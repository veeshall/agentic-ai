"""
Context window management — trims the message list before each Claude call.

If the conversation is approaching the token limit, the oldest messages
(excluding the original goal and the most recent turns) are summarized
by Haiku and replaced with a single summary message.

Skills, registry, and memory know nothing about this. It lives in harness.py.
"""

import anthropic

SUMMARY_MODEL   = "claude-haiku-4-5-20251001"
KEEP_RECENT     = 4   # always keep the last N messages verbatim
KEEP_GOAL       = 1   # always keep messages[0] (the original user goal)


def trim(messages: list, client: anthropic.Anthropic, model: str, threshold: int = 150_000) -> list:
    """
    Count tokens. If over threshold, summarize the middle of the conversation.
    Returns a (possibly shorter) messages list.
    """
    token_count = client.messages.count_tokens(
        model=model,
        messages=messages,
    ).input_tokens

    if token_count <= threshold:
        return messages

    # Split: keep goal + recent tail; summarize everything in between
    head = messages[:KEEP_GOAL]
    tail = messages[-KEEP_RECENT:]
    middle = messages[KEEP_GOAL:-KEEP_RECENT]

    if not middle:
        return messages  # nothing to trim

    # Flatten middle into plain text for summarization
    flat = []
    for m in middle:
        role = m["role"]
        content = m["content"]
        if isinstance(content, str):
            flat.append(f"{role}: {content}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    flat.append(f"{role}: {block['text']}")
                elif isinstance(block, dict) and block.get("type") == "tool_result":
                    flat.append(f"tool_result: {block.get('content', '')}")

    summary_input = "\n".join(flat)

    haiku = anthropic.Anthropic()
    response = haiku.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": (
                "Summarize the following agent conversation in 3 sentences. "
                "Focus on: what was tried, what worked, what is still unresolved.\n\n"
                f"{summary_input}"
            ),
        }],
    )
    summary_text = response.content[0].text

    summary_message = {
        "role":    "user",
        "content": f"[Context summary — earlier turns compressed]\n{summary_text}",
    }

    trimmed = head + [summary_message] + tail
    return trimmed
