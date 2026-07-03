"""
Unified, deterministic LLM gateway.

════════════════════════════════════════════════════════════════════════════════
EVERY AI call in this service MUST go through this module. Do not call the Anthropic
SDK, the OpenAI SDK, or the `claude` CLI directly anywhere else. This is the single
place where the backend is chosen and where determinism is enforced, so that a call
made through the Claude CLI, the Anthropic API key, or the LiteLLM API key produces
the same result in the same output format.

Backend priority (chosen once, in one place):
    LiteLLM proxy  (LITELLM_BASE_URL + LITELLM_API_KEY)  → Anthropic SDK → LF cluster
    Anthropic API  (ANTHROPIC_API_KEY)                   → Anthropic SDK → api.anthropic.com
    Claude Code    (neither key set)                     → `claude` CLI subprocess

Determinism guarantees (applied identically on every path):
    • Same model id on ALL backends — CLAUDE_MODEL for the SDK paths, and passed to
      the CLI via `--model` so the CLI cannot silently use a different session model.
    • temperature = 0.0 and top_p = 1.0 on every SDK call.
    • Fixed max_tokens per call (caller-supplied, never model-default).
    • One canonical tool format (Anthropic `input_schema`) and one output shape.

Honest caveat: bit-identical output across three different backends cannot be
guaranteed by any provider even at temperature=0 (the CLI may run a different model
build; providers don't promise identical sampling). This module makes the model,
parameters, tool format, and output format identical — which is as deterministic as
the platforms allow. Nothing downstream should assume more than that.

Public API:
    backend_name()   -> "litellm" | "anthropic" | "cli"
    resolve_model()  -> str
    complete_text(prompt, *, system=None, max_tokens=1024, timeout=120) -> str
    run_agent(messages, *, system, tools, execute_tool,
              max_tokens=4096, max_steps=8, on_event=None) -> (text, messages)
    run_cli_skill(prompt, *, cwd=None, timeout=900, on_event=None) -> (text, success)
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from typing import Callable, Optional

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, LITELLM_BASE_URL, LITELLM_API_KEY

log = logging.getLogger("email-staging.llm")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    log.addHandler(_h)
    log.propagate = False

# ── Deterministic sampling constants (single source of truth) ─────────────────
TEMPERATURE: float = 0.0
TOP_P: float = 1.0

# ── CLI discovery (lazy — never fails at import; only needed for the CLI backend) ──
_CLAUDE_CLI: Optional[str] = None


def _cli_path() -> str:
    """Resolve the `claude` CLI path on first use. Raises only if a CLI call is made
    without the CLI installed — SDK-only deployments never trigger this."""
    global _CLAUDE_CLI
    if _CLAUDE_CLI:
        return _CLAUDE_CLI
    env = os.getenv("CLAUDE_CLI_PATH")
    if env:
        _CLAUDE_CLI = env
        return env
    if found := shutil.which("claude"):
        _CLAUDE_CLI = found
        return found
    fallback = r"C:\Users\VinayU\AppData\Roaming\npm\claude.cmd"
    if os.path.exists(fallback):
        _CLAUDE_CLI = fallback
        return fallback
    raise RuntimeError("claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code")


# ── Backend selection (chosen once) ───────────────────────────────────────────
def backend_name() -> str:
    """Return the active backend: 'litellm' | 'anthropic' | 'cli'."""
    if LITELLM_BASE_URL and LITELLM_API_KEY:
        return "litellm"
    if ANTHROPIC_API_KEY:
        return "anthropic"
    return "cli"


def _has_sdk_key() -> bool:
    return backend_name() in ("litellm", "anthropic")


def resolve_model() -> str:
    """The one model id used on EVERY backend (SDK model + CLI --model)."""
    # LITELLM_MODEL may override for the proxy, but defaults to CLAUDE_MODEL so all
    # three backends request the same model unless explicitly diverged in .env.
    return os.getenv("LITELLM_MODEL", CLAUDE_MODEL)


# One-time loud warning the first time the CLI (least-deterministic) path is used.
_cli_warned = False


def _warn_cli_once() -> None:
    global _cli_warned
    if not _cli_warned:
        _cli_warned = True
        log.warning(
            "[LLM] Using the Claude CLI backend (no API key set). This path CANNOT pin "
            "temperature and emulates tool-calls via a text protocol, so its output may "
            "diverge from the LiteLLM/Anthropic SDK paths. Set LITELLM_API_KEY (or "
            "ANTHROPIC_API_KEY) for the deterministic SDK path."
        )


_sdk_client = None


def _make_sdk_client():
    """Anthropic SDK client pointed at the active endpoint (cached)."""
    global _sdk_client
    if _sdk_client is not None:
        return _sdk_client
    import anthropic
    if backend_name() == "litellm":
        _sdk_client = anthropic.Anthropic(api_key=LITELLM_API_KEY, base_url=LITELLM_BASE_URL)
    else:
        _sdk_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _sdk_client


# ── CLI subprocess helper (shared) ────────────────────────────────────────────
def _cli_argv(extra: Optional[list] = None) -> list:
    """Base argv for a deterministic `claude --print` call — always pins --model."""
    argv = [_cli_path(), "--print", "--model", resolve_model(), "--dangerously-skip-permissions"]
    if extra:
        argv.extend(extra)
    return argv


def _popen_kwargs() -> dict:
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return kw


def _kill(proc: "subprocess.Popen") -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()
    try:
        proc.communicate(timeout=5)
    except Exception:
        pass


def _cli_call(prompt: str, *, timeout: int, extra_args: Optional[list] = None) -> str:
    """Single blocking `claude --print` call via stdin. Returns stdout text."""
    _warn_cli_once()
    proc = subprocess.Popen(
        _cli_argv(extra_args),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        **_popen_kwargs(),
    )
    try:
        stdout_b, stderr_b = proc.communicate(
            input=prompt.encode("utf-8", errors="replace"), timeout=timeout
        )
    except subprocess.TimeoutExpired:
        _kill(proc)
        raise RuntimeError(f"Claude CLI timed out after {timeout}s")
    if proc.returncode != 0:
        stderr_text = stderr_b.decode("utf-8", errors="replace").strip()
        stdout_text = stdout_b.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Claude CLI error: {stderr_text or stdout_text or proc.returncode}")
    return stdout_b.decode("utf-8", errors="replace").strip()


# ══════════════════════════════════════════════════════════════════════════════
# 1) Single-shot text completion (no tools)
# ══════════════════════════════════════════════════════════════════════════════
def complete_text(prompt: str, *, system: Optional[str] = None,
                  max_tokens: int = 1024, timeout: int = 120) -> str:
    """Deterministic single-shot text completion. Same output on any backend."""
    if _has_sdk_key():
        client = _make_sdk_client()
        kwargs = dict(
            model=resolve_model(),
            max_tokens=max_tokens,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        return "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

    # CLI backend — embed system in stdin (no --system-prompt arg escaping issues)
    full = f"<system>\n{system}\n</system>\n\n{prompt}" if system else prompt
    return _cli_call(full, timeout=timeout)


# ══════════════════════════════════════════════════════════════════════════════
# 2) Agentic tool loop
# ══════════════════════════════════════════════════════════════════════════════
# `tools`        — canonical Anthropic format: [{"name","description","input_schema"}]
# `execute_tool` — callable(name: str, tool_input: dict) -> str (JSON-encoded result)
# `on_event`     — optional callable(dict) for streaming, e.g. {"type":"output","text":...}
#                  {"type":"tool","name":..,"input":..} / {"type":"tool_result","text":..}
# Returns (final_text, updated_messages).

def _emit(on_event: Optional[Callable], event: dict) -> None:
    if on_event:
        try:
            on_event(event)
        except Exception:
            pass


def _tools_to_cli_instructions(tools: list) -> str:
    """Render a tool listing for the CLI text-protocol path from Anthropic tool defs."""
    lines = []
    for t in tools:
        props = (t.get("input_schema") or {}).get("properties", {}) or {}
        req = set((t.get("input_schema") or {}).get("required", []) or [])
        params = ", ".join(p + ("" if p in req else "?") for p in props)
        lines.append(f"  {t['name']}({params}) — {t.get('description','').strip()[:120]}")
    return "\n".join(lines)


def run_agent(messages: list, *, system: str, tools: list,
              execute_tool: Callable[[str, dict], str],
              max_tokens: int = 4096, max_steps: int = 8,
              on_event: Optional[Callable] = None) -> tuple[str, list]:
    """Deterministic agentic loop. SDK backends use native tool-use; CLI uses the
    TOOL_CALL text protocol. Same tool contract and return shape on every backend."""
    if _has_sdk_key():
        return _agent_sdk(messages, system=system, tools=tools, execute_tool=execute_tool,
                          max_tokens=max_tokens, on_event=on_event)
    return _agent_cli(messages, system=system, tools=tools, execute_tool=execute_tool,
                      max_tokens=max_tokens, max_steps=max_steps, on_event=on_event)


def _agent_sdk(messages, *, system, tools, execute_tool, max_tokens, on_event) -> tuple[str, list]:
    client = _make_sdk_client()
    model = resolve_model()
    msgs = list(messages)
    best_plan = ""   # richest plan-like text seen (in case the final turn is thin)

    def _looks_like_plan(t: str) -> bool:
        return "##" in t or "|---|" in t or "| **" in t or len(t) > 400

    while True:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            system=system,
            tools=tools,
            messages=msgs,
        )
        turn_text = ""
        for b in resp.content:
            if hasattr(b, "text") and b.text:
                turn_text += b.text
                _emit(on_event, {"type": "output", "text": b.text})
        if _looks_like_plan(turn_text) and len(turn_text) > len(best_plan):
            best_plan = turn_text

        serialized = [b.model_dump() if hasattr(b, "model_dump") else b for b in resp.content]
        msgs = msgs + [{"role": "assistant", "content": serialized}]

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            # If the final turn is thin ("plan is above"), fall back to the richest
            # plan text produced earlier in the loop.
            if not _looks_like_plan(text) and best_plan:
                text = best_plan
            return text, msgs

        tool_results = []
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                _emit(on_event, {"type": "tool", "name": block.name, "input": dict(block.input)})
                result = execute_tool(block.name, dict(block.input))
                _emit(on_event, {"type": "tool_result", "text": str(result)[:200]})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
        msgs = msgs + [{"role": "user", "content": tool_results}]


_CLI_AGENT_RULES = """
IMPORTANT: You are operating in EXECUTION MODE. Do NOT enter plan mode. Do NOT ask for approval.
Execute tool calls immediately and directly.

To call a tool output EXACTLY this on its own line (nothing else on that line):
  TOOL_CALL: {"name": "<tool>", "input": {<params>}}

Available tools:
{tool_list}

Tool results are returned as:
  TOOL_RESULT: {<json>}

Rules:
- Call tools immediately without asking for confirmation
- Do NOT say "I'll now...", "Let me...", or "I plan to..." — just output the TOOL_CALL line
- When all tools are done, write your final response to the user
"""


def _agent_cli(messages, *, system, tools, execute_tool, max_tokens, max_steps, on_event) -> tuple[str, list]:
    # Build conversation history (last 6 visible messages)
    history = ""
    visible = [m for m in messages if m.get("role") not in ("__tool_log__",)]
    for msg in visible[-6:]:
        role = "User" if msg.get("role") == "user" else "Assistant"
        content = msg.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content)[:400]
        history += f"{role}: {content}\n\n"

    # The final user_message is the last user entry; keep original messages intact.
    user_message = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content", "")
            user_message = c if isinstance(c, str) else json.dumps(c)
            break

    # Use replace (not .format) — the rules text contains literal JSON braces.
    rules = _CLI_AGENT_RULES.replace("{tool_list}", _tools_to_cli_instructions(tools))
    prompt = (
        f"<system>\n{system}\n</system>\n\n{rules}\n\n"
        f"Conversation history:\n{history}"
    )

    def _strip_protocol(text: str) -> str:
        """Drop TOOL_CALL/TOOL_RESULT protocol lines — they are not user-facing."""
        return "\n".join(
            l for l in text.splitlines()
            if not l.strip().startswith("TOOL_CALL:") and not l.strip().startswith("TOOL_RESULT:")
        ).strip()

    def _looks_like_plan(text: str) -> bool:
        return "##" in text or "|---|" in text or "| **" in text or len(text) > 400

    # Claude sometimes writes the full plan/table in an INTERMEDIATE turn (alongside a
    # tool call) and then ends with a thin "the plan is above". Track the richest
    # plan-like content across all turns and fall back to it when the final turn is thin.
    best_plan   = ""
    final_text  = ""
    for _ in range(max_steps):
        response = _cli_call(prompt, timeout=90)
        _emit(on_event, {"type": "output", "text": response})

        non_tool = _strip_protocol(response)
        if _looks_like_plan(non_tool) and len(non_tool) > len(best_plan):
            best_plan = non_tool

        tool_line = next(
            (line.strip()[len("TOOL_CALL:"):].strip()
             for line in response.splitlines()
             if line.strip().startswith("TOOL_CALL:")),
            None,
        )
        if tool_line:
            try:
                call = json.loads(tool_line)
                _emit(on_event, {"type": "tool", "name": call.get("name"), "input": call.get("input", {})})
                result = execute_tool(call["name"], call.get("input", {}))
                _emit(on_event, {"type": "tool_result", "text": str(result)[:200]})
            except Exception as e:
                result = json.dumps({"error": str(e)})
            prompt += f"\n{response}\nTOOL_RESULT: {result}\n"
            continue

        # No tool call → final answer. Use it if it carries the plan; otherwise fall
        # back to the richest intermediate plan (avoids the "presented above" problem).
        final_text = non_tool if _looks_like_plan(non_tool) else (best_plan or non_tool)
        break
    else:
        final_text = best_plan   # ran out of steps without a clean final turn

    updated = list(messages) + [{"role": "assistant", "content": final_text}]
    return final_text, updated


# ══════════════════════════════════════════════════════════════════════════════
# 3) CLI skill / MCP runs (inherently CLI-only — real MCP connectors + SKILL.md)
# ══════════════════════════════════════════════════════════════════════════════
# Used where the work depends on the CLI's own MCP tools (e.g. Asana MCP) or a skill
# directory, which the SDK backends cannot provide. Streams via on_event when given.
# Still pins --model for determinism; temperature is not CLI-controllable.

def run_cli_skill(prompt: str, *, cwd: Optional[str] = None, timeout: int = 900,
                  on_event: Optional[Callable] = None,
                  stream_json: bool = False) -> tuple[str, bool]:
    """Run a `claude --print` subprocess that uses its own MCP tools / a skill dir.
    Returns (accumulated_text, success). Streams lines via on_event if provided."""
    extra = ["--output-format", "stream-json", "--verbose"] if stream_json else []
    proc = subprocess.Popen(
        _cli_argv(extra),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        cwd=cwd, **_popen_kwargs(),
    )
    proc.stdin.write(prompt)
    proc.stdin.close()

    collected: list = []

    def _reader():
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            if stream_json:
                try:
                    event = json.loads(line)
                    etype = event.get("type", "")
                    if etype == "assistant":
                        for block in event.get("message", {}).get("content", []):
                            if block.get("type") == "text":
                                collected.append(block["text"])
                                _emit(on_event, {"type": "output", "text": block["text"]})
                    elif etype == "result":
                        txt = event.get("result", "")
                        if txt:
                            collected.append(txt)
                            _emit(on_event, {"type": "output", "text": txt})
                    continue
                except json.JSONDecodeError:
                    pass
            collected.append(line)
            _emit(on_event, {"type": "output", "text": line})

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
        reader.join(timeout=10)
        success = proc.returncode == 0
    except subprocess.TimeoutExpired:
        _kill(proc)
        reader.join(timeout=5)
        _emit(on_event, {"type": "output", "text": f"\n⚠ Timed out after {timeout // 60} min — process killed."})
        success = False

    return "\n".join(collected), success


# ── OpenAI→Anthropic tool-def converter (for migrating audience_tools) ─────────
def openai_tools_to_anthropic(openai_tools: list) -> list:
    """Convert OpenAI function-tool defs to the canonical Anthropic tool format."""
    out = []
    for t in openai_tools:
        fn = t.get("function", t)
        out.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return out


# ── Startup diagnostic (one clear line so the active backend is never a mystery) ──
_b = backend_name()
if _b in ("litellm", "anthropic"):
    log.info(f"[LLM] backend={_b} (deterministic SDK path) model={resolve_model()!r} temperature=0")
else:
    log.warning(
        f"[LLM] backend=cli (fallback) model={resolve_model()!r} — no LITELLM_API_KEY/"
        "ANTHROPIC_API_KEY set. Output may diverge from the SDK paths; set a key for determinism."
    )
