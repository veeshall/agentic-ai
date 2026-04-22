# LLM Agent — Teaching Codebase

Progressive build of an LLM agent system, from a basic tool-use loop to a production-ready skill infrastructure with memory, observability, security, and evals.

## Structure

```
test/
├── examples/           # Early iterations (teaching examples, not production)
│   ├── agent_v1.py     # Calculator tool, fixed steps
│   ├── agent_v2.py     # Filesystem tools, open-ended goal
│   ├── agent_v3.py     # + planning, error recovery, colored logging
│   └── agent_v4.py     # Runs the debugger skill directly
│
├── v4/                 # Production agent components
│   ├── harness.py      # The loop: budget, logging, verification, context trimming
│   ├── mcp_server.py   # Tool implementations (read_file, write_file, run_tests)
│   ├── skill_debugger.py  # Debugger skill — fixes failing tests
│   ├── buggy.py        # Sample buggy source file
│   └── test_buggy.py   # Sample test file
│
├── eval/               # Eval test cases
│   ├── case_01_mutation/
│   ├── case_02_off_by_one/
│   └── case_03_wrong_return/
│
├── runs/               # Runtime output (logs, traces, memory) — gitignore this
│
├── registry.py         # Skill registry + middleware dispatch
├── memory.py           # File-based memory with compression and distillation
├── memory_server.py    # Memory exposed as an MCP server
├── observe.py          # Structured logging to runs/trace.jsonl
├── context.py          # Context window trimming
├── orchestrator.py     # Orchestrator — routes tasks to skills via Claude
├── eval_runner.py      # Runs eval cases, prints correctness/cost/time table
├── task_budget.py      # Token + cost budget tracking utilities
├── tool_descriptions.py  # Demonstrates how tool descriptions shape Claude's behavior
└── learning_notes.md   # Full teaching notes for all 30 topics
```

## Running

```bash
# Run the eval suite (dispatches all 3 cases in parallel)
python3.12 eval_runner.py

# Run the orchestrator against a real task
python3.12 orchestrator.py

# Run the debugger skill directly
python3.12 examples/agent_v4.py

# Start the memory MCP server
python3.12 memory_server.py
```

## Environment

```bash
export ANTHROPIC_API_KEY=...
export MCP_ALLOWED_DIR=/path/to/safe/working/dir   # limits file tool access
```

## Key concepts

| Concept | Where |
|---|---|
| Skill contract `{status, result, cost, blocker}` | `v4/skill_debugger.py` |
| Registry middleware (memory + observability injected automatically) | `registry.py` |
| Memory: compress → distill → forget | `memory.py` |
| Context trim + hard overflow guard | `context.py`, `v4/harness.py` |
| Security: injection detection, path allowlist, secrets via env | `v4/mcp_server.py` |
| Parallel dispatch, retry, fallback, circuit breaker | `registry.py` |
| Skill versioning + A/B eval | `registry.py`, `eval_runner.py` |

## Full teaching notes

See [learning_notes.md](learning_notes.md) — 30 topics from tool-use basics through production patterns.
