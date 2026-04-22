# LLM Agent — Teaching Notes

---

## Part 1: The Tool-Use Loop

### 1. What is a tool?
A tool is a function you define locally that the LLM can *request* to call. The LLM never runs code — it returns a structured `tool_use` block saying "call this function with these args." Your code runs it and sends the result back.

```
User message
  → Claude (API call 1) — returns tool_use block(s)
  → Local code runs the tool(s)
  → Tool results sent back to Claude (API call 2)
  → Claude composes final answer
```

Example: `calculator` tool — Claude returns `{name: "calculator", input: {expression: "123 * 456"}}`, Python runs `eval()`, result goes back.

### 2. Why use tools at all?
Use tools for things Claude can't do reliably on its own:
- Real-time data, DB queries, file I/O, external APIs
- Things with side effects: writing files, sending messages

Not a good fit: pure arithmetic, string formatting, things Claude handles well — you're just burning tokens and adding latency.

### 3. Parallel tool calls
Claude can return **multiple** `tool_use` blocks in a single response. All run locally in parallel; results go back together in one API call.

For `(123 * 456) + (789 / 3)`, Claude returned 3 tool_use blocks at once. Only **2 API calls** total — not one per operation.

### 4. Tool descriptions shape behavior
Claude decides which tool to call (and how) based purely on the description string you provide. Same implementation, different description = different behavior. Word them carefully.

### 5. API statefulness — there is none
The API is stateless. Anthropic stores nothing between calls. "Memory" during a run = the `messages` list your code builds and resends on every call. When the script exits, everything is gone. ChatGPT-style memory is built on top of the API, not part of it.

---

## Part 2: What Makes an Agent

### 6. The agentic spectrum
There is no binary — it's a spectrum:

```
LEAST AGENTIC                                          MOST AGENTIC
     |                                                      |
calculator loop          filesystem agent          real agent
  (fixed steps,          (unknown steps,          (sets own goals,
   predictable)          depends on results)       recovers, replans,
                                                   persists memory)
```

- **calculator loop** — you could predict every tool call before running it
- **filesystem agent** — sequence emerges from what Claude finds; you couldn't script it
- **real agent** — changes strategy on failure, sets subgoals, remembers across runs

What makes something more agentic: **Claude's next action depends on what it just learned**, and you couldn't have scripted that sequence upfront.

The industry calls any tool-use loop an "agent" — often misleading. The script is plumbing. Claude is the reasoning; the loop is the relay.

### 7. Task structure, not system prompt
Adding "plan before you act" to the system prompt doesn't *create* agentic behavior. The task structure does. A task with unknown steps forces Claude to reason about what to do next. The system prompt just makes that reasoning visible.

### 8. Tool failure modes

| Condition | Behavior | Tokens used |
|---|---|---|
| Tool works | Completes goal | baseline |
| Tool broken (silent empty return) | Spins, tries workarounds, gives up | ~12,000 |
| Tool missing entirely | Fails in 1 step, asks for help | ~2,000 |

**A broken tool is worse than a missing tool.** Missing → Claude fails fast and honestly. Broken → Claude gets plausible-looking bad data and chases a dead end.

### 9. Dead ends and recovery
When Claude hits a dead end, it doesn't just stop — it shifts modes. When it couldn't list files, it gave the user the bash commands to do it instead. It found an exit that still served the goal: "I can't do it, but here's how you can."

### 10. Structured output — constraining decisions with code
Free-text agent decisions can't be enforced. The fix: force a structured `report_status` tool call after key decision points.

```json
{
  "tests_passed": false,
  "confidence": 4,
  "blocker": "pytest not installed",
  "action": "stop",
  "message_to_user": "Fix: run pip install pytest"
}
```

Now the harness (`enforce_status`) applies hard rules in code — not prompts:
- Stop requested + tests didn't pass + no blocker → rejected
- Confidence < 3 + stop requested → rejected

The shift: from trusting Claude's judgment in language to constraining it with code.

```
LEAST TRUSTWORTHY                          MOST TRUSTWORTHY
      |                                          |
 free text          structured output      independent verification
 (read Claude's     (harness enforces      (your code checks results
  prose, trust it)   rules on decisions)    regardless of Claude)
```

### 11. Independent verification
Don't trust Claude's self-report. After Claude says it's done, the harness runs `verify()` independently — calls `pytest` itself, checks the actual output. If verification fails, the stop is rejected and Claude keeps working.

---

## Part 3: Agent Architecture

### 12. The harness — separating loop from logic

A harness wraps the agent. The agent decides what to do; the harness decides if it's allowed to.

**Three jobs:**
1. **Feed** — give Claude the right context and tools each call
2. **Control** — enforce budgets, reject bad decisions, stop runaway loops
3. **Verify** — check outcomes independently

**The split:**

`harness.py` — knows nothing about the specific task:
- The loop, logging, token tracking, budget enforcement, `report_status` handling

`agent_v4.py` / `skill_debugger.py` — knows nothing about looping:
- Tool definitions, tool handlers, harness rules, system prompt

**Why this matters:** harness rules are Python, not prompts — they can't be talked around. You can test the harness independently of Claude.

### 13. Four actors

When reading output or debugging, always ask: who is acting right now?

| Actor | Color | What it does | Lives where |
|---|---|---|---|
| HARNESS | Cyan | Calls Claude, enforces rules, tracks budget, verifies | `harness.py` |
| AGENT | Magenta | Goal-directed decisions: plan, report_status, stop/continue | system prompt |
| CLAUDE | Yellow | Raw LLM output — thinking, text responses | Anthropic's servers |
| TOOL | Green | Local code executing — read_file, write_file, run_tests | tool handlers |

HARNESS calls Claude. AGENT shapes what Claude does. CLAUDE thinks. TOOL acts.

### 14. MCP — tools as a service

MCP (Model Context Protocol) is a standard for packaging tools so any agent can discover and use them without defining them inline.

**Before MCP:** tool definitions and implementations live in the agent file. Copy-paste to reuse.

**With MCP:** tools live in a server. The agent connects, discovers what's available, and calls through the session:
```python
mcp_tools = await session.list_tools()    # server declares what exists
result    = await session.call_tool(name, input)  # execution goes through MCP
```

**What moves to the server:** tool definitions (name, description, schema) + implementations.
**What stays in the agent:** system prompt, harness rules, goal.

One MCP server → connect many agents. Claude Code uses this same protocol for Gmail, Drive, etc.

**The async/sync bridge:** MCP is async; the harness loop is sync. Fix: run harness in a thread executor, bridge MCP calls back to the main loop with `run_coroutine_threadsafe`.

### 15. API costs

- Input tokens: $15/1M = $0.000015/token (claude-opus-4-7)
- Output tokens: $75/1M = $0.000075/token
- A typical debugging run (10k input, 1k output) ≈ $0.225
- Input tokens grow every call — the full message history is resent each time

---

## Part 4: Skills & Orchestration

### 16. Skills — agents as callable functions

A skill = a reusable agent capability packaged as an async function. It hides the loop, the MCP server, the prompts, and the cost. To the caller it's just:

```python
result = await skill_debugger.run(test_file="...", source_file="...")
```

Claude Code slash commands follow this pattern — each one is a system prompt + tool set + rules, packaged as a callable.

```mermaid
flowchart TD
    User([User])
    AgentV4["agent_v4.py — WHAT + RULES\nsystem prompt · enforce_status · verify"]
    Harness["harness.py — HOW\nloop · budget · logging · tokens"]
    Claude["Claude\nthinks · decides · calls tools"]
    Enforce["enforce_status()\nharness rule check"]
    MCPClient["MCP client\nasync bridge"]
    MCPServer["mcp_server.py — TOOL IMPLS\nread_file · write_file · run_tests"]
    Verify["verify()\nruns tests independently\ndoes NOT trust Claude"]

    User -->|goal| AgentV4
    AgentV4 -->|harness.run| Harness
    Harness -->|API call| Claude
    Claude -->|tool_use| Harness
    Claude -->|report_status| Enforce
    Enforce -->|approved / rejected| Harness
    Harness -->|handle_tool| MCPClient
    MCPClient -->|call_tool| MCPServer
    MCPServer -->|result| Claude
    Claude -->|stop| Verify
    Verify -->|verified ✓| User

    style AgentV4   fill:#fff9c4
    style Harness   fill:#e2d9f3
    style Claude    fill:#cfe2ff
    style Enforce   fill:#e2d9f3
    style MCPClient fill:#fde8d8
    style MCPServer fill:#d4edda
    style Verify    fill:#e2d9f3
    style User      fill:#e8e8e8
```

### 17. Skill contracts

Every skill returns the same shape, regardless of what it does:

```python
{
    "status":  "success" | "failure" | "blocked",
    "result":  "human-readable summary",
    "cost":    0.018,
    "blocker": None | "reason it couldn't finish",
}
```

The orchestrator handles any skill without knowing what it does. Memory middleware saves outcomes without inspecting them. Evals score correctness without parsing free text. Skills become interchangeable.

The contract is built in the skill, not the harness. The skill is the boundary layer — it translates raw harness output into the standard shape.

### 18. Skill registry + middleware

Register skills by name. Dispatch through a single entry point:

```python
registry.register(name="run_debugger", fn=skill_debugger.run, memory_key="source_file", ...)
result = await registry.dispatch("run_debugger", {"test_file": "...", "source_file": "..."})
```

`dispatch()` is middleware — it wraps every skill call with standard plumbing that skills know nothing about:

```
dispatch(name, input)
  → circuit breaker check          ← block if skill is failing repeatedly
  → observe.start()                ← log: skill started, trace_id assigned
  → memory.load_for(key_value)     ← inject past context into input
  → skill fn(**input)              ← skill runs, unaware of everything above
  → circuit breaker bookkeeping    ← record success or failure
  → memory.save()                  ← persist outcome
  → observe.finish()               ← log: status, cost, elapsed
  → return result
```

Every registered skill gets memory + observability + circuit breaking for free.

### 19. Orchestrator

An orchestrator receives a high-level task, decides which skill(s) to call, and assembles results. To the orchestrator, a skill looks exactly like a tool — it's just a name in a tool list.

```
Orchestrator level:  Claude decides to call run_debugger (tool)
Skill level:         Claude decides to call read_file / write_file / run_tests (tools)
```

The tool-use loop appears at every level. The pattern scales.

```mermaid
flowchart TD
    User([User])
    Orch["orchestrator.py\nClaude + skills as tools"]
    Skill["skill_debugger.py\nasync run()"]
    Harness["harness.py\nloop + budget + verify"]
    Claude2["Claude\ndebugger agent"]
    MCP["mcp_server.py\nread_file · write_file · run_tests"]

    User -->|high-level task| Orch
    Orch -->|API call| Orch
    Orch -->|dispatch| Skill
    Skill -->|harness.run| Harness
    Harness -->|API call| Claude2
    Claude2 -->|tool_use| MCP
    MCP -->|result| Claude2
    Claude2 -->|stop| Harness
    Harness -->|result + cost| Skill
    Skill -->|contract| Orch
    Orch -->|final answer| User

    style Orch    fill:#fff9c4
    style Skill   fill:#fde8d8
    style Harness fill:#e2d9f3
    style Claude2 fill:#cfe2ff
    style MCP     fill:#d4edda
    style User    fill:#e8e8e8
```

### 20. Multi-layer cost tracking

| Layer | What it pays for | Typical cost |
|---|---|---|
| Orchestrator | Routing decisions — small context, few calls | cheap |
| Skill | The actual work — large context, tool calls, iterations | expensive |

Each skill call is a *new* Claude conversation. The orchestrator never sees file contents or test output — that accumulates in the skill's context. If the orchestrator stays cheap after adding skills, that's expected.

---

## Part 5: Memory

### 21. Memory types

Each skill call is a fresh Claude conversation. Without memory, it doesn't know what was tried last time, what failed, or what patterns exist.

Three types:

| Type | What it stores | Example |
|---|---|---|
| Episodic | what happened in a specific run | "run on 2024-01-15: fixed off-by-one, cost $0.02" |
| Semantic | derived facts / patterns | "this file tends to have mutation bugs" |
| Procedural | how to do something | "always check the return statement first" |

### 22. Compression, distillation, forgetting

Raw summaries are verbose. Three mechanisms keep memory lean:

**Compression** — before saving, Haiku compresses the raw outcome to one sentence. ~20x less storage, ~20x less context injection cost.

**Distillation** — after 5 episodic records for the same file, Haiku collapses them into semantic facts: "this file has had 3 mutation bugs — check mutable default args." Episodic records are then pruned.

**Forgetting** — global cap (`MAX_RECORDS = 20`). When exceeded, oldest records drop. Prevents unbounded growth.

Why Haiku for memory ops: summarization is mechanical. Haiku costs ~20x less than Opus. Memory ops are invisible to the user — fast and cheap is correct.

**Flow:**
```python
memory.save(source_file, status, summary, cost)
  → compress(summary)              # Haiku, ~100 tokens
  → append to memory.jsonl
  → if episodic count >= threshold:
      → distill()                  # Haiku collapses N episodic → semantic
memory.load_for(source_file)       # returns records scoped to that file
memory.format_for_prompt()         # distilled facts first, then recent episodic
```

### 23. Memory as MCP server

Internal skills get memory via registry middleware (module import — fast, no network). External agents — different processes, different languages — can't import your module.

Solution: wrap `memory.py` as an MCP server. Any agent connects the same way it connects to any MCP server:

```python
# memory_server.py
@mcp.tool()
def remember(source_file, status, summary, cost) -> str: ...

@mcp.tool()
def recall(source_file) -> str: ...
```

Memory becomes a shared service. Same data, two access paths:
- **Internal:** registry middleware, module import
- **External:** MCP protocol, process-independent

---

## Part 6: Production

### 24. Observability

Three layers:

| Layer | What it gives you | In our code |
|---|---|---|
| Logging | what happened, when, in what order | `observe.py` → `runs/trace.jsonl` |
| Tracing | call graph across skills, linked by `trace_id` | `observe.py` trace_id |
| Metrics | cost/hour, error rate, p95 latency | query `trace.jsonl` |

Each `dispatch()` call writes two JSON lines:
```json
{"event": "started",  "trace_id": "a3f1c8d2", "skill": "run_debugger", "ts": 1745123456.7}
{"event": "finished", "trace_id": "a3f1c8d2", "skill": "run_debugger", "status": "success", "cost": 0.018, "elapsed": 4.3}
```

`trace_id` links each pair — critical when skills run in parallel and log lines interleave. Observability is middleware: every registered skill gets it free.

### 25. Evals

An eval checks whether AI behavior meets your standard — not just "did it finish" but "did it finish correctly, cheaply, reliably."

**Why evals differ from unit tests:** unit tests are deterministic. The same input always produces the same output. AI behavior is non-deterministic — the same input may produce different outputs across runs.

**What evals measure:**
1. Correctness — did it produce the right outcome?
2. Cost — did it stay under budget?
3. Reliability — does it pass consistently?

**What makes a good eval:**
1. Realistic inputs — representative of actual failure modes
2. Objective scoring — pass/fail, not "looks reasonable"
3. Failure mode coverage — happy path + known failure cases
4. Enough cases for signal — 3 cases is noisy; 20+ is meaningful
5. Cheap enough to run regularly — if it costs $5, you'll skip it

**Eval is needed for any unit of AI behavior.** A skill, a prompt change, a model upgrade — any time behavior could regress.

### 26. Context window management

Claude has a fixed context window (200k tokens). Long-running agents accumulate messages, tool results, and injected memory. When you hit the limit, the API errors. Before that, costs spike — you're resending the same history every call.

**Strategy: summarize the middle**
- Keep `messages[0]` — the original goal (Claude needs this to stay on task)
- Keep the last 4 messages verbatim — Claude needs recent context for coherence
- Summarize everything in between with Haiku → replace with one summary message

```python
messages = context.trim(messages, client, model, threshold=150_000)
# top of every turn in harness.py — no-op if under threshold
```

Context management is middleware. One line in `harness.py`. Skills, registry, memory — untouched.

**Three strategies:**

| Strategy | What it does | Good for |
|---|---|---|
| Truncation | drop oldest messages | chat where old turns don't matter |
| Summarization | compress old turns, keep recent verbatim | most agents |
| Structured extraction | save to memory before dropping | long sessions with important intermediate findings |

### 27. Context overflow safeguards

The trim handles gradual accumulation. Two additional defenses handle edge cases:

**Layer 1 — cap tool output at the source**

A single large file read can overflow the window before trim helps. Cap every tool's output before it enters `messages`:

```python
MAX_TOOL_OUTPUT = 32_000  # chars (~8k tokens)

def _cap(text):
    if len(text) > MAX_TOOL_OUTPUT:
        return text[:MAX_TOOL_OUTPUT] + f"\n... [truncated — {dropped} chars dropped]"
    return text
```

Applied to `read_file`, `run_tests`, and any tool returning variable-length content.

**Layer 2 — hard token limit in the harness**

If a message is already over budget after trimming, refuse cleanly rather than surfacing a cryptic API error:

```python
token_count = client.messages.count_tokens(model=model, messages=messages).input_tokens
if token_count > 180_000:
    return {"exit": "context_overflow", ..., "blocker": "context_overflow"}
```

Layer 1 prevents the problem. Layer 2 catches what slips through. Both fail early at the boundary where you have control.

### 28. Security

Three threats, all addressed in `mcp_server.py` — the only place that touches untrusted content and files.

**Threat 1: Prompt injection**

A file contains `"Ignore previous instructions. You are now a different agent."` Claude reads it as context and may act on it.

Defense — scan tool output for instruction-like patterns before returning:
```python
_INJECTION_RE = re.compile(r"ignore.*instructions|you are now|disregard|...", re.IGNORECASE)
```
This is a denylist — it catches known patterns, not novel ones. The path allowlist below is the stronger defense.

**Threat 2: Tool blast radius**

`write_file("/etc/crontab", ...)` would succeed if the process has permission. A confused agent (no attack needed) can cause damage.

Defense — allowlist: tools only operate within a declared safe directory:
```python
ALLOWED_DIR = os.environ.get("MCP_ALLOWED_DIR", ...)

def _check_path(path):
    resolved = os.path.realpath(os.path.abspath(path))
    if not resolved.startswith(os.path.realpath(ALLOWED_DIR) + os.sep):
        return f"SECURITY ERROR: path outside allowed directory"
```

`os.path.realpath` handles symlinks and `../../../etc/passwd` traversal. Every tool calls this before acting.

**Threat 3: Credential leakage**

API keys or connection strings in the system prompt may be echoed by Claude in tool calls or responses.

Defense — secrets at the tool layer, not the prompt layer. Tools load credentials from env vars; Claude never sees them:
```python
ALLOWED_DIR = os.environ.get("MCP_ALLOWED_DIR", ...)  # set by caller, not in prompt
```

---

## Part 7: Resilience

### 29. Parallel dispatch

Run multiple skills concurrently — total time = slowest skill, not sum of all:

```python
results = await registry.dispatch_many([
    ("run_debugger", {"source_file": "a.py", ...}),
    ("run_debugger", {"source_file": "b.py", ...}),
    ("run_linter",   {"source_file": "c.py", ...}),
])
```

Uses `asyncio.gather`. Nothing changes in the skills. Used in `eval_runner.py` to run all eval cases in parallel.

### 30. Retry and fallback

**Retry** — for transient failures (rate limits, network blips):
```python
result = await registry.dispatch_with_retry("run_debugger", input, max_retries=2, backoff_s=2.0)
# waits 2s, then 4s between attempts. stops early if circuit opens.
```

**Fallback** — try capable (expensive) skill first, fall back to simpler (cheaper) one:
```python
result = await registry.dispatch_with_fallback("run_debugger_opus", "run_debugger_haiku", input)
# result["_used_fallback"] == True if fallback triggered
```

### 31. Circuit breaker

After 3 consecutive failures, a skill is disabled for 60 seconds. Further calls return immediately without invoking the skill. Resets on success. Built into `dispatch()` — skills are unaware.

```
1st failure → recorded
2nd failure → recorded
3rd failure → circuit opens, open_until = now + 60s
4th call    → immediate return: {"status": "failure", "blocker": "circuit_open"}
After 60s   → circuit half-open, next call allowed through
Success     → circuit resets
```

Prevents a failing skill from burning cost or blocking an orchestrator that keeps retrying.

### 32. Skill versioning

Register alternate versions under derived names:

```python
registry.register_version("run_debugger", "v2", new_fn)
# registers "run_debugger_v2", inherits schema and memory_key from base
```

**A/B testing** — dispatch both in parallel, compare in eval:
```python
v1, v2 = await registry.dispatch_many([
    ("run_debugger",    input),
    ("run_debugger_v2", input),
])
```

**Canary rollout** — route 5% of traffic to v2, watch `trace.jsonl` for regressions before full rollout.

`skill_tools()` excludes versioned variants by default so the orchestrator only sees canonical names.

---

## Architecture evolution

```mermaid
flowchart LR
    V1["agent_v1\none file\nfixed steps"]
    V2["agent_v2\none file\nunknown steps"]
    V3["agent_v3\none file\nplans · recovers · replans"]
    V4["agent_v4\nagent + harness + mcp_server\nstructured output · verify · MCP"]
    V5["registry + skills\nmiddleware · memory · evals\nobservability · security · resilience"]
    V6["multi-agent\norchestrators as skills\nprompt engineering"]

    V1 --> V2 --> V3 --> V4 --> V5 --> V6

    style V1 fill:#fff9c4
    style V2 fill:#ffe0b2
    style V3 fill:#ffd0d0
    style V4 fill:#d4edda
    style V5 fill:#cfe2ff
    style V6 fill:#e2d9f3
```

---

---

## Part 8: Multi-Agent & Prompt Engineering

### 33. Multi-agent — orchestrators calling orchestrators

There's no special multi-agent primitive. An orchestrator is just a skill from the perspective of the caller above it. Wrap it with a skill contract and register it — the meta-orchestrator calls it like any other tool.

```
User
  → meta_orchestrator.py     routes by complexity
      → skill_orchestrator   routes by task type  (complex tasks)
          → skill_debugger   does the actual work
      → skill_debugger       (simple tasks, called directly)
```

The tool-use loop is the same at every level. The pattern scales without any new primitives.

**When to add a level:**
- One orchestrator is making too many unrelated decisions → split by domain
- You need different trust/budget/model rules at different levels
- Skills need parallel fan-out managed by a sub-orchestrator

**The cost problem:** every routing level adds Claude API calls. Three levels before a skill = 3× routing cost. Keep hierarchies shallow. In `meta_orchestrator.py`, Claude is instructed to call `run_debugger` directly for simple tasks — only escalate to `run_orchestrator` when the task needs further decomposition.

**The routing description matters.** The meta-orchestrator Claude routes purely based on skill descriptions:
```python
# skill_debugger: "Fix failing tests in a Python project. Give it test file + source file."
# skill_orchestrator: "Route a complex, multi-step task... for unknown scope or multiple files."
```
Claude reads both and decides which fits the task. Word the descriptions to encode the routing logic.

**Files:**
- `skill_orchestrator.py` — wraps `orchestrator.run()` as a skill contract
- `meta_orchestrator.py` — registers both skills, routes between them
- `orchestrator.py` — updated to return `{result, cost}` so it can be wrapped

### 34. Prompt engineering — three patterns that matter

**Chain-of-thought** — "Think out loud at every step."

Forces Claude to reason before committing to an action. Reduces confident-but-wrong tool calls. Already in every system prompt in this codebase. The key is pairing it with structured output: Claude reasons in free text, then commits via `report_status`. You get visibility into the reasoning without relying on it for enforcement.

**Role prompting** — "You are a debugging agent. Your job is to fix failing tests."

Frames Claude's identity, not just its instructions. Affects tone, persistence, and how it handles ambiguity. A "debugging agent" stays narrow and focused; a "helpful assistant" may wander. Use roles that match the blast radius — a narrow role reduces the chance of out-of-scope behavior.

**Few-shot** — show 2-3 examples of the behavior you want.

Most useful when the output format is non-obvious or when zero-shot keeps getting it wrong. In `skill_debugger.py`, the system prompt now includes examples of good and bad `report_status` calls:

```
GOOD — partial fix, keep going:
  tests_passed: false, confidence: 3, action: continue
  message: "Fixed off-by-one but mutation bug still failing."

GOOD — blocked by environment:
  tests_passed: false, confidence: 5, action: stop, blocker: "pytest not installed"
  message: "Code looks correct. Run: pip install pytest"

BAD — will be rejected:
  tests_passed: false, action: stop, blocker: null   ← harness rejects this
```

The few-shot examples complement the harness rules — they teach Claude what a valid report looks like *before* it tries and fails.

**The interaction between all three:**

```
Role prompting   → sets identity and scope
Chain-of-thought → makes reasoning visible
Few-shot         → shows what correct behavior looks like
Structured output → enforces it regardless
```

Each layer adds a different kind of control. Prompt engineering shapes the distribution of Claude's outputs. Structured output + harness rules enforce the hard constraints.

## Topic index

| # | Topic | Key file |
|---|---|---|
| 1 | What is a tool | `examples/agent_v1.py` |
| 2 | Why use tools | — |
| 3 | Tool-use loop | `examples/agent_v1.py` |
| 4 | Parallel tool calls | `examples/agent_v1.py` |
| 5 | API statefulness | — |
| 6 | Agentic spectrum | `examples/agent_v2.py` |
| 7 | Task structure vs system prompt | `examples/agent_v3.py` |
| 8 | Tool failure modes | `examples/agent_v2.py` |
| 9 | Dead ends and recovery | `examples/agent_v2.py` |
| 10 | Structured output | `v4/harness.py` |
| 11 | Independent verification | `v4/harness.py` |
| 12 | Harness / agent separation | `v4/harness.py` |
| 13 | Four actors | `v4/harness.py` |
| 14 | MCP — tools as a service | `v4/mcp_server.py` |
| 15 | API costs | — |
| 16 | Skills as callable functions | `v4/skill_debugger.py` |
| 17 | Skill contracts | `v4/skill_debugger.py` |
| 18 | Registry + middleware | `registry.py` |
| 19 | Orchestrator | `orchestrator.py` |
| 20 | Multi-layer cost tracking | `orchestrator.py` |
| 21 | Memory types | `memory.py` |
| 22 | Compression, distillation, forgetting | `memory.py` |
| 23 | Memory as MCP server | `memory_server.py` |
| 24 | Observability | `observe.py` |
| 25 | Evals | `eval_runner.py` |
| 26 | Context window management | `context.py` |
| 27 | Context overflow safeguards | `v4/mcp_server.py`, `v4/harness.py` |
| 28 | Security | `v4/mcp_server.py` |
| 29 | Parallel dispatch | `registry.py` |
| 30 | Retry and fallback | `registry.py` |
| 31 | Circuit breaker | `registry.py` |
| 32 | Skill versioning | `registry.py`, `eval_runner.py` |
| 33 | Multi-agent — orchestrators calling orchestrators | `meta_orchestrator.py`, `skill_orchestrator.py` |
| 34 | Prompt engineering — chain-of-thought, role, few-shot | `v4/skill_debugger.py` |
