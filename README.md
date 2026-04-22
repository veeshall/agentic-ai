# LLM Agent — Teaching Codebase

Progressive build of an LLM agent system, from a basic tool-use loop to a production-ready skill infrastructure with memory, observability, security, and evals.

## Structure

```
agentic-ai/
├── agent/                 # The debugger agent (harness + MCP server + skill)
│   ├── harness.py         # Agent loop: budget, confirm, enforce, verify
│   ├── mcp_server.py      # MCP tool server: read_file, write_file, run_tests
│   ├── skill_debugger.py  # Debugger packaged as a callable skill
│   ├── buggy.py           # Sample buggy source (eval target)
│   ├── test_buggy.py      # Sample test file (eval target)
│   └── prompts/
│       └── debugger.md    # System prompt for the debugger agent
│
├── middleware/            # Cross-cutting concerns injected automatically via registry
│   ├── registry.py        # Skill registry + dispatch (memory, observability, circuit breaker)
│   ├── memory.py          # Per-skill memory (compress → distill → forget)
│   ├── memory_server.py   # Memory as an MCP server (for external agents)
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
├── examples/              # Teaching examples (standalone, not production)
│   ├── agent_v1.py        # Calculator tool, fixed steps
│   ├── agent_v2.py        # Filesystem tools, open-ended goal
│   ├── agent_v3.py        # + planning, error recovery
│   ├── agent_v4.py        # Runs the debugger skill directly
│   ├── tool_descriptions.py  # How description wording changes behavior
│   └── task_budget.py     # Task-budgets beta API feature
│
├── runs/                  # Runtime output: logs, traces, memory (gitignored)
├── CLAUDE.md              # Project context for AI coding assistants
└── learning_notes.md      # Full teaching notes for all 35 topics
```

## Running

```bash
# Run the eval suite (all 3 cases in parallel)
python3.12 eval/runner.py

# Route a task through the orchestrator
python3.12 orchestration/orchestrator.py

# Route through the meta-orchestrator
python3.12 orchestration/meta_orchestrator.py

# Run the debugger skill directly (no orchestrator)
python3.12 examples/agent_v4.py

# Start the memory MCP server
python3.12 middleware/memory_server.py
```

## Environment

```bash
export ANTHROPIC_API_KEY=...
export MCP_ALLOWED_DIR=/path/to/safe/working/dir   # limits file tool access (defaults to agent/)
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
| Multi-agent: orchestrators as skills | `skill_orchestrator.py`, `meta_orchestrator.py` |
| System prompts as external `.md` files | `prompts/`, `v4/prompts/` |

## Full teaching notes

See [learning_notes.md](learning_notes.md) — 35 topics from tool-use basics through production patterns.
