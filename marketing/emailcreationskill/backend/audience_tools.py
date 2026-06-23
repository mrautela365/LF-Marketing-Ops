"""
Audience list builder — wraps the hubspot-event-list-builder Claude skill.

Runs Claude as a subprocess (line-by-line streaming) with cwd set to the
skill directory so Claude can read SKILL.md and references/brand-master-lists.md.
Follows the same subprocess pattern used throughout agent.py.
"""
import os
import sys
import queue
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

# ── Skill directory ────────────────────────────────────────────────────────────
# backend/ → email_service/ → MCP/ → LF-Marketing-Ops/marketing/hubspot-event-list-builder
_BACKEND   = Path(__file__).parent
SKILL_DIR  = str(
    _BACKEND.parent.parent
    / "LF-Marketing-Ops" / "marketing" / "hubspot-event-list-builder"
)

# ── Claude CLI ─────────────────────────────────────────────────────────────────
_CLAUDE_CLI: str | None = None

def _get_claude_cli() -> str:
    global _CLAUDE_CLI
    if _CLAUDE_CLI:
        return _CLAUDE_CLI
    found = shutil.which("claude")
    if found:
        _CLAUDE_CLI = found
        return found
    fallback = r"C:\Users\VinayU\AppData\Roaming\npm\claude.cmd"
    if os.path.exists(fallback):
        _CLAUDE_CLI = fallback
        return fallback
    raise RuntimeError(
        "claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
    )

# ── In-memory job store ────────────────────────────────────────────────────────
_jobs: dict[str, queue.Queue] = {}

# ── Prompt ────────────────────────────────────────────────────────────────────
_BUILD_PROMPT = """\
Build the HubSpot event audience lists for this Linux Foundation event:

{url}

Follow the hubspot-event-list-builder skill instructions in SKILL.md exactly, \
working through all 6 steps:
1. Scrape the event page to extract name, edition, brand key, and Snowflake search terms
2. Query Snowflake for all past editions (excluding the current year)
3. Look up the brand master list ID from references/brand-master-lists.md
4. Clone the reference list and build List 1 — All Past Registrants
5. Build List 2 — Registrants + Web Visitors
6. Confirm and report both list IDs, names, and filter counts

After all individual lists are created, build one final Master Audience list:
- Name: "[Event Name] [Year] — Master Audience"
- Combines ALL lists using OR logic
- Never references any communitySeg list as a source

Narrate what you are doing at every sub-step.

IMPORTANT: At the very end, after all lists are built, output exactly this line \
(substitute the real numeric ID):
MASTER_LIST_ID: <numeric_hubspot_list_id>
"""


# ── Public API ─────────────────────────────────────────────────────────────────

def start_build_job(event_url: str) -> str:
    """Start an audience build job. Returns job_id for SSE polling."""
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    prompt = _BUILD_PROMPT.format(url=event_url)
    threading.Thread(target=_run_claude, args=(prompt, q), daemon=True).start()
    return job_id


def get_job_queue(job_id: str) -> queue.Queue | None:
    return _jobs.get(job_id)


def remove_job(job_id: str) -> None:
    _jobs.pop(job_id, None)


def extract_master_list_id(text: str) -> str:
    """Parse the master list ID from accumulated Claude output."""
    # Primary: explicit marker we asked Claude to print
    m = re.search(r"MASTER_LIST_ID:\s*(\d+)", text)
    if m:
        return m.group(1)
    # HubSpot URL patterns near "master" keyword
    for pat in [
        r"(?i)master[^\n]{0,300}objectLists/(\d+)",
        r"(?i)objectLists/(\d+)[^\n]{0,300}master",
        r"[Mm]aster [Aa]udience[^\n]*?[Ii][Dd][:\s]+(\d{4,7})",
        r"[Mm]aster[^\n]*?[Ll]ist[^\n]*?[Ii][Dd][:\s]+(\d{4,7})",
        r"(?:master audience|Master Audience)[^\n]{0,80}\b(\d{5,7})\b",
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    # Last resort: master list is always the LAST list Claude creates —
    # take the final objectLists/ID in the entire output
    all_ids = re.findall(r"objectLists/(\d+)", text)
    if all_ids:
        return all_ids[-1]
    return ""


# ── Private: subprocess runner ─────────────────────────────────────────────────

def _run_claude(prompt: str, q: queue.Queue) -> None:
    """Run Claude subprocess and push each output line into the queue."""
    try:
        claude_cmd = _get_claude_cli()
    except RuntimeError as exc:
        q.put({"type": "output", "text": f"Error: {exc}"})
        q.put({"type": "done", "done": True, "success": False})
        return

    skill_dir = SKILL_DIR if os.path.isdir(SKILL_DIR) else None
    if not skill_dir:
        q.put({"type": "output",
               "text": f"⚠ Skill directory not found: {SKILL_DIR} — running without SKILL.md"})

    popen_kw: dict = {}
    if sys.platform == "win32":
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        proc = subprocess.Popen(
            [claude_cmd, "--print", "--dangerously-skip-permissions"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=skill_dir,
            **popen_kw,
        )
        # Write prompt then close stdin so Claude starts processing
        proc.stdin.write(prompt)
        proc.stdin.close()

        for line in proc.stdout:
            q.put({"type": "output", "text": line.rstrip()})

        proc.wait()
        q.put({"type": "done", "done": True, "success": proc.returncode == 0})

    except Exception as exc:
        q.put({"type": "output", "text": f"Error: {exc}"})
        q.put({"type": "done", "done": True, "success": False})
