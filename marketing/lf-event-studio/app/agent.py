"""
Agentic loop using the OpenAI-compatible LiteLLM proxy.
Streams text in real time and handles tool_calls stop_reason.
"""

import json
import os
import queue
import threading
import uuid

from openai import OpenAI

from .tools import TOOL_DEFS_OPENAI, TOOL_HANDLERS

_jobs: dict[str, queue.Queue] = {}
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        base_url = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
        api_key  = os.environ.get("LITELLM_API_KEY", "")
        if not base_url or not api_key:
            raise RuntimeError("LITELLM_BASE_URL and LITELLM_API_KEY must be set in .env")
        _client = OpenAI(base_url=base_url, api_key=api_key)
    return _client


def _model() -> str:
    return os.environ.get("LITELLM_MODEL", "claude-sonnet-4-6")


# ── Public API ────────────────────────────────────────────────────────────────

def start_job(prompt: str) -> str:
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    threading.Thread(target=_run_agent, args=(prompt, q), daemon=True).start()
    return job_id


def get_queue(job_id: str) -> queue.Queue | None:
    return _jobs.get(job_id)


def remove_job(job_id: str) -> None:
    _jobs.pop(job_id, None)


# ── Agentic loop ──────────────────────────────────────────────────────────────

def _run_agent(prompt: str, q: queue.Queue) -> None:
    try:
        client = _get_client()
        messages = [{"role": "user", "content": prompt}]

        while True:
            collected_text   = ""
            pending_text     = ""           # buffer for line-by-line emission
            collected_calls  = {}           # index → partial tool_call dict
            finish_reason    = None

            stream = client.chat.completions.create(
                model=_model(),
                messages=messages,
                tools=TOOL_DEFS_OPENAI,
                tool_choice="auto",
                stream=True,
                max_tokens=32000,
            )

            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                finish_reason = choice.finish_reason or finish_reason
                delta = choice.delta

                # ── Stream text content ──────────────────────────────────────
                if delta.content:
                    collected_text += delta.content
                    pending_text   += delta.content
                    # Emit complete lines immediately so the UI updates in real time
                    while "\n" in pending_text:
                        line, pending_text = pending_text.split("\n", 1)
                        if line.strip():
                            q.put({"type": "output", "text": line})

                # ── Accumulate tool call chunks ──────────────────────────────
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in collected_calls:
                            collected_calls[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.id:
                            collected_calls[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                collected_calls[idx]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                collected_calls[idx]["function"]["arguments"] += tc.function.arguments

            # Flush any remaining buffered text
            if pending_text.strip():
                q.put({"type": "output", "text": pending_text})

            # ── Handle finish reason ──────────────────────────────────────────
            if finish_reason == "stop":
                q.put({"type": "done", "done": True, "success": True})
                break

            if finish_reason == "tool_calls":
                tool_call_list = [collected_calls[i] for i in sorted(collected_calls)]

                # Add assistant message (may have text + tool calls)
                messages.append({
                    "role": "assistant",
                    "content": collected_text or None,
                    "tool_calls": tool_call_list,
                })

                # Execute each tool and append result
                for tc in tool_call_list:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    q.put({"type": "output", "text": f"🔧 {name}({json.dumps(args)[:100]})"})

                    handler = TOOL_HANDLERS.get(name)
                    if handler:
                        try:
                            result = handler(args)
                        except Exception as exc:
                            result = {"error": str(exc)}
                    else:
                        result = {"error": f"Unknown tool: {name}"}

                    q.put({"type": "output", "text": f"   ↳ {json.dumps(result)[:200]}"})

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result),
                    })

            else:
                # length, content_filter, or unknown — treat as done
                q.put({"type": "done", "done": True, "success": True})
                break

    except Exception as exc:
        q.put({"type": "output", "text": f"❌ Agent error: {exc}"})
        q.put({"type": "done", "done": True, "success": False})
