"""
Claude Task Budgets — agentic loop example.

Requires:
  pip install anthropic
  export ANTHROPIC_API_KEY=...

Only supported on claude-opus-4-7 with the task-budgets-2026-03-13 beta header.
"""

import anthropic

MODEL = "claude-opus-4-7"
BETA = "task-budgets-2026-03-13"

client = anthropic.Anthropic()


# ---------------------------------------------------------------------------
# Example tools
# ---------------------------------------------------------------------------

tools = [
    {
        "name": "bash",
        "description": "Run a shell command and return stdout + stderr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."}
            },
            "required": ["command"],
        },
    }
]


def run_tools(content: list) -> list:
    """Execute any tool_use blocks and return tool_result blocks."""
    import subprocess

    results = []
    for block in content:
        if block.type != "tool_use":
            continue
        if block.name == "bash":
            try:
                out = subprocess.run(
                    block.input["command"],
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                output = out.stdout + out.stderr
            except Exception as e:
                output = f"Error: {e}"
        else:
            output = f"Unknown tool: {block.name}"

        results.append(
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output or "(no output)",
            }
        )
    return results


# ---------------------------------------------------------------------------
# Agentic loop with task budget
# ---------------------------------------------------------------------------

def run_with_budget(
    task: str,
    total_budget: int = 64_000,
    remaining: int | None = None,
) -> tuple[str, int]:
    """
    Run an agentic loop for `task` with a task budget.

    Args:
        task:          The user prompt / task description.
        total_budget:  Total token budget for the full agentic loop (min 20,000).
        remaining:     Budget carried over from a prior request (e.g. after
                       context compaction). Defaults to `total_budget`.

    Returns:
        (final_text, tokens_spent)
    """
    if total_budget < 20_000:
        raise ValueError("task_budget.total must be at least 20,000 tokens.")

    messages = [{"role": "user", "content": task}]
    tokens_spent = 0
    final_text = ""

    task_budget: dict = {"type": "tokens", "total": total_budget}
    if remaining is not None:
        task_budget["remaining"] = remaining

    print(f"[budget] total={total_budget:,}  remaining={remaining or total_budget:,}")

    turn = 0
    while True:
        turn += 1
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16_384,          # per-request hard cap
            messages=messages,
            tools=tools,
            output_config={
                "effort": "high",
                "task_budget": task_budget,
            },
            betas=[BETA],
        )

        tokens_this_turn = response.usage.output_tokens
        tokens_spent += tokens_this_turn
        print(
            f"[turn {turn}] stop_reason={response.stop_reason}  "
            f"output_tokens={tokens_this_turn:,}  total_spent={tokens_spent:,}"
        )

        # Collect any text blocks for the final answer
        for block in response.content:
            if hasattr(block, "text"):
                final_text = block.text  # keep last text block as the answer

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            # max_tokens or unexpected stop
            print(f"[warn] unexpected stop_reason: {response.stop_reason}")
            break

        # Execute tools and continue the loop
        tool_results = run_tools(response.content)
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        # On subsequent turns, omit `remaining` so the server tracks the countdown.
        # Only set it if you compact context between turns (see docs).
        task_budget = {"type": "tokens", "total": total_budget}

    print(f"[budget] finished — {tokens_spent:,} / {total_budget:,} tokens used")
    return final_text, tokens_spent


# ---------------------------------------------------------------------------
# Measure baseline token usage (no budget)
# ---------------------------------------------------------------------------

def measure_token_usage(task: str) -> int:
    """
    Run a task WITHOUT a budget to measure how many tokens it naturally uses.
    Useful for sizing your task_budget.total before enabling budgets.
    """
    messages = [{"role": "user", "content": task}]
    total = 0
    turn = 0

    while True:
        turn += 1
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16_384,
            messages=messages,
            tools=tools,
            betas=[BETA],
        )
        total += response.usage.output_tokens
        print(f"[measure turn {turn}] output_tokens={response.usage.output_tokens:,}  running={total:,}")

        if response.stop_reason != "tool_use":
            break

        tool_results = run_tools(response.content)
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    print(f"[measure] total tokens used: {total:,}")
    return total


# ---------------------------------------------------------------------------
# Example: carry budget across context compaction
# ---------------------------------------------------------------------------

def run_with_compaction(task: str, total_budget: int = 128_000) -> str:
    """
    Demonstrates passing `remaining` after you compact (summarize) context.
    In real usage, replace `summarize_messages()` with your own compaction logic.
    """
    messages = [{"role": "user", "content": task}]
    tokens_spent = 0

    while True:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16_384,
            messages=messages,
            tools=tools,
            output_config={
                "effort": "high",
                "task_budget": {
                    "type": "tokens",
                    "total": total_budget,
                    "remaining": total_budget - tokens_spent,  # carry the countdown
                },
            },
            betas=[BETA],
        )

        tokens_spent += response.usage.output_tokens

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return ""

        tool_results = run_tools(response.content)
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        # --- compact context here if needed ---
        # messages = summarize_messages(messages)
        # After compaction, `remaining` on the next request ensures the
        # countdown continues correctly instead of resetting to `total`.


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    task = "List the files in the current directory and summarize what you find."

    answer, spent = run_with_budget(task, total_budget=64_000)
    print("\n--- Answer ---")
    print(answer)
