import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import anthropic
from datetime import datetime
import context

client = anthropic.Anthropic()

# ─── Four actors, four colors ────────────────────────────────────────────────
#
#   [HARNESS] CYAN    — the Python loop: calls Claude, enforces rules, tracks budget
#   [AGENT]   MAGENTA — goal-directed reasoning: the system prompt + report_status decisions
#                       (defined in agent_v4.py — shapes HOW Claude behaves)
#   [CLAUDE]  YELLOW  — the raw LLM output: thinking, text responses
#                       (Claude's words, before the agent interprets them)
#   [TOOL]    GREEN   — local code executing: read_file, write_file, run_tests
#
#   RED is used by any actor to signal an error or rejection.
#
#   HARNESS calls Claude. AGENT shapes what Claude does. CLAUDE thinks. TOOL acts.

CYAN    = "\033[96m"
MAGENTA = "\033[95m"
YELLOW  = "\033[93m"
GREEN   = "\033[92m"
RED     = "\033[91m"
WHITE   = "\033[97m"
RESET   = "\033[0m"

HARNESS = CYAN
AGENT   = MAGENTA
CLAUDE  = YELLOW
TOOL    = GREEN

# ─── Pricing (claude-opus-4-7, per token) ────────────────────────────────────
# Change these if you switch models.
PRICE_PER_INPUT_TOKEN  = 15 / 1_000_000   # $15 per 1M input tokens
PRICE_PER_OUTPUT_TOKEN = 75 / 1_000_000   # $75 per 1M output tokens


# ─── Logging ─────────────────────────────────────────────────────────────────
# Every log line goes to stdout AND to a file so you can replay what happened.

_log_file = None

def _write_log(text: str):
    if _log_file:
        _log_file.write(text + "\n")
        _log_file.flush()

def log(step, label, content="", color=WHITE):
    actor = ""
    if color == HARNESS: actor = "[HARNESS] "
    elif color == AGENT:  actor = "[AGENT]   "
    elif color == CLAUDE: actor = "[CLAUDE]  "
    elif color == TOOL:   actor = "[TOOL]    "
    elif color == RED:    actor = "[ERROR]   "
    line = f"\n--- step {step}: {actor}{label} ---"
    print(f"{color}{line}{RESET}")
    _write_log(line)
    if content:
        print(f"{color}{content}{RESET}")
        _write_log(content)


# ─── Cost tracker ────────────────────────────────────────────────────────────

def _cost(input_tokens: int, output_tokens: int) -> float:
    return input_tokens * PRICE_PER_INPUT_TOKEN + output_tokens * PRICE_PER_OUTPUT_TOKEN


# ─── Human-in-the-loop ───────────────────────────────────────────────────────
# Tools listed here will pause and ask for confirmation before running.
# The agent doesn't know this is happening — it just sees the result.

def _confirm(tool_name: str, tool_input: dict) -> bool:
    print(f"\n{HARNESS}[HARNESS] ⚠ HUMAN APPROVAL NEEDED{RESET}")
    print(f"{HARNESS}  tool:  {tool_name}{RESET}")
    print(f"{HARNESS}  input: {tool_input}{RESET}")
    answer = input(f"{HARNESS}  Allow? (y/n): {RESET}").strip().lower()
    return answer == "y"


# ─── Tool retry ──────────────────────────────────────────────────────────────
# If a tool returns ERROR, the harness retries before telling Claude.
# Claude only sees the final result — it doesn't need to handle retries itself.

def _run_with_retry(handle_tool, name: str, input: dict, max_retries: int = 2) -> str:
    for attempt in range(max_retries + 1):
        result = handle_tool(name, input)
        if not result.startswith("ERROR") or attempt == max_retries:
            return result
        print(f"{RED}  tool error (retry {attempt+1}/{max_retries}): {result}{RESET}")
    return result


# ─── Main harness loop ───────────────────────────────────────────────────────

def run(
    goal: str,
    tools: list,
    system_prompt: str,
    handle_tool,
    enforce_status=None,
    verify=None,              # function() -> bool  — independent verification after agent stops
    max_attempts: int = 5,
    max_cost_usd: float = 1.0,
    confirm_tools: list = (), # tool names that require human approval before running
    log_path: str = None,     # file to write the run log to
):
    """
    Run an agent loop.

    tools           — tool definitions to give Claude
    system_prompt   — the agent's instructions (memory context already injected by caller)
    handle_tool     — function(name, input) -> str: runs a tool locally
    enforce_status  — function(status) -> str|None: harness rules on report_status.
                      return a rejection string to block, None to approve.
    verify          — function() -> bool: independent check after agent claims done.
                      harness runs this itself — doesn't trust Claude's self-report.
    max_attempts    — budget: max run_tests calls before forced stop
    max_cost_usd    — budget: max dollars before forced stop
    confirm_tools   — tool names that need human approval before running
    log_path        — if set, writes full run log to this file
    """
    global _log_file

    # ── Set up file logging ──────────────────────────────────────────────────
    # Every run gets its own timestamped log file so you can replay it later.
    if log_path is None:
        log_path = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    _log_file = open(log_path, "w")
    _write_log(f"RUN STARTED: {datetime.now()}")
    _write_log(f"GOAL: {goal}\n")

    messages = [{"role": "user", "content": goal}]
    step = 0
    attempt = 0
    total_in = 0
    total_out = 0
    total_cost = 0.0

    step += 1
    log(step, "USER GOAL", goal, WHITE)

    try:
        while True:
            step += 1

            # ── middleware: context window trim ──────────────────────────────
            messages = context.trim(messages, client, "claude-opus-4-7")

            # ── hard context limit ───────────────────────────────────────────
            # If even after trimming we're over the limit, stop cleanly rather
            # than letting the API return a cryptic error.
            token_count = client.messages.count_tokens(
                model="claude-opus-4-7", messages=messages
            ).input_tokens
            if token_count > 180_000:
                log(step, "CONTEXT OVERFLOW",
                    f"Input is {token_count} tokens after trim — exceeds hard limit. Stopping.", RED)
                _print_summary(total_in, total_out, total_cost)
                return {"exit": "context_overflow", "result": "Context too large to continue",
                        "cost": total_cost, "blocker": "context_overflow"}

            log(step, f"CALLING CLAUDE (attempt {attempt+1}/{max_attempts}, {len(messages)} messages, {token_count} tokens)", color=CLAUDE)

            response = client.messages.create(
                model="claude-opus-4-7",
                max_tokens=4096,
                tools=tools,
                system=system_prompt,
                messages=messages,
            )

            total_in   += response.usage.input_tokens
            total_out  += response.usage.output_tokens
            call_cost   = _cost(response.usage.input_tokens, response.usage.output_tokens)
            total_cost += call_cost

            for block in response.content:
                if block.type == "text":
                    log(step, "RAW RESPONSE (thinking out loud)", block.text, CLAUDE)
                elif block.type == "tool_use":
                    log(step, f"AGENT DECIDED TO CALL: {block.name}", str(block.input), AGENT)

            log(step, "TOKENS + COST",
                f"input: {response.usage.input_tokens}  output: {response.usage.output_tokens}  "
                f"call cost: ${call_cost:.4f}  total cost: ${total_cost:.4f}  limit: ${max_cost_usd:.2f}", HARNESS)

            # ── Cost limit ───────────────────────────────────────────────────
            # Stops the agent if it's spending too much — regardless of progress.
            if total_cost >= max_cost_usd:
                log(step, "COST LIMIT REACHED",
                    f"Spent ${total_cost:.4f} — limit is ${max_cost_usd:.2f}. Stopping.", RED)
                return {"exit": "cost_limit", "result": "Cost limit reached", "cost": total_cost, "blocker": None}

            if response.stop_reason == "end_turn":
                final = next((b.text for b in response.content if b.type == "text"), "")
                log(step, "AGENT FINISHED (no more tool calls)", final, AGENT)

                # ── Independent verification ─────────────────────────────────
                # Don't trust Claude's self-report. Run the check ourselves.
                if verify:
                    log(step, "VERIFYING INDEPENDENTLY", "", HARNESS)
                    passed = verify()
                    if passed:
                        log(step, "VERIFICATION PASSED", "Harness confirmed the outcome.", TOOL)
                    else:
                        log(step, "VERIFICATION FAILED",
                            "Claude said it was done but harness verification failed. Review needed.", RED)

                _print_summary(total_in, total_out, total_cost)
                return {"exit": "end_turn", "result": final, "cost": total_cost, "blocker": None}

            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                step += 1

                # ── report_status: agent's structured stop/continue decision ──
                if block.name == "report_status":
                    status = block.input
                    log(step, "AGENT STATUS REPORT",
                        f"tests_passed: {status['tests_passed']}  confidence: {status['confidence']}/5  "
                        f"action: {status['action']}\n"
                        f"blocker: {status.get('blocker') or 'none'}\n"
                        f"message: {status['message_to_user']}", AGENT)

                    rejection = enforce_status(status) if enforce_status else None

                    if rejection:
                        log(step, "HARNESS REJECTED AGENT DECISION", rejection, RED)
                        tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": rejection})
                    else:
                        if status["action"] == "stop":
                            log(step, "HARNESS APPROVED AGENT STOP", "", HARNESS)
                            if status.get("blocker"):
                                print(f"\n{RED}⚠ BLOCKER: {status['blocker']}{RESET}")

                            # ── Independent verification ─────────────────────
                            if verify:
                                log(step, "HARNESS VERIFYING INDEPENDENTLY", "", CYAN)
                                passed = verify()
                                if passed:
                                    log(step, "VERIFICATION PASSED", "", GREEN)
                                else:
                                    log(step, "VERIFICATION FAILED",
                                        "Claude reported done but verification failed — rejecting stop.", RED)
                                    tool_results.append({
                                        "type": "tool_result",
                                        "tool_use_id": block.id,
                                        "content": "REJECTED: harness ran independent verification and it failed. Keep working."
                                    })
                                    # skip the return below — fall through so normal flow sends tool_results
                                    continue

                            print(f"\n{GREEN}✓ {status['message_to_user']}{RESET}")
                            _print_summary(total_in, total_out, total_cost)
                            blocker = status.get("blocker") or None
                            return {
                                "exit":    "approved_stop",
                                "result":  status.get("message_to_user", "Done"),
                                "cost":    total_cost,
                                "blocker": blocker,
                            }
                        else:
                            tool_results.append({
                                "type": "tool_result", "tool_use_id": block.id,
                                "content": "Status noted. Continue."
                            })

                else:
                    # ── Human-in-the-loop ────────────────────────────────────
                    # Pause before irreversible tools. Agent sees the result either way.
                    if block.name in confirm_tools:
                        approved = _confirm(block.name, block.input)
                        if not approved:
                            log(step, f"HUMAN DENIED: {block.name}", "", RED)
                            tool_results.append({
                                "type": "tool_result", "tool_use_id": block.id,
                                "content": "Action denied by user. Try a different approach."
                            })
                            continue

                    # ── Tool retry ───────────────────────────────────────────
                    # Harness retries on ERROR before Claude even sees the failure.
                    log(step, f"RUNNING LOCALLY: {block.name}", str(block.input), GREEN)
                    result = _run_with_retry(handle_tool, block.name, block.input)

                    if block.name == "run_tests":
                        attempt += 1
                        passed = "passed" in result and "failed" not in result
                        log(step, f"TEST RESULT (attempt {attempt}/{max_attempts})",
                            result, GREEN if passed else RED)

                        # ── Attempt budget ───────────────────────────────────
                        if attempt >= max_attempts:
                            log(step, "BUDGET EXHAUSTED", f"Used all {max_attempts} attempts.", RED)
                            _print_summary(total_in, total_out, total_cost)
                            return {"exit": "budget_exhausted", "result": "Budget exhausted", "cost": total_cost, "blocker": None}
                    else:
                        log(step, "LOCAL RESULT", result, GREEN)

                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

            messages.append({"role": "user", "content": tool_results})
            step += 1
            log(step, "SENDING RESULTS BACK TO CLAUDE", f"{len(tool_results)} result(s)", WHITE)

    finally:
        _log_file.close()
        _log_file = None


def _print_summary(total_in, total_out, total_cost):
    print(f"\n{CYAN}=== TOTAL TOKENS === in: {total_in}  out: {total_out}  cost: ${total_cost:.4f}{RESET}")
