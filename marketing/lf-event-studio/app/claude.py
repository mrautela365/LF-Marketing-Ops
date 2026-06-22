"""
Claude subprocess runner and in-process job store.
"""

import queue
import subprocess
import threading
import uuid
from pathlib import Path

CLAUDE_EXE = (
    Path.home()
    / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
)

_jobs: dict[str, queue.Queue] = {}


def start_job(prompt: str, cwd: str | None = None) -> str:
    """Start a Claude subprocess with the given prompt. Returns job_id."""
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    threading.Thread(target=_run_claude, args=(prompt, q, cwd), daemon=True).start()
    return job_id


def get_queue(job_id: str) -> queue.Queue | None:
    return _jobs.get(job_id)


def remove_job(job_id: str) -> None:
    _jobs.pop(job_id, None)


def _run_claude(prompt: str, q: queue.Queue, cwd: str | None = None) -> None:
    claude_cmd = str(CLAUDE_EXE) if CLAUDE_EXE.exists() else "claude"
    run_cwd = cwd or str(Path(__file__).parent.parent)
    try:
        proc = subprocess.Popen(
            [claude_cmd, "-p", prompt, "--dangerously-skip-permissions"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=run_cwd,
        )
        for line in proc.stdout:
            q.put({"type": "output", "text": line.rstrip()})
        proc.wait()
        q.put({"type": "done", "done": True, "success": proc.returncode == 0})
    except Exception as exc:
        q.put({"type": "output", "text": f"Error: {exc}"})
        q.put({"type": "done", "done": True, "success": False})
