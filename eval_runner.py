"""
Eval runner — runs the debugger skill against known buggy cases and scores the results.

Each case has a buggy source file and a test file.
The eval checks: did the skill fix it? how much did it cost? how long did it take?

Run with:
    python3.12 eval_runner.py
"""

import sys
import asyncio
import os

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "v4"))

import registry
import skill_debugger

registry.register(
    name=skill_debugger.SKILL_DEF["name"],
    description=skill_debugger.SKILL_DEF["description"],
    schema=skill_debugger.SKILL_DEF["schema"],
    fn=skill_debugger.run,
    memory_key=skill_debugger.SKILL_DEF.get("memory_key"),
)

# Register a second version for A/B comparison.
# In practice this would point to a different fn (different model, different prompt).
# Here it reuses the same fn to show the wiring.
registry.register_version("run_debugger", "v2", skill_debugger.run)

EVAL_DIR = os.path.join(os.path.dirname(__file__), "eval")

CASES = [
    {
        "name":        "mutation bug",
        "test_file":   os.path.join(EVAL_DIR, "case_01_mutation",    "test_source.py"),
        "source_file": os.path.join(EVAL_DIR, "case_01_mutation",    "source.py"),
        "expected":    "success",
    },
    {
        "name":        "off-by-one",
        "test_file":   os.path.join(EVAL_DIR, "case_02_off_by_one",  "test_source.py"),
        "source_file": os.path.join(EVAL_DIR, "case_02_off_by_one",  "source.py"),
        "expected":    "success",
    },
    {
        "name":        "wrong return",
        "test_file":   os.path.join(EVAL_DIR, "case_03_wrong_return", "test_source.py"),
        "source_file": os.path.join(EVAL_DIR, "case_03_wrong_return", "source.py"),
        "expected":    "success",
    },
]

COST_BUDGET = 0.50  # fail the case if it costs more than this


async def main():
    print(f"\n{'='*60}")
    print(f"EVAL RUN — {len(CASES)} cases")
    print(f"{'='*60}")

    # ── Parallel fan-out: run all cases at once ───────────────────────────────
    calls = [("run_debugger", {"test_file": c["test_file"], "source_file": c["source_file"]})
             for c in CASES]
    raw = await registry.dispatch_many(calls)
    results = []
    for case, outcome in zip(CASES, raw):
        passed      = outcome["status"] == case["expected"]
        under_budget = outcome["cost"] <= COST_BUDGET
        results.append({
            "name":         case["name"],
            "status":       outcome["status"],
            "expected":     case["expected"],
            "correct":      passed,
            "cost":         outcome["cost"],
            "under_budget": under_budget,
            "elapsed_s":    0.0,   # not tracked in dispatch_many; use observe trace for timing
            "blocker":      outcome.get("blocker"),
        })

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"{'Case':<20} {'Expected':<10} {'Actual':<10} {'Correct':<10} {'Cost':>8} {'Time':>8}")
    print(f"{'─'*20} {'─'*10} {'─'*10} {'─'*10} {'─'*8} {'─'*8}")

    total_cost = 0.0
    passed = 0
    for r in results:
        correct_str = "✓" if r["correct"] else "✗"
        blocker_str = f" [{r['blocker']}]" if r["blocker"] else ""
        print(
            f"{r['name']:<20} {r['expected']:<10} {r['status']:<10} "
            f"{correct_str:<10} ${r['cost']:>6.4f} {r['elapsed_s']:>6.1f}s"
            f"{blocker_str}"
        )
        total_cost += r["cost"]
        if r["correct"]:
            passed += 1

    print(f"{'─'*20} {'─'*10} {'─'*10} {'─'*10} {'─'*8} {'─'*8}")
    print(f"{'TOTAL':<20} {'':<10} {'':<10} {passed}/{len(results)} passed   ${total_cost:.4f}")
    print()

    # ── Version comparison: run first case against v1 and v2 in parallel ─────
    print(f"\n{'='*60}")
    print(f"VERSION COMPARISON — case: {CASES[0]['name']}")
    print(f"{'='*60}")
    v_input = {"test_file": CASES[0]["test_file"], "source_file": CASES[0]["source_file"]}
    v1, v2 = await registry.dispatch_many([
        ("run_debugger",    v_input),
        ("run_debugger_v2", v_input),
    ])
    print(f"{'Version':<16} {'Status':<10} {'Cost':>8}")
    print(f"{'─'*16} {'─'*10} {'─'*8}")
    print(f"{'run_debugger':<16} {v1['status']:<10} ${v1['cost']:>6.4f}")
    print(f"{'run_debugger_v2':<16} {v2['status']:<10} ${v2['cost']:>6.4f}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
