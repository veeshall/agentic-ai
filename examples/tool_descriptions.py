import anthropic

client = anthropic.Anthropic()

# Same tool, three different descriptions.
# We'll run the same question through each and watch how Claude behaves differently.

VARIANTS = {
    "A — broad": "Perform arithmetic.",

    "B — narrow": "Only use for expressions involving numbers with more than 6 digits. Do not use for simple math.",

    "C — opinionated": "Use this when the user explicitly asks to calculate something. Do not use for math you can do in your head.",
}

QUESTION = "What is 12 + 7?"

def make_tool(description: str) -> dict:
    return {
        "name": "calculator",
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string"}
            },
            "required": ["expression"],
        },
    }

def run(variant_name: str, description: str):
    print(f"\n{'='*60}")
    print(f"VARIANT {variant_name}")
    print(f"Description: \"{description}\"")
    print(f"Question: \"{QUESTION}\"")
    print(f"{'='*60}")

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        tools=[make_tool(description)],
        messages=[{"role": "user", "content": QUESTION}],
    )

    tool_calls = [b for b in response.content if b.type == "tool_use"]
    text_blocks = [b for b in response.content if b.type == "text"]

    if tool_calls:
        for t in tool_calls:
            print(f"\n  → CALLED TOOL: calculator('{t.input['expression']}')")
        print(f"  (Claude decided to use the tool)")
    else:
        answer = text_blocks[0].text if text_blocks else ""
        print(f"\n  → NO TOOL CALLED. Claude answered directly:")
        print(f"  \"{answer}\"")

    print(f"\n  stop_reason: {response.stop_reason}")
    print(f"  input tokens: {response.usage.input_tokens}  output tokens: {response.usage.output_tokens}")


if __name__ == "__main__":
    print("\nSame question, same tool, three descriptions — watch how behavior changes.\n")
    for name, desc in VARIANTS.items():
        run(name, desc)
