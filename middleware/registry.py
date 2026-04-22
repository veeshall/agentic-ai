"""
Skill registry — maps skill names to their definitions and callables.

dispatch() is the single entry point for all skill calls.
Standard plumbing (memory, observability) lives here — skills know nothing about it.

Also provides:
  dispatch_many()      — parallel fan-out to multiple skills
  dispatch_with_retry()  — automatic retry with backoff
  dispatch_with_fallback() — try primary, fall back to secondary on failure
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import memory
import observe

REGISTRY: dict = {}

# ── Circuit breaker state ─────────────────────────────────────────────────────
# Per-skill failure tracking. If a skill fails too many times in a window,
# further calls are blocked immediately without invoking the skill.
_CIRCUIT: dict = {}             # name -> {failures, open_until}
CB_THRESHOLD   = 3              # failures before opening the circuit
CB_TIMEOUT_S   = 60             # seconds before allowing a retry


def register(name: str, description: str, schema: dict, fn, memory_key: str = None) -> None:
    REGISTRY[name] = {
        "description": description,
        "schema":      schema,
        "fn":          fn,
        "memory_key":  memory_key,
    }
    _CIRCUIT[name] = {"failures": 0, "open_until": 0}


def register_version(base_name: str, version: str, fn) -> None:
    """Register an alternate version of an existing skill under '<base_name>_<version>'.
    Inherits description, schema, and memory_key from the base registration.
    """
    versioned_name = f"{base_name}_{version}"
    if base_name not in REGISTRY:
        raise ValueError(f"Base skill '{base_name}' not registered")
    base = REGISTRY[base_name]
    register(
        name=versioned_name,
        description=base["description"] + f" [{version}]",
        schema=base["schema"],
        fn=fn,
        memory_key=base.get("memory_key"),
    )


def skill_tools(exclude_versions: bool = True) -> list:
    """Return the tools list Claude needs — built from whatever is registered.
    By default excludes versioned variants (names containing '_v') so the
    orchestrator only sees canonical skill names.
    """
    return [
        {"name": k, "description": v["description"], "input_schema": v["schema"]}
        for k, v in REGISTRY.items()
        if not (exclude_versions and "_v" in k)
    ]


def _circuit_check(name: str) -> str | None:
    """Return an error string if the circuit is open, else None."""
    cb = _CIRCUIT.get(name, {"failures": 0, "open_until": 0})
    if cb["open_until"] > time.time():
        remaining = round(cb["open_until"] - time.time())
        return f"CIRCUIT OPEN: skill '{name}' is temporarily disabled ({remaining}s remaining)"
    return None


def _circuit_record_failure(name: str) -> None:
    cb = _CIRCUIT[name]
    cb["failures"] += 1
    if cb["failures"] >= CB_THRESHOLD:
        cb["open_until"] = time.time() + CB_TIMEOUT_S
        print(f"[REGISTRY] circuit opened for '{name}' — {CB_THRESHOLD} failures, pausing {CB_TIMEOUT_S}s")


def _circuit_record_success(name: str) -> None:
    _CIRCUIT[name] = {"failures": 0, "open_until": 0}


async def dispatch(name: str, input: dict) -> dict:
    """Single entry point for all skill calls. Middleware: observe, memory, circuit breaker."""
    if name not in REGISTRY:
        raise ValueError(f"Unknown skill: {name}")

    # ── circuit breaker ───────────────────────────────────────────────────────
    if err := _circuit_check(name):
        return {"status": "failure", "result": err, "cost": 0.0, "blocker": "circuit_open"}

    entry      = REGISTRY[name]
    memory_key = entry.get("memory_key")
    key_value  = input.get(memory_key) if memory_key else None

    # ── middleware: observe start ─────────────────────────────────────────────
    ctx = observe.start(name, input_keys=list(input.keys()))

    # ── middleware: memory in ─────────────────────────────────────────────────
    if key_value:
        records = memory.load_for(key_value)
        input = {**input, "memory_context": memory.format_for_prompt(records)}

    # ── skill runs ────────────────────────────────────────────────────────────
    result = await entry["fn"](**input)

    # ── circuit breaker bookkeeping ───────────────────────────────────────────
    if result["status"] == "failure":
        _circuit_record_failure(name)
    else:
        _circuit_record_success(name)

    # ── middleware: memory out ────────────────────────────────────────────────
    if key_value:
        memory.save(
            source_file=key_value,
            status=result["status"],
            summary=result["result"],
            cost=result["cost"],
        )

    # ── middleware: observe finish ────────────────────────────────────────────
    observe.finish(ctx, name, result)

    return result


async def dispatch_many(calls: list[tuple[str, dict]]) -> list[dict]:
    """Fan-out: dispatch multiple skills in parallel, return results in the same order.

    Usage:
        results = await dispatch_many([
            ("run_debugger", {"test_file": "...", "source_file": "a.py"}),
            ("run_debugger", {"test_file": "...", "source_file": "b.py"}),
        ])
    """
    return list(await asyncio.gather(*[dispatch(name, inp) for name, inp in calls]))


async def dispatch_with_retry(name: str, input: dict, max_retries: int = 2, backoff_s: float = 2.0) -> dict:
    """Dispatch with automatic retry on failure. Uses exponential backoff.
    Stops early if the circuit opens.
    """
    last_result = None
    for attempt in range(max_retries + 1):
        if attempt > 0:
            wait = backoff_s ** attempt
            print(f"[REGISTRY] retry {attempt}/{max_retries} for '{name}' in {wait:.1f}s")
            await asyncio.sleep(wait)
        last_result = await dispatch(name, input)
        if last_result["status"] != "failure":
            return last_result
        if last_result.get("blocker") == "circuit_open":
            break  # no point retrying if circuit is open
    return last_result


async def dispatch_with_fallback(primary: str, fallback: str, input: dict) -> dict:
    """Try primary skill first. On failure, try fallback.
    Both results are returned so callers can log/compare them.
    """
    result = await dispatch(primary, input)
    if result["status"] != "failure":
        return result
    print(f"[REGISTRY] '{primary}' failed — falling back to '{fallback}'")
    fallback_result = await dispatch(fallback, input)
    fallback_result["_used_fallback"] = True
    return fallback_result
