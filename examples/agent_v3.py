import anthropic
import os

client = anthropic.Anthropic()

# Terminal colors
BLUE   = "\033[94m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
RESET  = "\033[0m"

COLORS = {
    "USER GOAL": WHITE,
    "CALLING CLAUDE": BLUE,
    "CLAUDE THINKING / PLANNING": YELLOW,
    "CLAUDE WANTS TO CALL": BLUE,
    "STOP REASON": BLUE,
    "TOKENS THIS CALL": CYAN,
    "RUNNING LOCALLY": GREEN,
    "LOCAL RESULT": GREEN,
    "LOCAL RESULT (ERROR — Claude will decide what to do)": RED,
    "SENDING RESULTS BACK TO CLAUDE": WHITE,
    "AGENT DONE": GREEN,
    "TOTAL TOKENS": CYAN,
}

tools = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns an error message if the file can't be read.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"],
        },
    },
]

def run_tool(name: str, input: dict) -> str:
    if name == "read_file":
        try:
            with open(input["path"], "r") as f:
                return f.read()
        except Exception as e:
            return f"ERROR: {e}"
    raise ValueError(f"Unknown tool: {name}")

def log(step, label, content=""):
    color = COLORS.get(label, RESET)
    print(f"\n{color}--- step {step}: {label} ---{RESET}")
    if content:
        print(f"{color}{content}{RESET}")

def run_agent(goal: str):
    messages = [{"role": "user", "content": goal}]
    step = 0
    total_input_tokens = 0
    total_output_tokens = 0

    step += 1
    log(step, "USER GOAL (sent to Claude)", goal)

    while True:
        step += 1
        log(step, f"CALLING CLAUDE ({len(messages)} messages in history)")

        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            tools=tools,
            system="""You are an agent with filesystem tools.

Before calling any tools, always start by writing out your plan — what steps you intend to take and why.

As you work:
- If a tool returns an ERROR or unexpected result, try to get the same information through the other tool before giving up.
- If you find something unexpected, say so and revise your plan before continuing.
- Only stop when you are confident you have a complete and correct answer.

Think out loud at every step.""",
            messages=messages,
        )

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        for block in response.content:
            if block.type == "text":
                log(step, "CLAUDE THINKING / PLANNING", block.text)
            elif block.type == "tool_use":
                log(step, f"CLAUDE WANTS TO CALL: {block.name}", str(block.input))

        log(step, "TOKENS THIS CALL",
            f"input: {response.usage.input_tokens}  "
            f"output: {response.usage.output_tokens}  "
            f"running total in: {total_input_tokens}  out: {total_output_tokens}")

        log(step, "STOP REASON", response.stop_reason)

        if response.stop_reason == "end_turn":
            final = next((b.text for b in response.content if b.type == "text"), "")
            print(f"\n=== AGENT DONE ===\n{final}")
            print(f"\n=== TOTAL TOKENS === input: {total_input_tokens}  output: {total_output_tokens}")
            return final

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                step += 1
                log(step, f"RUNNING LOCALLY: {block.name}({block.input})")
                result = run_tool(block.name, block.input)

                if result.startswith("ERROR"):
                    log(step, "LOCAL RESULT (ERROR — Claude will decide what to do)", result)
                else:
                    log(step, "LOCAL RESULT", result)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "user", "content": tool_results})

        step += 1
        log(step, "SENDING RESULTS BACK TO CLAUDE", f"{len(tool_results)} result(s)")


if __name__ == "__main__":
    run_agent("How many functions are defined across all .py files in /Users/veeshall/code/test?")
