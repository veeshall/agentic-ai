"""
Debugger skill — fixes failing tests in a Python file.

This is agent_v4 packaged as a callable function so an orchestrator
can invoke it as a tool, just like any other tool.

Usage:
    from skill_debugger import run
    result = asyncio.run(run(test_file="...", source_file="..."))
"""

import sys
import asyncio
import subprocess
import os

sys.path.insert(0, os.path.dirname(__file__))
import harness

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MCP_SERVER = os.path.join(os.path.dirname(__file__), "mcp_server.py")
DIR = os.path.dirname(__file__)

SKILL_DEF = {
    "name": "run_debugger",
    "description": (
        "Fix failing tests in a Python project. "
        "Give it the path to the test file and the source file. "
        "It will read the code, find the bug, fix it, and verify tests pass."
    ),
    "schema": {
        "type": "object",
        "properties": {
            "test_file":   {"type": "string", "description": "Path to the pytest test file"},
            "source_file": {"type": "string", "description": "Path to the source file under test"},
        },
        "required": ["test_file", "source_file"],
    },
    "memory_key": "source_file",
}

REPORT_STATUS_TOOL = {
    "name": "report_status",
    "description": "Call this after every test run to report your assessment.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tests_passed":    {"type": "boolean"},
            "confidence":      {"type": "integer", "description": "1-5"},
            "blocker":         {"type": "string"},
            "action":          {"type": "string", "enum": ["continue", "stop"]},
            "message_to_user": {"type": "string"},
        },
        "required": ["tests_passed", "confidence", "blocker", "action", "message_to_user"],
    },
}

_PROMPT_FILE = os.path.join(os.path.dirname(__file__), "prompts", "debugger.md")
SYSTEM_PROMPT = open(_PROMPT_FILE).read().strip()


async def run(test_file: str, source_file: str, memory_context: str = "") -> dict:
    """
    Fix failing tests in source_file so that test_file passes.
    Returns a contract dict: {status, result, cost, blocker}.
    """
    system_prompt = SYSTEM_PROMPT
    if memory_context:
        system_prompt += f"\n\n{memory_context}"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[MCP_SERVER],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = await session.list_tools()

            tools = [
                {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
                for t in mcp_tools.tools
            ] + [REPORT_STATUS_TOOL]

            main_loop = asyncio.get_event_loop()

            def handle_tool(name: str, input: dict) -> str:
                future = asyncio.run_coroutine_threadsafe(
                    session.call_tool(name, input), main_loop
                )
                return future.result().content[0].text

            def enforce_status(status: dict):
                if status["action"] == "stop" and not status["tests_passed"] and not status["blocker"]:
                    return "REJECTED: tests didn't pass and no blocker reported. Keep trying."
                if status["action"] == "stop" and status["confidence"] < 3:
                    return f"REJECTED: confidence {status['confidence']}/5 is too low to stop."
                return None

            def verify() -> bool:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", test_file, "-v"],
                    capture_output=True, text=True,
                    cwd=os.path.dirname(test_file)
                )
                return "passed" in result.stdout and "failed" not in result.stdout

            result = await main_loop.run_in_executor(None, lambda: harness.run(
                goal=f"Fix the failing tests in {test_file}. The code under test is in {source_file}.",
                tools=tools,
                system_prompt=system_prompt,
                handle_tool=handle_tool,
                enforce_status=enforce_status,
                verify=verify,
                max_attempts=5,
                max_cost_usd=0.50,
                confirm_tools=["write_file"],
                log_path=os.path.join(DIR, "..", "runs", f"skill_debugger_{os.getpid()}.log"),
            ))

            exit_path = result.get("exit", "unknown") if isinstance(result, dict) else "unknown"
            cost      = result.get("cost", 0.0)    if isinstance(result, dict) else 0.0
            message   = result.get("result", "")   if isinstance(result, dict) else str(result)
            blocker   = result.get("blocker")      if isinstance(result, dict) else None

            if exit_path == "approved_stop" and not blocker:
                status = "success"
            elif exit_path == "approved_stop" and blocker:
                status = "blocked"
            else:
                status = "failure"

            return {
                "status":  status,
                "result":  message,
                "cost":    cost,
                "blocker": blocker,
            }
