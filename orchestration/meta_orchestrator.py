"""
Meta-orchestrator — routes tasks to either a specialist skill or a sub-orchestrator.

This demonstrates the multi-agent pattern:
  meta_orchestrator → skill_orchestrator → skill_debugger → harness → Claude

At every level, the caller sees the level below as a tool.
The tool-use loop is the same pattern throughout.

Run with:
    python3.12 meta_orchestrator.py
"""

import sys
import asyncio
import os

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "middleware"))

import registry
import skill_debugger
import skill_orchestrator
import anthropic

client = anthropic.Anthropic()

PRICE_PER_INPUT_TOKEN  = 15 / 1_000_000
PRICE_PER_OUTPUT_TOKEN = 75 / 1_000_000

# ── Register skills at this level ─────────────────────────────────────────────
# Both a specialist skill and a sub-orchestrator are available.
# The meta-orchestrator Claude decides which to call based on task complexity.

registry.register(
    name=skill_debugger.SKILL_DEF["name"],
    description=skill_debugger.SKILL_DEF["description"],
    schema=skill_debugger.SKILL_DEF["schema"],
    fn=skill_debugger.run,
    memory_key=skill_debugger.SKILL_DEF.get("memory_key"),
)

registry.register(
    name=skill_orchestrator.SKILL_DEF["name"],
    description=skill_orchestrator.SKILL_DEF["description"],
    schema=skill_orchestrator.SKILL_DEF["schema"],
    fn=skill_orchestrator.run,
)

_PROMPT_FILE = os.path.join(os.path.dirname(__file__), "prompts", "meta_orchestrator.md")
SYSTEM_PROMPT = open(_PROMPT_FILE).read().strip()


async def run(task: str):
    print(f"\n{'='*60}")
    print(f"META-ORCHESTRATOR RECEIVED:\n{task}")
    print(f"{'='*60}\n")

    messages = [{"role": "user", "content": task}]
    meta_cost  = 0.0
    child_cost = 0.0

    while True:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            tools=registry.skill_tools(),
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        call_cost = (response.usage.input_tokens * PRICE_PER_INPUT_TOKEN +
                     response.usage.output_tokens * PRICE_PER_OUTPUT_TOKEN)
        meta_cost += call_cost

        for block in response.content:
            if block.type == "text":
                print(f"[meta] thinking: {block.text}")
            elif block.type == "tool_use":
                print(f"[meta] routing to: {block.name}")

        if response.stop_reason == "end_turn":
            final = next((b.text for b in response.content if b.type == "text"), "")
            total = meta_cost + child_cost
            print(f"\n{'='*60}")
            print(f"META-ORCHESTRATOR DONE:\n{final}")
            print(f"\n--- COST BREAKDOWN ---")
            print(f"  meta-orchestrator: ${meta_cost:.4f}")
            print(f"  child handlers:    ${child_cost:.4f}")
            print(f"  TOTAL:             ${total:.4f}")
            return final

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                outcome = await registry.dispatch(block.name, block.input)
                child_cost += outcome["cost"]
                print(f"[meta] {block.name} → {outcome['status']}  cost: ${outcome['cost']:.4f}")

                if outcome["status"] == "success":
                    content = outcome["result"]
                elif outcome["status"] == "blocked":
                    content = f"BLOCKED: {outcome['blocker']}\n{outcome['result']}"
                else:
                    content = f"FAILED: {outcome['result']}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                })

        messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    asyncio.run(run(
        "I have a Python project where the tests are failing. "
        f"Test file: {os.path.abspath('agent/test_buggy.py')}. "
        f"Source file: {os.path.abspath('agent/buggy.py')}. "
        "Please fix it."
    ))
