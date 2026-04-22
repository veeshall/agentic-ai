# agentic-ai

A progressive learning codebase for building LLM agents with the Anthropic API.
Built incrementally — each concept is layered on top of the previous one.

## Structure

```
agentic-ai/
├── agent/                 # The debugger agent (harness + MCP tools + skill)
│   ├── harness.py         # Agent loop: budget, confirm, enforce, verify
│   ├── mcp_server.py      # MCP tool server: read_file, write_file, run_tests
│   ├── skill_debugger.py  # Debugger packaged as a callable skill
│   ├── buggy.py           # Sample buggy source (eval target)
│   ├── test_buggy.py      # Sample test file (eval target)
│   └── prompts/
│       └── debugger.md    # System prompt for the debugger agent
│
├── middleware/            # Cross-cutting concerns (all skills get these for free)
│   ├── registry.py        # Skill registry + dispatch (memory, observability, circuit breaker)
│   ├── memory.py          # Per-skill memory store (compress → distill → forget)
│   ├── memory_server.py   # Memory exposed as an MCP server (for external agents)
│   ├── observe.py         # Structured JSONL logging (trace_id links start/finish)
│   └── context.py         # Context window trimming (summarize middle with Haiku)
│
├── orchestration/         # Orchestrators (route tasks to skills via Claude)
│   ├── orchestrator.py    # Single-level: receives task, calls skills
│   ├── skill_orchestrator.py  # Orchestrator wrapped as a callable skill
│   ├── meta_orchestrator.py   # Routes between skill_debugger and skill_orchestrator
│   └── prompts/
│       ├── orchestrator.md
│       └── meta_orchestrator.md
│
├── eval/                  # Eval suite
│   ├── runner.py          # Runs all cases in parallel, reports correctness + cost
│   ├── case_01_mutation/
│   ├── case_02_off_by_one/
│   └── case_03_wrong_return/
│
├── examples/              # Teaching examples (v1–v4, standalone scripts)
│   ├── agent_v1.py        # Raw tool-use loop
│   ├── agent_v2.py        # Open-ended filesystem agent
│   ├── agent_v3.py        # Planning + recovery
│   ├── agent_v4.py        # Runs the debugger skill directly
│   ├── tool_descriptions.py  # Shows how description wording changes behavior
│   └── task_budget.py     # Demonstrates the task-budgets beta API feature
│
├── runs/                  # Runtime output: logs, traces, memory (gitignored)
├── CLAUDE.md
├── README.md
└── learning_notes.md
```

## Key patterns

**Skill contract** — every skill returns `{status, result, cost, blocker}`. The registry
enforces this; callers never need to know the implementation.

**Registry middleware** — `registry.dispatch()` wraps every skill call with memory
injection, observability logging, and circuit breaker logic. Skills are unaware of any of it.

**System prompts as files** — all agent prompts live in `prompts/*.md`. Edit them without
touching Python. Loaded at import time via `open(_PROMPT_FILE).read()`.

**Multi-agent** — orchestrators are wrapped as skills and registered like any other tool.
The tool-use loop is identical at every level of the hierarchy.

## Running things

```bash
# Run the eval suite
python3.12 eval/runner.py

# Route a task through the orchestrator
python3.12 orchestration/orchestrator.py

# Route through the meta-orchestrator
python3.12 orchestration/meta_orchestrator.py

# Run the debugger skill directly (no orchestrator)
python3.12 examples/agent_v4.py
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | required | Anthropic API key |
| `MCP_ALLOWED_DIR` | `agent/` dir | Path allowlist for MCP file tools |

## Models used

- Orchestration and debugging: `claude-opus-4-7`
- Context summarization: `claude-haiku-4-5-20251001`
