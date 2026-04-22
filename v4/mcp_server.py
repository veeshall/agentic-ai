import os
import re
import sys
import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("filesystem-tools")

# ── Defense 2: path allowlist ─────────────────────────────────────────────────
# Tools only operate within this directory. Set via env var so the secret of
# where work happens never appears in the system prompt.
ALLOWED_DIR = os.environ.get("MCP_ALLOWED_DIR", os.path.dirname(os.path.abspath(__file__)))

# ── Defense 3: secrets at tool layer ─────────────────────────────────────────
# Any credentials the tools need live here, loaded from env — never in the prompt.
# Example: DB_URL = os.environ.get("DB_URL") if you had a db query tool.

MAX_TOOL_OUTPUT = 32_000  # chars (~8k tokens)

# ── Defense 1: injection patterns ────────────────────────────────────────────
_INJECTION_PATTERNS = [
    r"ignore (all |previous |prior )?instructions",
    r"you are now",
    r"new persona",
    r"system prompt",
    r"disregard",
    r"do not follow",
    r"forget (everything|all|your instructions)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def _cap(text: str) -> str:
    if len(text) > MAX_TOOL_OUTPUT:
        dropped = len(text) - MAX_TOOL_OUTPUT
        return text[:MAX_TOOL_OUTPUT] + f"\n... [truncated — {dropped} chars dropped]"
    return text


def _sanitize(text: str) -> str:
    """Flag content that looks like a prompt injection attempt."""
    if _INJECTION_RE.search(text):
        return (
            "[SECURITY: tool output contained instruction-like patterns and was blocked. "
            "The file may contain adversarial content. Proceed with caution.]"
        )
    return text


def _check_path(path: str) -> str | None:
    """Return an error string if path is outside the allowed directory, else None."""
    resolved = os.path.realpath(os.path.abspath(path))
    allowed  = os.path.realpath(ALLOWED_DIR)
    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        return f"SECURITY ERROR: path '{path}' is outside the allowed directory '{ALLOWED_DIR}'"
    return None


@mcp.tool()
def read_file(path: str) -> str:
    """Read the contents of a file."""
    if err := _check_path(path):
        return err
    try:
        with open(path) as f:
            return _sanitize(_cap(f.read()))
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write content to a file, replacing its current contents."""
    if err := _check_path(path):
        return err
    try:
        with open(path, "w") as f:
            f.write(content)
        return f"Written successfully to {path}"
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def run_tests(path: str) -> str:
    """Run pytest on a test file. Returns full output including pass/fail details."""
    if err := _check_path(path):
        return err
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", path, "-v"],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.abspath(path))
        )
        return _cap(result.stdout + result.stderr)
    except Exception as e:
        return f"ERROR: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
