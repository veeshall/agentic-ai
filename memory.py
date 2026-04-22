"""
File-based memory for agent skills.

Each run appends one JSON record to a .jsonl file (one object per line).
On the next run, past records are loaded and injected into the system prompt
so Claude acts like it remembers what happened before.

This is the simplest possible memory — no database, no vector search.
It works well when the number of past runs is small (< ~20).
"""

import json
import os
from datetime import datetime
import anthropic

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "runs", "memory.jsonl")
MAX_RECORDS = 20        # global cap across all files
DISTILL_THRESHOLD = 5   # distill a file's episodic records once it reaches this many

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _compress(raw_summary: str, status: str) -> str:
    """Ask Claude to compress a run summary to one sentence. ~100 input tokens."""
    response = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": (
                f"Compress this into one sentence for a future debugging agent "
                f"(status was: {status}):\n\n{raw_summary}"
            ),
        }],
    )
    return response.content[0].text.strip()


def _distill(episodic_records: list, source_file: str) -> dict:
    """
    Collapse N episodic records into one semantic fact record.
    The facts describe patterns, not individual runs.
    """
    summaries = "\n".join(
        f"- [{r['timestamp']} status={r['status']}] {r['summary']}"
        for r in episodic_records
    )
    response = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": (
                "You are building a memory for a future debugging agent.\n"
                "Given these past run summaries, extract 2-3 stable facts about "
                "this codebase that would help a future agent debug it faster.\n"
                "Write facts, not history. No timestamps, no 'last time' — just what is true.\n\n"
                f"{summaries}"
            ),
        }],
    )
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source_file": os.path.abspath(source_file),
        "type": "distilled",
        "facts": response.content[0].text.strip(),
        "distilled_from": len(episodic_records),
    }


def save(source_file: str, status: str, summary: str, cost: float) -> None:
    """Compress summary, append record, distill if threshold reached, prune if over cap."""
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)

    compressed = _compress(summary, status)
    target = os.path.abspath(source_file)

    new_record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source_file": target,
        "status": status,
        "summary": compressed,
        "cost": round(cost, 4),
    }

    all_records = _read_all()
    all_records.append(new_record)

    # Check if this file's episodic records hit the distill threshold
    episodic = [r for r in all_records if r.get("source_file") == target and r.get("type") != "distilled"]
    if len(episodic) >= DISTILL_THRESHOLD:
        print(f"[memory] distilling {len(episodic)} records for {os.path.basename(source_file)}...")
        distilled = _distill(episodic, source_file)
        # Replace all episodic records for this file with the one distilled record
        all_records = [r for r in all_records if r.get("source_file") != target or r.get("type") == "distilled"]
        all_records.append(distilled)
        print(f"[memory] distilled → {distilled['facts'][:80]}...")

    # Global cap
    all_records = all_records[-MAX_RECORDS:]

    with open(MEMORY_FILE, "w") as f:
        for r in all_records:
            f.write(json.dumps(r) + "\n")


def _read_all() -> list:
    """Read every record from the memory file."""
    if not os.path.exists(MEMORY_FILE):
        return []
    records = []
    with open(MEMORY_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_for(source_file: str) -> list:
    """Return all past records for a given source file, oldest first."""
    target = os.path.abspath(source_file)
    return [r for r in _read_all() if r.get("source_file") == target]


def format_for_prompt(records: list) -> str:
    """Format past records as a text block to inject into a system prompt."""
    if not records:
        return ""
    lines = []
    for r in records:
        if r.get("type") == "distilled":
            lines.append(f"Known facts about this codebase (distilled from {r['distilled_from']} past runs):\n{r['facts']}")
        else:
            lines.append(
                f"  - {r['timestamp']}  status={r['status']}  cost=${r['cost']:.4f}\n"
                f"    {r['summary']}"
            )
    if not lines:
        return ""
    # Put distilled facts first — they're more useful than individual episodes
    distilled = [l for l in lines if l.startswith("Known facts")]
    episodic  = [l for l in lines if not l.startswith("Known facts")]
    ordered = distilled + (["Recent runs:"] + episodic if episodic else [])
    return "\n".join(ordered)
