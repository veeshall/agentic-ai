"""
Observability middleware — structured logging for every skill call.

Writes one JSON line per event to runs/trace.jsonl.
Two events per dispatch: "started" and "finished".
A shared trace_id links them so you can reconstruct the full call.

Skills know nothing about this. It lives entirely in registry.dispatch().
"""

import json
import os
import time
import uuid

TRACE_FILE = os.path.join(os.path.dirname(__file__), "runs", "trace.jsonl")


def _write(record: dict) -> None:
    os.makedirs(os.path.dirname(TRACE_FILE), exist_ok=True)
    with open(TRACE_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def start(skill_name: str, input_keys: list) -> dict:
    """Log that a skill call has begun. Returns a context dict to pass to finish()."""
    trace_id = str(uuid.uuid4())[:8]
    ts = time.time()
    _write({
        "event":      "started",
        "trace_id":   trace_id,
        "skill":      skill_name,
        "input_keys": input_keys,
        "ts":         ts,
    })
    return {"trace_id": trace_id, "started_at": ts}


def finish(ctx: dict, skill_name: str, result: dict) -> None:
    """Log the outcome of a skill call."""
    elapsed = round(time.time() - ctx["started_at"], 2)
    _write({
        "event":    "finished",
        "trace_id": ctx["trace_id"],
        "skill":    skill_name,
        "status":   result.get("status"),
        "cost":     result.get("cost", 0.0),
        "elapsed":  elapsed,
        "blocker":  result.get("blocker"),
    })
