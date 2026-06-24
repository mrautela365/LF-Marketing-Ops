"""
Anthropic SDK agentic loop with streaming.
Replaces the claude.exe subprocess runner.
"""

import json
import os
import queue
import threading
import uuid

import anthropic

from .tools import TOOL_DEFS, TOOL_HANDLERS

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 16000

_jobs: dict[str, queue.Queue] = {}
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in environment / .env")
        _client = anthropic.Anthropic(api_key=key)
    return _client


# ── Public API ────────────────────────────────────────────────────────────────

def start_job(prompt: str) -> str:
    """Start an agentic Claude run. Returns job_id."""
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
            # Stream text chunks, collect full message for tool-use handling
            pending_text = ""
            content_blocks = []

            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                tools=TOOL_DEFS,
                messages=messages,
            ) as stream:
                for event in stream:
                    # Stream text deltas line by line so the UI sees output immediately
                    if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                        pending_text += event.delta.text
                        # Emit complete lines as they form
                        while "\n" in pending_text:
                            line, pending_text = pending_text.split("\n", 1)
                            if line.strip():
                                q.put({"type": "output", "text": line})

                final_msg = stream.get_final_message()

            # Flush any remaining text (no trailing newline)
            if pending_text.strip():
                q.put({"type": "output", "text": pending_text})

            stop_reason = final_msg.stop_reason

            if stop_reason == "end_turn":
                q.put({"type": "done", "done": True, "success": True})
                break

            if stop_reason == "tool_use":
                tool_results = []
                for block in final_msg.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input
                        # Show tool call in the stream
                        input_preview = json.dumps(tool_input)[:120]
                        q.put({"type": "output", "text": f"🔧 {tool_name}({input_preview})"})

                        handler = TOOL_HANDLERS.get(tool_name)
                        if handler:
                            try:
                                result = handler(tool_input)
                            except Exception as exc:
                                result = {"error": str(exc)}
                        else:
                            result = {"error": f"Unknown tool: {tool_name}"}

                        # Show result preview
                        result_preview = json.dumps(result)[:200]
                        q.put({"type": "output", "text": f"   ↳ {result_preview}"})

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })

                messages.append({"role": "assistant", "content": final_msg.content})
                messages.append({"role": "user", "content": tool_results})

            else:
                # Unexpected stop reason — treat as done
                q.put({"type": "done", "done": True, "success": True})
                break

    except Exception as exc:
        q.put({"type": "output", "text": f"❌ Agent error: {exc}"})
        q.put({"type": "done", "done": True, "success": False})
