"""
Claude subprocess runner and in-process job store.
"""

import queue
import subprocess
import threading
import uuid
from pathlib import Path

from .prompts import SEGMENT_PLANNER_PROMPT

# Path to the Claude Code binary (Windows)
CLAUDE_EXE = (
    Path.home()
    / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
)

# job_id -> Queue
_jobs: dict[str, queue.Queue] = {}


def start_job(url: str) -> str:
    """Kick off a Claude run for the given event URL. Returns a job_id."""
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q

    prompt = SEGMENT_PLANNER_PROMPT.format(url=url)
    thread = threading.Thread(
        target=_run_claude,
        args=(job_id, prompt, q),
        daemon=True,
    )
    thread.start()
    return job_id


def get_queue(job_id: str) -> queue.Queue | None:
    return _jobs.get(job_id)


def remove_job(job_id: str) -> None:
    _jobs.pop(job_id, None)


def _run_claude(job_id: str, prompt: str, q: queue.Queue) -> None:
    claude_cmd = str(CLAUDE_EXE) if CLAUDE_EXE.exists() else "claude"
    try:
        proc = subprocess.Popen(
            [claude_cmd, "-p", prompt, "--dangerously-skip-permissions"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,                          # line-buffered
            cwd=str(Path(__file__).parent.parent),
        )
        for line in proc.stdout:
            q.put({"type": "output", "text": line.rstrip()})
        proc.wait()
        q.put({"type": "done", "done": True, "success": proc.returncode == 0})
    except Exception as exc:
        q.put({"type": "output", "text": f"Error: {exc}"})
        q.put({"type": "done", "done": True, "success": False})
