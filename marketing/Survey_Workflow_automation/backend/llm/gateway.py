"""
Unified, deterministic LLM gateway (ported from emailcreationskill/backend/llm/gateway.py).

EVERY AI call in this service MUST go through this module. Do not call the Anthropic
SDK or the `claude` CLI directly anywhere else. This is the single place where the
backend is chosen and where determinism is enforced.

Backend priority (chosen once, in one place):
    Anthropic API  (ANTHROPIC_API_KEY)                   -> Anthropic SDK -> api.anthropic.com
    LiteLLM proxy  (LITELLM_BASE_URL + LITELLM_API_KEY)  -> Anthropic SDK -> LF cluster
    Claude Code    (neither key set)                     -> `claude` CLI subprocess

Determinism guarantees (applied identically on every path):
    - Same model id on ALL backends.
    - temperature = 0.0 on every SDK call (top_p intentionally omitted).
    - Fixed max_tokens per call (caller-supplied, never model-default).

This module only exposes `complete_text()` — a single-shot completion, which is all
this tool needs (no agentic tool-calling loop here).
"""
import logging
import os
import shutil
import subprocess
import sys
from typing import Callable, Optional

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, LITELLM_BASE_URL, LITELLM_API_KEY

log = logging.getLogger("survey-workflow.llm")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    log.addHandler(_h)
    log.propagate = False

TEMPERATURE: float = 0.0

_CLAUDE_CLI: Optional[str] = None


def _cli_path() -> str:
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


def backend_name() -> str:
    """Return the active backend: 'anthropic' | 'litellm' | 'cli'."""
    if ANTHROPIC_API_KEY:
        return "anthropic"
    if LITELLM_BASE_URL and LITELLM_API_KEY:
        return "litellm"
    return "cli"


def _has_sdk_key() -> bool:
    return backend_name() in ("litellm", "anthropic")


def resolve_model() -> str:
    return os.getenv("LITELLM_MODEL") or CLAUDE_MODEL


_cli_warned = False


def _warn_cli_once() -> None:
    global _cli_warned
    if not _cli_warned:
        _cli_warned = True
        log.warning(
            "[LLM] Using the Claude CLI backend (no API key set). This path CANNOT pin "
            "temperature, so its output may diverge from the LiteLLM/Anthropic SDK paths. "
            "Set LITELLM_API_KEY (or ANTHROPIC_API_KEY) for the deterministic SDK path."
        )


_sdk_client = None


def _make_sdk_client():
    global _sdk_client
    if _sdk_client is not None:
        return _sdk_client
    import anthropic
    if backend_name() == "litellm":
        _sdk_client = anthropic.Anthropic(api_key=LITELLM_API_KEY, base_url=LITELLM_BASE_URL)
    else:
        _sdk_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _sdk_client


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


def _cli_call(prompt: str, *, timeout: int) -> str:
    """Single blocking `claude --print` call via stdin. Returns stdout text.

    Always passes --strict-mcp-config (with no --mcp-config) so no MCP server startup
    can eat into the timeout — this path never uses real MCP tools.
    """
    _warn_cli_once()
    argv = [
        _cli_path(), "--print", "--model", resolve_model(),
        "--dangerously-skip-permissions", "--strict-mcp-config",
    ]
    proc = subprocess.Popen(
        argv,
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


def complete_text(prompt: str, *, system: Optional[str] = None,
                  max_tokens: int = 1024, timeout: int = 120) -> str:
    """Deterministic single-shot text completion. Same output on any backend."""
    if _has_sdk_key():
        client = _make_sdk_client()
        kwargs = dict(
            model=resolve_model(),
            max_tokens=max_tokens,
            temperature=TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        return "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

    full = f"<system>\n{system}\n</system>\n\n{prompt}" if system else prompt
    return _cli_call(full, timeout=timeout)


_b = backend_name()
if _b in ("litellm", "anthropic"):
    log.info(f"[LLM] backend={_b} (deterministic SDK path) model={resolve_model()!r} temperature=0")
else:
    log.warning(
        f"[LLM] backend=cli (fallback) model={resolve_model()!r} — no LITELLM_API_KEY/"
        "ANTHROPIC_API_KEY set. Output may diverge from the SDK paths; set a key for determinism."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Agentic tool loop (ported from emailcreationskill/backend/llm/gateway.py for
# the Audience Builder discovery agent — see audience_builder/discovery_agent.py).
#
# `tools`        — canonical Anthropic format: [{"name","description","input_schema"}]
# `execute_tool` — callable(name: str, tool_input: dict) -> str (JSON-encoded result)
# `on_event`     — optional callable(dict) for streaming, e.g. {"type":"output","text":...}
#                  {"type":"tool","name":..,"input":..} / {"type":"tool_result","text":..}
# Returns (final_text, updated_messages).
#
# Unlike the source project, this gateway's CLI backend has no agentic tool-use
# protocol ported over (the source's TOOL_CALL text-protocol emulation for the
# `claude` CLI, `_agent_cli`/`_cli_call_streaming`/`_extract_tool_call`, is
# intentionally NOT ported here — this project's CLI fallback path only ever
# needed single-shot `complete_text`). run_agent therefore requires an SDK
# backend (ANTHROPIC_API_KEY or LITELLM_BASE_URL+LITELLM_API_KEY) and raises a
# clear RuntimeError otherwise, matching this project's existing
# "no HUBSPOT_ACCESS_TOKEN configured" error-surfacing style rather than
# silently degrading.

def _emit(on_event: Optional[Callable], event: dict) -> None:
    if on_event:
        try:
            on_event(event)
        except Exception:
            pass


def _serialize_content_block(block) -> dict:
    """Serialize one response content block back into valid message-INPUT shape.
    `block.model_dump()` round-trips whatever the response happened to carry —
    some LiteLLM-routed model groups attach extra output-only fields that the
    API's stricter input schema then rejects on the next turn — so only the
    fields each block type actually needs as input are kept."""
    btype = getattr(block, "type", None)
    if btype == "text":
        return {"type": "text", "text": block.text}
    if btype == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input)}
    if btype == "thinking":
        d = {"type": "thinking", "thinking": block.thinking}
        if getattr(block, "signature", None):
            d["signature"] = block.signature
        return d
    if btype == "redacted_thinking":
        return {"type": "redacted_thinking", "data": block.data}
    return block.model_dump() if hasattr(block, "model_dump") else block


def run_agent(messages: list, *, system: str, tools: list,
              execute_tool: Callable[[str, dict], str],
              max_tokens: int = 4096, max_steps: int = 8,
              on_event: Optional[Callable] = None) -> tuple[str, list]:
    """Deterministic agentic loop, SDK backend only (see module note above).
    Raises RuntimeError immediately if no SDK key is configured — never falls
    back to a non-deterministic/no-op CLI emulation."""
    if not _has_sdk_key():
        raise RuntimeError(
            "run_agent requires an SDK backend (set ANTHROPIC_API_KEY or "
            "LITELLM_BASE_URL + LITELLM_API_KEY in .env) — the Claude CLI "
            "fallback does not support the agentic tool-calling loop in this project."
        )
    return _agent_sdk(messages, system=system, tools=tools, execute_tool=execute_tool,
                      max_tokens=max_tokens, max_steps=max_steps, on_event=on_event)


def _agent_sdk(messages, *, system, tools, execute_tool, max_tokens, max_steps, on_event) -> tuple[str, list]:
    client = _make_sdk_client()
    model = resolve_model()
    msgs = list(messages)
    best_plan = ""   # richest plan-like text seen (in case the final turn is thin)

    def _looks_like_plan(t: str) -> bool:
        return "##" in t or "|---|" in t or "| **" in t or len(t) > 400

    for _ in range(max_steps):
        # Stream (not .create()) so narration text reaches on_event as the model
        # generates it — a single non-streaming turn can take tens of seconds with
        # no callback in between, which would look like a hang to SSE consumers.
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=TEMPERATURE,
            system=system,
            tools=tools,
            messages=msgs,
        ) as stream:
            for event in stream:
                if event.type == "content_block_start" and getattr(event.content_block, "type", None) == "thinking":
                    _emit(on_event, {"type": "output", "text": "thinking..."})
                elif event.type == "content_block_delta" and getattr(event.delta, "type", None) == "text_delta":
                    _emit(on_event, {"type": "output_delta", "text": event.delta.text})
            resp = stream.get_final_message()
        turn_text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        if _looks_like_plan(turn_text) and len(turn_text) > len(best_plan):
            best_plan = turn_text

        serialized = [_serialize_content_block(b) for b in resp.content]
        msgs = msgs + [{"role": "assistant", "content": serialized}]

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
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

    return best_plan, msgs   # ran out of steps without a clean final turn


def openai_tools_to_anthropic(openai_tools: list) -> list:
    """Convert OpenAI function-tool defs (as used by audience_builder/tools.py's
    TOOL_DEFS_OPENAI) to the canonical Anthropic tool format required by run_agent."""
    out = []
    for t in openai_tools:
        fn = t.get("function", t)
        out.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return out
