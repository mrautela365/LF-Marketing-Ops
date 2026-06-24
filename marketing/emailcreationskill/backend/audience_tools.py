"""
Audience list builder — same 3-mode pattern as agent.py:

  Mode 1  LiteLLM proxy    LITELLM_BASE_URL + LITELLM_API_KEY   Anthropic SDK → LF cluster
  Mode 2  Direct Anthropic  ANTHROPIC_API_KEY                    Anthropic SDK → api.anthropic.com
  Mode 3  Claude Code CLI   neither key set                      claude -p subprocess

Priority: LiteLLM → Anthropic → CLI
"""
import json
import os
import queue
import re
import requests
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    LITELLM_BASE_URL, LITELLM_API_KEY,
    HUBSPOT_ACCESS_TOKEN, HUBSPOT_PORTAL_ID,
)

# ── Skill directory (used for CLI mode cwd + brand-master-lists.md in SDK mode) ──
_BACKEND  = Path(__file__).parent
SKILL_DIR = _BACKEND.parent.parent / "LF-Marketing-Ops" / "marketing" / "hubspot-event-list-builder"

# ── In-memory job store ────────────────────────────────────────────────────────
_jobs: dict[str, queue.Queue] = {}

# ── CLI timeout ────────────────────────────────────────────────────────────────
_CLI_TIMEOUT = 900  # 15 min


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def start_build_job(event_url: str) -> str:
    """Start an audience build job. Returns job_id for SSE polling."""
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    threading.Thread(target=_run, args=(event_url, q), daemon=True).start()
    return job_id


def get_job_queue(job_id: str) -> queue.Queue | None:
    return _jobs.get(job_id)


def remove_job(job_id: str) -> None:
    _jobs.pop(job_id, None)


def extract_master_list_id(text: str) -> str:
    """Parse the master list ID from accumulated output."""
    m = re.search(r"MASTER_LIST_ID:\s*(\d+)", text)
    if m:
        return m.group(1)
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
    # Last resort: master is built last — take the final objectLists/ID
    ids = re.findall(r"objectLists/(\d+)", text)
    return ids[-1] if ids else ""


# ══════════════════════════════════════════════════════════════════════════════
# Mode dispatcher
# ══════════════════════════════════════════════════════════════════════════════

def _has_sdk_key() -> bool:
    return bool(LITELLM_API_KEY or ANTHROPIC_API_KEY)


def _make_client():
    import anthropic
    if LITELLM_BASE_URL and LITELLM_API_KEY:
        return anthropic.Anthropic(api_key=LITELLM_API_KEY, base_url=LITELLM_BASE_URL)
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _run(event_url: str, q: queue.Queue) -> None:
    if _has_sdk_key():
        _sdk_run(event_url, q)
    else:
        _cli_run(event_url, q)


# ══════════════════════════════════════════════════════════════════════════════
# Mode 1 & 2 — Anthropic SDK agentic loop
# ══════════════════════════════════════════════════════════════════════════════

_AUDIENCE_SYSTEM = """\
You are a HubSpot audience list builder for Linux Foundation marketing events.
When given an event URL, you will build three HubSpot contact lists:
  1. [Brand] - [Event Name] - All Past Registrants
  2. [Brand] - [Event Name] - Registrants + Web Visitors
  3. [Event Name] [Year] — Master Audience  (OR of lists 1 and 2)

Use the tools available. Narrate each step briefly.
At the very end output exactly:
MASTER_LIST_ID: <numeric_id>
"""

_AUDIENCE_TOOLS = [
    {
        "name": "fetch_url",
        "description": "HTTP GET a URL and return readable text. Use to scrape the event page.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to fetch"}},
            "required": ["url"],
        },
    },
    {
        "name": "read_brand_master_lists",
        "description": "Return the full content of brand-master-lists.md to look up the HubSpot master list ID for a brand.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_hubspot_lists",
        "description": "Search HubSpot contact lists by name fragment.",
        "input_schema": {
            "type": "object",
            "properties": {"search_term": {"type": "string"}},
            "required": ["search_term"],
        },
    },
    {
        "name": "get_hubspot_list",
        "description": "Get details and filter definition of a HubSpot list by its numeric ID.",
        "input_schema": {
            "type": "object",
            "properties": {"list_id": {"type": "string"}},
            "required": ["list_id"],
        },
    },
    {
        "name": "create_hubspot_list",
        "description": (
            "Create a new HubSpot SNAPSHOT contact list. "
            "filter_branch must follow the HubSpot v3 filterBranch schema: "
            "{filterBranchType, filterBranches[], filters[]}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "filter_branch": {
                    "type": "object",
                    "description": "HubSpot v3 filterBranch object",
                },
            },
            "required": ["name", "filter_branch"],
        },
    },
    {
        "name": "clone_hubspot_list",
        "description": "Copy an existing HubSpot list's filters into a new list with a new name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_list_id": {"type": "string"},
                "new_name": {"type": "string"},
            },
            "required": ["source_list_id", "new_name"],
        },
    },
]


def _hs_headers() -> dict:
    return {"Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}", "Content-Type": "application/json"}


def _execute_tool(name: str, inputs: dict) -> str:
    try:
        if name == "fetch_url":
            resp = requests.get(
                inputs["url"], timeout=20,
                headers={"User-Agent": "Mozilla/5.0 (compatible; LF-email-bot/1.0)"},
            )
            resp.raise_for_status()
            # Strip HTML tags simply
            text = re.sub(r"<[^>]+>", " ", resp.text)
            text = re.sub(r"\s+", " ", text).strip()[:4000]
            return json.dumps({"content": text})

        elif name == "read_brand_master_lists":
            path = SKILL_DIR / "references" / "brand-master-lists.md"
            content = path.read_text(encoding="utf-8") if path.exists() else "File not found"
            return json.dumps({"content": content})

        elif name == "search_hubspot_lists":
            import hubspot_tools
            return json.dumps(hubspot_tools.search_lists(inputs.get("search_term", "")))

        elif name == "get_hubspot_list":
            resp = requests.get(
                f"https://api.hubapi.com/crm/v3/lists/{inputs['list_id']}",
                headers=_hs_headers(),
            )
            return json.dumps(resp.json())

        elif name == "create_hubspot_list":
            payload = {
                "name": inputs["name"],
                "processingType": "SNAPSHOT",
                "objectTypeId": "0-1",
                "filterBranch": inputs["filter_branch"],
            }
            resp = requests.post(
                "https://api.hubapi.com/crm/v3/lists",
                headers=_hs_headers(), json=payload,
            )
            data = resp.json()
            list_id = str(data.get("listId") or data.get("id") or "")
            return json.dumps({
                "list_id": list_id,
                "name": inputs["name"],
                "url": f"https://app.hubspot.com/contacts/{HUBSPOT_PORTAL_ID}/objectLists/{list_id}/filters",
                "raw": data,
            })

        elif name == "clone_hubspot_list":
            src = requests.get(
                f"https://api.hubapi.com/crm/v3/lists/{inputs['source_list_id']}",
                headers=_hs_headers(),
            ).json()
            payload = {
                "name": inputs["new_name"],
                "processingType": src.get("processingType", "SNAPSHOT"),
                "objectTypeId": src.get("objectTypeId", "0-1"),
                "filterBranch": src.get("filterBranch", {"filterBranchType": "OR", "filters": [], "filterBranches": []}),
            }
            resp = requests.post(
                "https://api.hubapi.com/crm/v3/lists",
                headers=_hs_headers(), json=payload,
            )
            data = resp.json()
            list_id = str(data.get("listId") or data.get("id") or "")
            return json.dumps({
                "list_id": list_id,
                "name": inputs["new_name"],
                "url": f"https://app.hubspot.com/contacts/{HUBSPOT_PORTAL_ID}/objectLists/{list_id}/filters",
            })

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _sdk_run(event_url: str, q: queue.Queue) -> None:
    """Agentic loop using Anthropic SDK — same pattern as agent.py _sdk_run_turn."""
    try:
        client = _make_client()
    except Exception as exc:
        q.put({"type": "output", "text": f"Error initialising API client: {exc}"})
        q.put({"type": "done", "done": True, "success": False})
        return

    user_prompt = (
        f"Build the HubSpot audience lists for this Linux Foundation event:\n\n{event_url}\n\n"
        "Steps:\n"
        "1. fetch_url the event page — extract event name, year, brand\n"
        "2. read_brand_master_lists — find the brand's master list ID\n"
        "3. search_hubspot_lists to check if lists already exist\n"
        "4. clone_hubspot_list from list 26624 (reference) → rename to '[Brand] - [Event] - All Past Registrants'\n"
        "   Update filters: add 'Has completed event' filter for each past edition found on Snowflake\n"
        "   (skip Snowflake if unavailable — use search_hubspot_lists to find past list membership instead)\n"
        "5. create_hubspot_list '[Brand] - [Event] - Registrants + Web Visitors'\n"
        "   filter_branch: OR of (member of list 1) and (web visitor + brand master list member)\n"
        "6. create_hubspot_list '[Event] [Year] — Master Audience'\n"
        "   filter_branch: OR of lists 1 and 2\n\n"
        "Narrate every step. At the very end output:\n"
        "MASTER_LIST_ID: <numeric_id>"
    )

    messages = [{"role": "user", "content": user_prompt}]
    max_steps = 25

    for _ in range(max_steps):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=_AUDIENCE_SYSTEM,
                tools=_AUDIENCE_TOOLS,
                messages=messages,
            )
        except Exception as exc:
            q.put({"type": "output", "text": f"\nAPI error: {exc}"})
            q.put({"type": "done", "done": True, "success": False})
            return

        # Stream any text in this turn
        text_out = "".join(
            b.text for b in response.content if hasattr(b, "text") and b.text
        )
        if text_out:
            q.put({"type": "output", "text": text_out})

        serialized = [b.model_dump() if hasattr(b, "model_dump") else b for b in response.content]
        messages = messages + [{"role": "assistant", "content": serialized}]

        if response.stop_reason == "end_turn":
            q.put({"type": "done", "done": True, "success": True})
            return

        # Execute tool calls
        tool_results = []
        for block in response.content:
            if not (hasattr(block, "type") and block.type == "tool_use"):
                continue
            tool_name = block.name
            tool_input = dict(block.input)
            brief = ", ".join(f"{k}={repr(v)[:40]}" for k, v in tool_input.items())
            q.put({"type": "output", "text": f"\n→ {tool_name}({brief})"})
            result = _execute_tool(tool_name, tool_input)
            q.put({"type": "output", "text": "  ✓\n"})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        if tool_results:
            messages = messages + [{"role": "user", "content": tool_results}]

    q.put({"type": "output", "text": "\n⚠ Max steps reached without completion"})
    q.put({"type": "done", "done": True, "success": False})


# ══════════════════════════════════════════════════════════════════════════════
# Mode 3 — Claude Code CLI subprocess
# ══════════════════════════════════════════════════════════════════════════════

_CLI_PROMPT = """\
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

Narrate what you are doing at every sub-step.

IMPORTANT: At the very end output exactly this line (substitute the real numeric ID):
MASTER_LIST_ID: <numeric_hubspot_list_id>
"""

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
    raise RuntimeError("claude CLI not found — install with: npm install -g @anthropic-ai/claude-code")


def _cli_run(event_url: str, q: queue.Queue) -> None:
    """Fallback: spawn claude CLI subprocess (uses local Claude Code session auth)."""
    try:
        claude_cmd = _get_claude_cli()
    except RuntimeError as exc:
        q.put({"type": "output", "text": f"Error: {exc}"})
        q.put({"type": "done", "done": True, "success": False})
        return

    skill_dir = str(SKILL_DIR) if SKILL_DIR.is_dir() else None
    if not skill_dir:
        q.put({"type": "output", "text": f"⚠ Skill directory not found: {SKILL_DIR}"})

    prompt = _CLI_PROMPT.format(url=event_url)
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
            cwd=skill_dir,
        )

        def _reader():
            for line in proc.stdout:
                q.put({"type": "output", "text": line.rstrip()})

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        try:
            proc.wait(timeout=_CLI_TIMEOUT)
            reader.join(timeout=10)
            success = proc.returncode == 0
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            reader.join(timeout=5)
            q.put({"type": "output", "text": f"\n⚠ Timed out after {_CLI_TIMEOUT // 60} min — process killed."})
            success = False

        q.put({"type": "done", "done": True, "success": success})

    except Exception as exc:
        q.put({"type": "output", "text": f"Error: {exc}"})
        q.put({"type": "done", "done": True, "success": False})
