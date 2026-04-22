"""
Orchestrator — receives a high-level task, breaks it into parts,
dispatches to specialist skills.

The key point: the orchestrator doesn't know HOW the debugger skill works.
It just calls it by name with inputs, same as any other tool.
That's the same tool-use pattern — but the "tool" is another agent.
"""

import sys
import asyncio
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "middleware"))
import skill_debugger

import registry
import anthropic

client = anthropic.Anthropic()

# ── Register all skills ───────────────────────────────────────────────────────
# Adding a new skill = one register() call here. Orchestrator picks it up automatically.

registry.register(
    name=skill_debugger.SKILL_DEF["name"],
    description=skill_debugger.SKILL_DEF["description"],
    schema=skill_debugger.SKILL_DEF["schema"],
    fn=skill_debugger.run,
    memory_key=skill_debugger.SKILL_DEF.get("memory_key"),
)

_PROMPT_FILE = os.path.join(os.path.dirname(__file__), "prompts", "orchestrator.md")
SYSTEM_PROMPT = open(_PROMPT_FILE).read().strip()


PRICE_PER_INPUT_TOKEN  = 15 / 1_000_000
PRICE_PER_OUTPUT_TOKEN = 75 / 1_000_000

async def run(task: str):
    print(f"\n{'='*60}")
    print(f"ORCHESTRATOR RECEIVED TASK:\n{task}")
    print(f"{'='*60}\n")

    messages = [{"role": "user", "content": task}]
    orchestrator_cost = 0.0
    skills_cost = 0.0

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
        orchestrator_cost += call_cost

        for block in response.content:
            if block.type == "text":
                print(f"[orchestrator thinking] {block.text}")
            elif block.type == "tool_use":
                print(f"[orchestrator] decided to call skill: {block.name}")

        print(f"[orchestrator cost] this call: ${call_cost:.4f}  "
              f"orchestrator total: ${orchestrator_cost:.4f}")

        if response.stop_reason == "end_turn":
            final = next((b.text for b in response.content if b.type == "text"), "")
            total_cost = orchestrator_cost + skills_cost
            print(f"\n{'='*60}")
            print(f"ORCHESTRATOR DONE:\n{final}")
            print(f"\n--- COST BREAKDOWN ---")
            print(f"  orchestrator (Claude calls): ${orchestrator_cost:.4f}")
            print(f"  skills (debugger etc.):      ${skills_cost:.4f}")
            print(f"  TOTAL:                       ${total_cost:.4f}")
            return {"result": final, "cost": total_cost}

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                outcome = await registry.dispatch(block.name, block.input)
                skills_cost += outcome["cost"]
                print(f"\n[orchestrator] skill status:  {outcome['status']}")
                print(f"[orchestrator] skill result:  {outcome['result']}")
                if outcome["blocker"]:
                    print(f"[orchestrator] skill blocker: {outcome['blocker']}")
                print(f"[orchestrator] skill cost: ${outcome['cost']:.4f}  "
                      f"skills total: ${skills_cost:.4f}\n")

                # Tell Claude what actually happened — include status so it can react
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
    outcome = asyncio.run(run(
        "I have a Python project where the tests are failing. "
        f"Test file: {os.path.abspath('agent/test_buggy.py')}. "
        f"Source file: {os.path.abspath('agent/buggy.py')}. "
        "Please fix it."
    ))
    print(f"\nResult: {outcome['result']}")
