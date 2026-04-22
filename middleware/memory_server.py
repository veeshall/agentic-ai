"""
Memory MCP server — exposes memory operations as tools any agent can call.

Tools:
  remember(source_file, status, summary, cost) — save a run record
  recall(source_file)                          — get relevant memories as prompt text

Usage (stdio):
  python3.12 memory_server.py

Any agent can connect to this server and use memory without importing memory.py directly.
Same flat file backend — just a different interface.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import memory

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("memory")


@mcp.tool()
def remember(source_file: str, status: str, summary: str, cost: float) -> str:
    """Save a run record to memory. Status must be success, blocked, or failure."""
    memory.save(source_file=source_file, status=status, summary=summary, cost=cost)
    return f"Saved memory for {os.path.basename(source_file)} (status={status})"


@mcp.tool()
def recall(source_file: str) -> str:
    """Return past run memories for a source file, formatted for a system prompt."""
    records = memory.load_for(source_file)
    if not records:
        return "No past memories for this file."
    return memory.format_for_prompt(records)


if __name__ == "__main__":
    mcp.run(transport="stdio")
