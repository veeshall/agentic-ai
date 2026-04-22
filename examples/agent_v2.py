import anthropic
import os

client = anthropic.Anthropic()

tools = [
    {
        "name": "list_dir",
        "description": "List files in a directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"}
            },
            "required": ["path"],
        },
    },
]

def run_tool(name: str, input: dict) -> str:
    if name == "list_dir":
        try:
            entries = os.listdir(input["path"])
            return "\n".join(entries)
        except Exception as e:
            return f"Error: {e}"
    if name == "read_file":
        try:
            with open(input["path"], "r") as f:
                return f.read()
        except Exception as e:
            return f"Error: {e}"
    raise ValueError(f"Unknown tool: {name}")

def log(step, label, content):
    print(f"\n--- step {step}: {label} ---")
    print(content)

def run_agent(goal: str):
    messages = [{"role": "user", "content": goal}]
    step = 0

    step += 1
    log(step, "USER GOAL (sent to Claude)", goal)

    while True:
        step += 1
        log(step, f"CALLING CLAUDE ({len(messages)} messages in history)", "")

        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            tools=tools,
            system="You are an agent with access to filesystem tools. Use them step by step to achieve the goal. Think out loud about what you're doing.",
            messages=messages,
        )

        for block in response.content:
            if block.type == "text":
                log(step, "CLAUDE SAID", block.text)
            elif block.type == "tool_use":
                log(step, f"CLAUDE WANTS TO CALL: {block.name}", str(block.input))

        log(step, "CLAUDE STOP REASON", response.stop_reason)
        log(step, "TOKENS", f"input: {response.usage.input_tokens}  output: {response.usage.output_tokens}  cache_read: {getattr(response.usage, 'cache_read_input_tokens', 0)}  cache_write: {getattr(response.usage, 'cache_creation_input_tokens', 0)}")

        if response.stop_reason == "end_turn":
            final = next(b.text for b in response.content if b.type == "text")
            print(f"\n=== DONE ===\n{final}")
            return final

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                step += 1
                log(step, f"RUNNING LOCALLY: {block.name}({block.input})", "")
                result = run_tool(block.name, block.input)
                log(step, "LOCAL RESULT", result)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "user", "content": tool_results})

        step += 1
        log(step, "SENDING TOOL RESULTS BACK TO CLAUDE", f"{len(tool_results)} result(s)")


if __name__ == "__main__":
    run_agent("How many functions are defined across all .py files in /Users/veeshall/code/test?")
