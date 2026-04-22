import anthropic

client = anthropic.Anthropic()

tools = [
    {
        "name": "calculator",
        "description": "Perform basic arithmetic. Returns the result as a number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression, e.g. '2 + 2'"}
            },
            "required": ["expression"],
        },
    }
]

def run_tool(name: str, input: dict) -> str:
    if name == "calculator":
        return str(eval(input["expression"]))
    raise ValueError(f"Unknown tool: {name}")

def print_table(rows: list[dict]):
    headers = ["Step", "Input", "Claude did", "Local did", "Output"]
    col_widths = [len(h) for h in headers]
    for row in rows:
        vals = [str(row.get(h, "")) for h in headers]
        for i, v in enumerate(vals):
            col_widths[i] = max(col_widths[i], len(v))

    def fmt_row(vals):
        return "| " + " | ".join(v.ljust(col_widths[i]) for i, v in enumerate(vals)) + " |"

    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    print("\n" + sep)
    print(fmt_row(headers))
    print(sep)
    for row in rows:
        print(fmt_row([str(row.get(h, "—")) for h in headers]))
    print(sep + "\n")

def run_agent(user_message: str) -> str:
    messages = [{"role": "user", "content": user_message}]
    log = []
    turn = 0
    step = 0

    while True:
        turn += 1
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=16000,
            tools=tools,
            system="Use the calculator tool only for individual arithmetic operations you cannot do in your head. Once you have all the tool results, compute any final combination yourself and answer directly.",
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            final_text = next(b.text for b in response.content if b.type == "text")
            step += 1
            log.append({
                "Step": step,
                "Input": f"tool results (turn {turn-1})" if turn > 1 else user_message,
                "Claude did": "Composed final answer",
                "Local did": "—",
                "Output": final_text,
            })
            print_table(log)
            return final_text

        messages.append({"role": "assistant", "content": response.content})

        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        calls_summary = ", ".join(f"{b.name}({b.input})" for b in tool_blocks)

        step += 1
        step_input = user_message if turn == 1 else "both tool results"
        log.append({
            "Step": step,
            "Input": step_input,
            "Claude did": f"Requested {len(tool_blocks)} tool call(s): {calls_summary}",
            "Local did": "—",
            "Output": f"{len(tool_blocks)} tool_use block(s)",
        })

        tool_results = []
        for i, block in enumerate(tool_blocks, 1):
            result = run_tool(block.name, block.input)
            log.append({
                "Step": f"{step}.{i}",
                "Input": f"tool_use: {block.input}",
                "Claude did": "—",
                "Local did": f"eval('{block.input['expression']}')",
                "Output": result,
            })
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    answer = run_agent("What is (123 * 456) + (789 / 3)?")
    print(f"Final answer: {answer}")
