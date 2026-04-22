"""
Orchestrator skill — wraps orchestrator.run() with a standard skill contract.

This is what makes multi-agent work: the orchestrator is just a skill
from the perspective of whoever calls it. Same contract, same dispatch path.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "v4"))
import orchestrator

SKILL_DEF = {
    "name": "run_orchestrator",
    "description": (
        "Route a complex, multi-step engineering task to the right specialist skills. "
        "Use this when the task involves multiple files, unknown scope, or requires "
        "deciding between different types of work (debugging, reviewing, testing). "
        "For simple single-file tasks, call the specialist skill directly instead."
    ),
    "schema": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "High-level task description"},
        },
        "required": ["task"],
    },
}


async def run(task: str, memory_context: str = "") -> dict:
    """
    Route a task through the orchestrator.
    Returns a contract dict: {status, result, cost, blocker}.
    """
    if memory_context:
        task = f"{task}\n\nContext from previous runs:\n{memory_context}"

    try:
        outcome = await orchestrator.run(task)
        return {
            "status":  "success",
            "result":  outcome["result"] or "Done",
            "cost":    outcome["cost"],
            "blocker": None,
        }
    except Exception as e:
        return {
            "status":  "failure",
            "result":  str(e),
            "cost":    0.0,
            "blocker": None,
        }
