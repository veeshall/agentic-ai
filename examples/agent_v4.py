"""
agent_v4 — runs the debugger skill directly (no orchestrator).
To run via orchestrator instead, use: python3.12 orchestrator.py
"""

import sys
import asyncio
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
from skill_debugger import run

DIR = os.path.join(os.path.dirname(__file__), "..", "agent")

if __name__ == "__main__":
    result = asyncio.run(run(
        test_file=os.path.join(DIR, "test_buggy.py"),
        source_file=os.path.join(DIR, "buggy.py"),
    ))
    print(f"\nResult: {result}")
