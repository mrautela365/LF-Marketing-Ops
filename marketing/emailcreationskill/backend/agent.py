"""
Claude agentic loop.

Three modes — same interface, same tools:
  • LiteLLM proxy mode  (LITELLM_BASE_URL + LITELLM_API_KEY set) → Anthropic SDK → LF LiteLLM cluster
  • Anthropic SDK mode  (ANTHROPIC_API_KEY set)                  → Anthropic SDK → api.anthropic.com
  • Claude Code mode    (neither key set)                        → claude CLI subprocess

Priority: LiteLLM → Anthropic → Claude Code CLI
"""
import json
import os
import subprocess
import asyncio
import nest_asyncio
nest_asyncio.apply()  # allows asyncio.run() inside FastAPI's event loop
from datetime import datetime
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, LITELLM_BASE_URL, LITELLM_API_KEY
import hubspot_tools
import content_tools

import shutil

# ── SDK client factory ────────────────────────────────────────────────────────

def _has_sdk_key() -> bool:
    """True when an API key is available for direct SDK calls."""
    return bool(LITELLM_API_KEY or ANTHROPIC_API_KEY)

def _make_client():
    """Return an Anthropic SDK client pointed at the right endpoint."""
    import anthropic
    if LITELLM_BASE_URL and LITELLM_API_KEY:
        return anthropic.Anthropic(api_key=LITELLM_API_KEY, base_url=LITELLM_BASE_URL)
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Find the claude CLI — resolved lazily, only when the CLI fallback mode is
# actually used (LiteLLM/Anthropic SDK users should never need it installed) ──
_CLAUDE_CLI: str | None = None

def _get_claude_cli() -> str:
    global _CLAUDE_CLI
    if _CLAUDE_CLI:
        return _CLAUDE_CLI
    if env_path := os.getenv("CLAUDE_CLI_PATH"):
        _CLAUDE_CLI = env_path
        return env_path
    if found := shutil.which("claude"):
        _CLAUDE_CLI = found
        return found
    fallback = r"C:\Users\VinayU\AppData\Roaming\npm\claude.cmd"
    if os.path.exists(fallback):
        _CLAUDE_CLI = fallback
        return fallback
    raise RuntimeError("claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code")

# ── Shared system prompt ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an email staging assistant for Linux Foundation marketing operations.
You stage HubSpot marketing emails from event URLs through a 3-phase flow:

PHASE 1 - PLAN: User provides an event/campaign URL.
  1. Call fetch_url to extract event name, dates, organization, description from the URL.
  2. From those details, infer: brand (HubSpot brand name), email type, and email suffix.
  3. Call lookup_brand_history to get sender settings, send list, suppression lists.
  4. Build and present a complete Email Staging Plan — see format rules below.

PHASE 2 - STAGE: User approves the plan (may provide missing fields).
  1. Call clone_email with the correct name.
  2. Call update_email_settings to apply from name, from address, email type, suppression lists.
  3. Return the HubSpot draft URL and ask for content.

PHASE 3 - CONTENT: User provides content (Google Doc URL, HTML, or text).
  1. Call fetch_content to convert to clean email HTML.
  2. Call update_email_content to update the email body.
  3. Return the final summary with draft link.

Plan format rules (STRICTLY follow):
  - NEVER mention cloning, source emails, or templates — only show the final staged settings.
  - Present as a clean summary with two sections:
    (a) A settings table with: Email Name, From Name, From Address, Email Type, Subject, Preview Text, Send Date
    (b) Audience section showing: Send List (with contact count if available), Suppression Lists
  - Mark fields that need user input as [REQUIRED — provide below]
  - Add a short paragraph summary at the top describing what will be staged.
  - After the plan table, ask ONLY for the specific missing fields.

Email naming convention:
  "<YY>Q<N> - <Brand> - <EventName> - <Suffix>"
  Examples: "26Q2 - CNCF - KubeCon EU - Invite", "26Q2 - OpenSSF - Newsletter - June"
  Quarter: Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec
  Suffix: Invite / Last Chance / Newsletter / Update / Reminder

Safety rules (never violate):
  - NEVER delete, archive, or send any email or list.
  - NEVER modify any existing HubSpot list.
  - NEVER call update_email_settings or update_email_content on any email
    except the one created in the current session.
  - Always keep emails in DRAFT state.

Current date: {date}
HubSpot Portal: 8112310
"""

# ── Tool definitions (shared) ─────────────────────────────────────────────────

TOOLS = [
    {
        "name": "lookup_brand_history",
        "description": "Look up the most recently sent HubSpot email for a brand. Returns from name, from address, suppression list IDs, email type, and last email ID. Always call this first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "brand_name": {"type": "string"},
                "email_type_hint": {"type": "string", "description": "Optional: newsletter, event_invite, transactional"}
            },
            "required": ["brand_name"]
        },
    },
    {
        "name": "clone_email",
        "description": "Clone a HubSpot email with a new name. Returns new email ID and draft URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_email_id": {"type": "string"},
                "clone_name": {"type": "string"}
            },
            "required": ["source_email_id", "clone_name"],
        },
    },
    {
        "name": "update_email_settings",
        "description": "Update email subject, preview text, from name/address, suppression list IDs, send list ID, email type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string"},
                "subject": {"type": "string"},
                "preview_text": {"type": "string"},
                "from_name": {"type": "string"},
                "from_address": {"type": "string"},
                "suppression_list_ids": {"type": "array", "items": {"type": "string"}},
                "send_list_id": {"type": "string"},
                "email_type": {"type": "string"},
            },
            "required": ["email_id"],
        },
    },
    {
        "name": "update_email_content",
        "description": "Replace the email body with HTML. Auto-handles html_body and widget-module templates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string"},
                "html_content": {"type": "string"}
            },
            "required": ["email_id", "html_content"],
        },
    },
    {
        "name": "fetch_content",
        "description": "Convert a Google Doc URL, raw HTML, or plain text into clean email HTML.",
        "input_schema": {
            "type": "object",
            "properties": {"content_input": {"type": "string"}},
            "required": ["content_input"],
        },
    },
    {
        "name": "search_hubspot_lists",
        "description": "Search HubSpot contact lists by name.",
        "input_schema": {
            "type": "object",
            "properties": {"search_term": {"type": "string"}},
            "required": ["search_term"],
        },
    },
    {
        "name": "fetch_url",
        "description": (
            "Fetch an event or campaign URL and extract: event_name, brand_name, location, "
            "event_dates, description. Always call this first when given a URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "search_emails_for_event",
        "description": (
            "Search HubSpot for the most recently sent email matching a brand + event name. "
            "Filters by short_brand_name (e.g. 'LF', 'CNCF') and scores by event_name keywords. "
            "Finds the same event's previous email for pre-populating settings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand_name":       {"type": "string", "description": "Full brand name"},
                "event_name":       {"type": "string", "description": "Canonical event name"},
                "location":         {"type": "string", "description": "Location hint (optional)"},
                "short_brand_name": {"type": "string", "description": "Short brand code, e.g. LF, CNCF, PTF"},
                "event_short_name": {"type": "string", "description": "Short event name, e.g. OSS Japan, KubeCon EU"},
                "email_type":       {"type": "string", "description": "Email suffix hint: Invite, Last Chance, Newsletter, Reminder, Update"},
            },
            "required": ["brand_name", "event_name"],
        },
    },
]

# ── Tool executor (shared by both modes) ──────────────────────────────────────

import logging
_log = logging.getLogger("email-staging.agent")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _lh = logging.StreamHandler()
    _lh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    _log.addHandler(_lh)
    _log.propagate = False

# Tracks the email ID cloned in the current session — only this ID may be modified.
# Set by clone_email tool call, checked before any update operation.
# NOTE: This is per-process, not per-session. Use session.meta["email_id"] as the
# authoritative source; this global is a fallback.
_session_email_id: str | None = None

# Tools that are completely forbidden regardless of inputs
_FORBIDDEN_TOOLS = {"delete_email", "delete_list", "delete_contact", "archive_email"}

# Tools that perform write operations on HubSpot — must be validated
_WRITE_TOOLS = {"update_email_settings", "update_email_content"}


def _execute_tool(name: str, inputs: dict, session_email_id: str | None = None) -> str:
    global _session_email_id  # declared first — used later in clone_email branch
    _log.info(f"  → TOOL {name}({', '.join(f'{k}={str(v)[:40]!r}' for k,v in inputs.items())})")

    # ── Safety gate 1: block any delete/archive tools outright ──────────────
    if name in _FORBIDDEN_TOOLS:
        _log.warning(f"  ✗ BLOCKED forbidden tool: {name}")
        return json.dumps({"error": f"Tool '{name}' is not permitted. This service never deletes or archives."})

    # ── Safety gate 2: write ops only allowed on the session-created email ──
    if name in _WRITE_TOOLS:
        target_id = inputs.get("email_id")
        allowed_id = session_email_id or _session_email_id
        if not allowed_id:
            return json.dumps({"error": "No email has been cloned in this session yet. Clone first."})
        if target_id != allowed_id:
            _log.warning(f"  ✗ BLOCKED write to email {target_id} — only {allowed_id} is allowed this session")
            return json.dumps({
                "error": f"Write blocked: email {target_id} was not created by this session. "
                         f"Only email {allowed_id} (cloned in this session) may be modified."
            })

    try:
        if name == "lookup_brand_history":
            result = hubspot_tools.lookup_brand_history(
                inputs["brand_name"],
                email_type_hint=inputs.get("email_type_hint")
            )
        elif name == "clone_email":
            result = hubspot_tools.clone_email(inputs["source_email_id"], inputs["clone_name"])
            # Register the newly created email ID — only this may be modified
            _session_email_id = result.get("email_id")
            _log.info(f"  ✓ Session email locked to: {_session_email_id}")
        elif name == "update_email_settings":
            email_id = inputs.pop("email_id")
            result = hubspot_tools.update_email_settings(email_id, **inputs)
        elif name == "update_email_content":
            result = hubspot_tools.update_email_content(inputs["email_id"], inputs["html_content"])
        elif name == "fetch_content":
            html = content_tools.prepare_content(inputs["content_input"])
            result = {"html": html, "length": len(html)}
        elif name == "search_hubspot_lists":
            result = hubspot_tools.search_hubspot_lists(inputs["search_term"])
        elif name == "fetch_url":
            result = content_tools.scrape_event_full(inputs["url"])
        elif name == "search_emails_for_event":
            result = hubspot_tools.search_emails_for_event(
                inputs["brand_name"],
                inputs["event_name"],
                inputs.get("location", ""),
                short_brand_name=inputs.get("short_brand_name", ""),
                event_short_name=inputs.get("event_short_name", ""),
                email_type=inputs.get("email_type", ""),
            )
        else:
            result = {"error": f"Unknown tool: {name}. Allowed: lookup_brand_history, clone_email, "
                               "update_email_settings, update_email_content, fetch_content, search_hubspot_lists"}
    except Exception as exc:
        result = {"error": str(exc)}
    return json.dumps(result)


# ── Mode 1: Anthropic SDK (API key available) ─────────────────────────────────

def _sdk_run_turn(messages: list, user_message: str) -> tuple[str, list]:
    client = _make_client()
    system = SYSTEM_PROMPT.format(date=datetime.now().strftime("%Y-%m-%d"))
    messages = messages + [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=system,
            tools=TOOLS,
            messages=messages,
        )
        serialized = [b.model_dump() if hasattr(b, "model_dump") else b for b in response.content]
        messages = messages + [{"role": "assistant", "content": serialized}]

        if response.stop_reason == "end_turn":
            text = "".join(b.text for b in response.content if hasattr(b, "text"))
            return text, messages

        tool_results = []
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _execute_tool(block.name, dict(block.input)),
                })
        messages = messages + [{"role": "user", "content": tool_results}]


# ── Mode 2: Claude Code SDK (no API key — uses Claude Code's own auth) ────────

_TOOL_INSTRUCTIONS = """
IMPORTANT: You are operating in EXECUTION MODE. Do NOT enter plan mode. Do NOT ask for approval.
Execute tool calls immediately and directly.

To call a tool output EXACTLY this on its own line (nothing else on that line):
  TOOL_CALL: {"name": "<tool>", "input": {<params>}}

Available tools:
  fetch_url(url)                                          — scrape event URL: event_name, brand_name, location, event_dates
  search_emails_for_event(brand_name, event_name, location?) — find last sent email for this brand+event, returns all settings
  lookup_brand_history(brand_name, email_type_hint?)      — fallback: most recent brand email (use search_emails_for_event first)
  clone_email(source_email_id, clone_name)
  update_email_settings(email_id, subject?, preview_text?, from_name?, from_address?, suppression_list_ids?, send_list_id?, email_type?)
  update_email_content(email_id, html_content)
  fetch_content(content_input)
  search_hubspot_lists(search_term)

Tool results are returned as:
  TOOL_RESULT: {<json>}

Rules:
- Call tools immediately without asking for confirmation
- Do NOT say "I'll now...", "Let me...", or "I plan to..." — just output the TOOL_CALL line
- When all tools are done, write your final response to the user
"""

def _sdk_run_turn_cc(messages: list, user_message: str) -> tuple[str, list]:
    """
    Run one turn using the claude CLI via stdin pipe.

    Auth chain: FastAPI → subprocess (stdin) → claude CLI → ~/.claude/ token → Anthropic
    No ANTHROPIC_API_KEY needed. Avoids all Windows .cmd argument mangling by
    sending the prompt through stdin instead of as a command-line argument.
    """
    system = SYSTEM_PROMPT.format(date=datetime.now().strftime("%Y-%m-%d"))

    # Build conversation history (last 6 messages for context, skip internal __tool_log__ entries)
    history = ""
    visible_msgs = [m for m in messages if m.get("role") not in ("__tool_log__",)]
    for msg in visible_msgs[-6:]:
        role = "User" if msg.get("role") == "user" else "Assistant"
        content = msg.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content)[:400]
        history += f"{role}: {content}\n\n"

    # Embed system context in stdin — avoids --system-prompt arg escaping issues
    prompt = (
        f"<system>\n{system}\n</system>\n\n"
        f"{_TOOL_INSTRUCTIONS}\n\n"
        f"Conversation history:\n{history}"
        f"User: {user_message}"
    )

    def _call_claude(stdin_text: str) -> str:
        """Call claude --print with prompt via stdin. Returns stdout text."""
        import sys as _sys
        popen_kw = {}
        if _sys.platform == "win32":
            popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            [_get_claude_cli(), "--print", "--dangerously-skip-permissions"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **popen_kw,
        )
        try:
            stdout_b, stderr_b = proc.communicate(
                input=stdin_text.encode("utf-8", errors="replace"), timeout=90
            )
        except subprocess.TimeoutExpired:
            if _sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
            raise RuntimeError("Claude CLI timed out after 90s")

        if proc.returncode != 0:
            stderr_text = stderr_b.decode("utf-8", errors="replace").strip()
            stdout_text = stdout_b.decode("utf-8", errors="replace").strip()
            detail = stderr_text or stdout_text or f"exit code {proc.returncode}"
            raise RuntimeError(f"Claude CLI error: {detail}")
        return stdout_b.decode("utf-8", errors="replace").strip()

    # Pull session email ID from conversation history (set during clone step)
    session_email_id: str | None = _session_email_id

    # Collect tool results so they can be stored in messages and read by later turns
    collected_tool_results: list[dict] = []

    # Agentic loop — Claude calls tools until it has a final answer
    max_steps = 8
    full_response = ""
    # Track the richest plan content seen across all responses.
    # Claude sometimes writes the plan table in an intermediate response (before
    # calling the last tool) and then says "presented above" in the final response.
    # We use best_plan_response as a fallback when the final response is thin.
    best_plan_response = ""

    for _ in range(max_steps):
        response = _call_claude(prompt)

        # Detect a TOOL_CALL line
        tool_line = next(
            (line.strip()[len("TOOL_CALL:"):].strip()
             for line in response.splitlines()
             if line.strip().startswith("TOOL_CALL:")),
            None,
        )

        if tool_line:
            try:
                call = json.loads(tool_line)
                tool_result = _execute_tool(
                    call["name"],
                    call.get("input", {}),
                    session_email_id=session_email_id,
                )
                # Store result for later phases to read
                try:
                    result_data = json.loads(tool_result)
                    collected_tool_results.append({
                        "type": "tool_result",
                        "tool": call["name"],
                        "content": tool_result,
                    })
                    if "email_id" in result_data:
                        session_email_id = result_data["email_id"]
                except Exception:
                    pass
            except Exception as e:
                tool_result = json.dumps({"error": str(e)})
            prompt += f"\n{response}\nTOOL_RESULT: {tool_result}\n"
            full_response += response + "\n"
            # If this intermediate response contains a plan table, remember it
            non_tool = "\n".join(
                l for l in response.splitlines() if not l.strip().startswith("TOOL_CALL:")
            ).strip()
            if ("##" in non_tool or "|---|" in non_tool) and len(non_tool) > len(best_plan_response):
                best_plan_response = non_tool
        else:
            # Final response — use it if it contains plan content, otherwise fall
            # back to the richest intermediate response seen (avoids "above" problem)
            has_plan = "##" in response or "|---|" in response or len(response) > 400
            if has_plan:
                full_response = response
            elif best_plan_response:
                _log.warning("[CC] Final response is thin ('above' pattern) — using best intermediate plan")
                full_response = best_plan_response
            else:
                full_response = response
            break

    # Store tool results in messages so subsequent turns (clone, content) can read them
    # This bridges the gap: Claude Code mode doesn't use structured tool_use blocks,
    # so we inject the results as a special message that extract_brand_history_from_messages can find.
    # Strip TOOL_CALL / TOOL_RESULT lines — they are protocol markers, not UX text
    clean_lines = [
        l for l in full_response.splitlines()
        if not l.strip().startswith("TOOL_CALL:") and not l.strip().startswith("TOOL_RESULT:")
    ]
    full_response = "\n".join(clean_lines).strip()

    tool_msg = []
    for tr in collected_tool_results:
        tool_msg.append({
            "type": "tool_result",
            "tool": tr["tool"],
            "content": tr["content"],
        })

    updated_messages = messages + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": full_response},
    ]
    if tool_msg:
        updated_messages.append({"role": "__tool_log__", "content": tool_msg})

    return full_response, updated_messages


# ── Single-turn Claude helper (no tools, plain text) ─────────────────────────

def _claude_text(prompt: str, max_tokens: int = 100, timeout: int = 60) -> str:
    """Ask Claude a simple question and return plain text. No tools, no history."""
    if _has_sdk_key():
        client = _make_client()
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
    else:
        import sys as _sys
        popen_kw = {}
        if _sys.platform == "win32":
            popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            [_get_claude_cli(), "--print", "--dangerously-skip-permissions"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **popen_kw,
        )
        try:
            stdout_b, stderr_b = proc.communicate(
                input=prompt.encode("utf-8", errors="replace"), timeout=timeout
            )
        except subprocess.TimeoutExpired:
            if _sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
            raise RuntimeError(f"Claude CLI timed out after {timeout}s generating content")

        if proc.returncode != 0:
            stderr_text = stderr_b.decode("utf-8", errors="replace").strip()
            stdout_text = stdout_b.decode("utf-8", errors="replace").strip()
            detail = stderr_text or stdout_text or f"exit code {proc.returncode}"
            raise RuntimeError(f"Claude CLI: {detail}")
        return stdout_b.decode("utf-8", errors="replace").strip()


def fetch_asana_task_via_mcp(task_url: str) -> dict:
    """
    Fetch Asana task + subtask data via the Asana MCP connector (Claude Code subprocess).
    Used when ASANA_ACCESS_TOKEN is not set — requires the Asana MCP to be authenticated
    in the parent Claude Code session.
    Returns the same shape as asana_tools.extract_brief().
    """
    import re as _re

    prompt = f"""Use the Asana MCP tools to fetch task data and return it as a JSON object.

Asana task URL: {task_url}

Steps:
1. Extract the task GID from the URL (it is the numeric ID after /task/)
2. Call get_task with that GID requesting fields: name, notes, due_on, projects
3. Call get_tasks or a subtask lookup to list subtasks of this task (fields: name, notes, gid)
4. For any subtask named "Content" or "List Pull", read its notes carefully for URLs and instructions

Return ONLY this JSON (no markdown fences, no explanation — raw JSON only):
{{
  "task_name": "<full parent task name>",
  "brand_name": "<brand from task name pattern 'YYQn - BRAND - ...' — or empty string>",
  "content_doc_url": "<first docs.google.com/document URL found in Content subtask, or empty string>",
  "event_url": "<first LF event URL (linuxfoundation.org / cncf.io / etc.) found anywhere, or empty string>",
  "audience_instructions": "<text from List Pull subtask notes, or empty string>",
  "due_on": "<due date YYYY-MM-DD, or empty string>",
  "subtask_names": ["subtask name 1", "subtask name 2"]
}}"""

    # Always use CLI subprocess — MCP tools are only available via Claude Code,
    # not through the Anthropic SDK even if ANTHROPIC_API_KEY is set.
    import sys as _sys
    popen_kw = {}
    if _sys.platform == "win32":
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        [_get_claude_cli(), "--print", "--dangerously-skip-permissions"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        **popen_kw,
    )
    try:
        stdout_b, stderr_b = proc.communicate(
            input=prompt.encode("utf-8", errors="replace"), timeout=180
        )
    except subprocess.TimeoutExpired:
        if _sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.kill()
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        raise RuntimeError("Asana MCP fetch timed out after 180s")

    if proc.returncode != 0:
        stderr_text = stderr_b.decode("utf-8", errors="replace").strip()
        stdout_text = stdout_b.decode("utf-8", errors="replace").strip()
        detail = stderr_text or stdout_text or f"exit code {proc.returncode}"
        raise RuntimeError(f"Claude CLI error: {detail}")

    raw = stdout_b.decode("utf-8", errors="replace").strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0].strip()

    m = _re.search(r'\{[\s\S]+\}', raw)
    if not m:
        raise ValueError(f"MCP fetch returned no JSON. Response was: {raw[:300]}")

    data = json.loads(m.group(0))
    data.setdefault("email_name", data.get("task_name", ""))
    data.setdefault("subtask_names", [])
    return data


import re as _re

# Patterns that Claude should never emit in rich_text sections — the system adds them.
_STRIP_PATTERNS = [
    # "Thank You to Our Sponsors!" heading
    r'<[^>]+>[^<]*[Tt]hank [Yy]ou to [Oo]ur [Ss]ponsors[!]?[^<]*</[^>]+>',
    # "This email was sent by: ..." footer line
    r'<[^>]+>[^<]*[Tt]his email was sent by[^<]*</[^>]+>',
    # "Subscription Center" or "Unsubscribe" footer paragraphs
    r'<[^>]+>[^<]*[Uu]nsubscribe[^<]*</[^>]+>',
    r'<[^>]+>[^<]*[Ss]ubscription [Cc]enter[^<]*</[^>]+>',
    # LF address footer
    r'<[^>]+>[^<]*2810 N Church[^<]*</[^>]+>',
    r'<[^>]+>[^<]*Wilmington, Delaware[^<]*</[^>]+>',
    # "View in browser" header link — HubSpot adds this automatically; never put it in body content
    r'<[^>]+>[^<]*[Vv]iew (?:this )?(?:email )?in (?:your )?[Bb]rowser[^<]*</[^>]+>',
    r'<a[^>]*>[^<]*[Vv]iew in [Bb]rowser[^<]*</a>',
]
_STRIP_RE = _re.compile("|".join(_STRIP_PATTERNS), _re.IGNORECASE)


def _strip_system_content(html: str) -> str:
    """Remove headings/lines that the system adds automatically (sponsors, footer, sent-by)."""
    return _STRIP_RE.sub("", html).strip()


def _sections_to_html(sections: list, btn_color: str = "#04c0da",
                      sponsors: list = None) -> str:
    """Convert structured sections array to flat HTML for the UI iframe preview."""
    parts = []
    for sec in sections:
        stype = sec.get("type", "")
        if stype == "rich_text":
            html = _strip_system_content(sec.get("html", "").strip())
            if html:
                parts.append(f'<div style="padding:15px 40px 10px;">{html}</div>')
        elif stype == "button":
            text  = sec.get("text", "")
            url   = sec.get("url", "#")
            color = sec.get("color") or btn_color
            parts.append(
                f'<div style="text-align:center;padding:5px 20px;">'
                f'<table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto;">'
                f'<tr><td style="background-color:{color};border-radius:8px;'
                f'padding:12px 24px;text-align:center;">'
                f'<a href="{url}" style="color:#ffffff;font-weight:bold;font-size:16px;'
                f'text-decoration:none;font-family:Arial,sans-serif;">{text}</a>'
                f'</td></tr></table></div>'
            )
    _logo_sponsors = [s for s in (sponsors or []) if isinstance(s, dict) and s.get("logo_url")]
    _tier1 = _logo_sponsors[:5]   # top tier — up to 5, larger
    _tier2 = _logo_sponsors[5:8]  # next tier — up to 3, smaller
    if _tier1:
        parts.append(
            '<div style="padding:10px 40px;">'
            '<hr style="border:none;border-top:1px solid #eee;margin:10px 0;">'
            '</div>'
            '<p style="font-weight:bold;text-align:center;font-size:18px;'
            'padding:0 40px;margin:0 0 10px;">Thank You to Our Sponsors!</p>'
        )
        imgs1 = "".join(
            f'<td style="padding:8px 16px;text-align:center;">'
            f'<img src="{s["logo_url"]}" alt="{s.get("name","Sponsor")}" '
            f'height="60" style="max-width:180px;height:60px;object-fit:contain;"></td>'
            for s in _tier1
        )
        parts.append(
            f'<table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto;">'
            f'<tr>{imgs1}</tr></table>'
        )
        if _tier2:
            imgs2 = "".join(
                f'<td style="padding:6px 12px;text-align:center;">'
                f'<img src="{s["logo_url"]}" alt="{s.get("name","Sponsor")}" '
                f'height="45" style="max-width:140px;height:45px;object-fit:contain;"></td>'
                for s in _tier2
            )
            parts.append(
                f'<table cellpadding="0" cellspacing="0" border="0" style="margin:4px auto 0;">'
                f'<tr>{imgs2}</tr></table>'
            )
    return "\n".join(parts)


def _build_email_preview(banner_url: str, body_html: str,
                         event_url: str = "", event_name: str = "") -> str:
    """Build a standalone preview HTML email for display in the browser iframe."""
    if banner_url:
        link_open  = ('<a href="' + event_url + '" target="_blank" style="display:block;line-height:0;font-size:0;">') if event_url else ""
        link_close = "</a>" if event_url else ""
        banner_row = (
            '<tr><td style="background-color:#003366;text-align:center;padding:0;line-height:0;font-size:0;">'
            + link_open
            + '<img src="' + banner_url + '" width="600" alt="' + event_name + '"'
            + ' style="display:block;width:100%;max-width:600px;height:auto;">'
            + link_close
            + "</td></tr>"
        )
    else:
        banner_row = '<tr><td style="background-color:#003366;height:8px;"></td></tr>'

    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        # Guard: any image (hero, inline body, reference) is capped to the column
        # width so it can never overflow the preview. Inline styles (system hero,
        # sponsor logos) still win for their own sizing.
        "<style>img{max-width:100%;height:auto;} table{max-width:100%;}</style>"
        "</head>"
        '<body style="margin:0;padding:0;background-color:#F4F4F4;font-family:Arial,sans-serif;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background-color:#F4F4F4;">'
        '<tr><td align="center" style="padding:20px 0;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"'
        ' style="max-width:600px;width:100%;background-color:#ffffff;'
        'border-radius:4px;overflow:hidden;">'
        + banner_row
        + "<tr><td>" + body_html + "</td></tr>"
        # ── Pre-footer divider ──────────────────────────────────────────
        + '<tr><td style="padding:0 40px;">'
        '<hr style="border:none;border-top:1px solid #23496d;margin:20px 0 0;">'
        "</td></tr>"
        # ── Social icons row (CSS circles — no external image dependency) ─
        + '<tr><td style="background-color:#ffffff;padding:16px 40px;text-align:center;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"'
        ' style="margin:0 auto;">'
        "<tr>"
        # LFX
        '<td style="padding:0 6px;">'
        '<a href="https://insights.linuxfoundation.org/'
        '?utm_campaign=23551824-Q3-2025-LF-Awareness-LFX-Insights'
        '&amp;utm_source=email&amp;utm_medium=LF-Events&amp;utm_content=regular-email"'
        ' target="_blank" style="display:inline-block;width:32px;height:32px;'
        'background-color:#09c0d9;border-radius:50%;color:#ffffff;text-align:center;'
        'line-height:32px;text-decoration:none;font-weight:bold;font-size:11px;'
        'font-family:Arial,sans-serif;">LFX</a></td>'
        # Twitter / X
        '<td style="padding:0 6px;">'
        '<a href="https://twitter.com/linuxfoundation" target="_blank"'
        ' style="display:inline-block;width:32px;height:32px;background-color:#000000;'
        'border-radius:50%;color:#ffffff;text-align:center;line-height:32px;'
        'text-decoration:none;font-weight:bold;font-size:14px;'
        'font-family:Arial,sans-serif;">𝕏</a></td>'
        # LinkedIn
        '<td style="padding:0 6px;">'
        '<a href="https://www.linkedin.com/company/the-linux-foundation/" target="_blank"'
        ' style="display:inline-block;width:32px;height:32px;background-color:#0077b5;'
        'border-radius:50%;color:#ffffff;text-align:center;line-height:32px;'
        'text-decoration:none;font-weight:bold;font-size:13px;'
        'font-family:Arial,sans-serif;">in</a></td>'
        # Facebook
        '<td style="padding:0 6px;">'
        '<a href="https://www.facebook.com/TheLinuxFoundation/" target="_blank"'
        ' style="display:inline-block;width:32px;height:32px;background-color:#1877f2;'
        'border-radius:50%;color:#ffffff;text-align:center;line-height:32px;'
        'text-decoration:none;font-weight:bold;font-size:16px;'
        'font-family:Arial,sans-serif;">f</a></td>'
        "</tr></table>"
        "</td></tr>"
        # ── "Sent by" text ──────────────────────────────────────────────
        + '<tr><td style="background-color:#ffffff;padding:0 40px 8px;text-align:center;">'
        '<p style="margin:0;font-size:12px;line-height:175%;color:#000000;">'
        "This email was sent by: "
        '<strong>The Linux Foundation Events</strong>'
        "</p>"
        "</td></tr>"
        # ── Address + subscription center ───────────────────────────────
        + '<tr><td style="background-color:#ffffff;padding:0 40px 24px;text-align:center;">'
        '<p style="margin:0 0 6px;font-size:12px;line-height:150%;color:#666666;">'
        "The Linux Foundation, 2810 N Church St., PMB 57274,<br>"
        "Wilmington, Delaware 19802-4447, United States"
        "</p>"
        '<p style="margin:0;font-size:12px;">'
        '<a href="{{ unsubscribe_link }}"'
        ' style="color:#0094ff;text-decoration:underline;">Subscription Center</a>'
        "</p>"
        "</td></tr>"
        "</table></td></tr></table></body></html>"
    )


def generate_email_content(
    event_details: dict,
    stage_info: dict,
    brand_history: dict | None,
    change_request: str = "",
    source_email_id: str = "",
) -> dict:  # noqa: C901
    """
    Generate subject, preview text, and full HTML email body.

    Primary mode: fetches the reference email's actual content (the most recent
    sent email for this brand/stage) and asks Claude to produce a similar email
    for the new event — same structure, tone, and style; all event-specific
    content (name, dates, speakers, sponsors) substituted.

    Fallback: if no reference email is available, falls back to the official
    Marketing Journey stage template.

    Returns: {subject, preview_text, html, body_html, banner_url}
    """
    import re as _re
    import logging as _logging
    _log = _logging.getLogger("email-staging")

    event_name    = event_details.get("event_name", "")
    event_dates   = event_details.get("event_dates", [])
    location      = event_details.get("location", "")
    description   = (event_details.get("description") or "")[:400]
    url           = event_details.get("url", "")
    hero_img      = event_details.get("hero_image_url", "")
    logo_img      = event_details.get("logo_url", "")
    speakers      = event_details.get("speakers", [])
    topics        = event_details.get("topics", [])
    sponsors      = event_details.get("sponsors", [])[:8]
    reg           = event_details.get("registration") or {}

    stage_name         = stage_info.get("name", "")
    funnel             = stage_info.get("funnel", "")
    cta_label          = stage_info.get("cta_label", "Register Now")
    event_date         = stage_info.get("event_date_str", "") or (event_dates[0] if event_dates else "")
    from_name          = (brand_history or {}).get("from_name") or "Linux Foundation Events"
    dates_display      = event_dates[0] if event_dates else event_date
    marketing_strategy = stage_info.get("marketing_strategy", "")
    content_ideas      = stage_info.get("content_ideas", [])

    # Upload hero / logo / sponsor images to HubSpot CDN for reliable rendering
    from hubspot_tools import upload_image_to_hubspot as _upload_img
    _log.info(f"[GEN_EMAIL] hero={hero_img!r} logo={logo_img!r} source_ref={source_email_id!r}")
    if hero_img:
        hero_img = _upload_img(hero_img) or hero_img
    if logo_img:
        logo_img = _upload_img(logo_img) or logo_img
    banner_url = hero_img

    # Upload sponsor logos to HubSpot CDN.
    # Only keep sponsors whose logo successfully uploaded — text-only sponsors are excluded.
    uploaded_sponsors = []
    for sp in sponsors:
        if isinstance(sp, dict):
            raw_logo = sp.get("logo_url", "")
            if not raw_logo:
                continue  # no logo URL at all — skip
            cdn_logo = _upload_img(raw_logo) or raw_logo
            if cdn_logo:
                uploaded_sponsors.append({"name": sp.get("name", ""), "logo_url": cdn_logo})
    sponsors = uploaded_sponsors
    _log.info(f"[GEN_EMAIL] sponsors with logos: {len(sponsors)} (text-only sponsors excluded)")

    # Build supplementary context lines
    reg_lines = []
    if reg.get("ticket_types"):
        reg_lines.append(f"Ticket info: {'; '.join(reg['ticket_types'][:2])}")
    if reg.get("deadlines"):
        reg_lines.append(f"Deadline: {reg['deadlines'][0]}")
    if reg.get("url"):
        reg_lines.append(f"Register at: {reg['url']}")
    reg_info = "\n".join(reg_lines)

    speakers_str = "\n".join(f"  • {s}" for s in speakers) if speakers else "  (to be announced)"

    def _sponsor_line(s) -> str:
        if isinstance(s, dict):
            name = s.get("name", "")
            logo = s.get("logo_url", "")
            return f"  • {name}" + (f"  [logo: {logo}]" if logo else "")
        return f"  • {s}"

    sponsors_str = "\n".join(_sponsor_line(s) for s in sponsors) if sponsors else "  (not listed on event page)"
    topics_str   = ", ".join(topics[:4]) if topics else "Open Source, Cloud Native, Linux"

    # HubSpot personalization tokens
    hs_firstname = "{{ contact.firstname }}"
    hs_company   = "{{ contact.company }}"

    # ── Fetch reference email from HubSpot (primary mode) ─────────────────────
    ref_block = ""
    ref_name  = ""
    ref       = {}   # keep in scope for task_instructions block below
    if source_email_id:
        try:
            import hubspot_tools as _ht
            ref = _ht.get_email_content_text(source_email_id)
            ref_sections  = ref.get("sections", [])
            ref_body_html = ref.get("body_html", "")
            ref_body_text = ref.get("body_text", "")

            if ref.get("success") and (ref_sections or ref_body_html):
                ref_name = ref.get("email_name", source_email_id)
                ref_subj = ref.get("subject", "")
                ref_prev = ref.get("preview_text", "")

                # Build a component-by-component layout description so Claude
                # knows the exact sequence: image → rich_text → button → divider…
                layout_lines = []
                for i, comp in enumerate(ref_sections):
                    ctype = comp.get("type", "")
                    if ctype == "image":
                        layout_lines.append(f"  [{i+1}] IMAGE — hero banner (full-width event graphic)")
                    elif ctype == "image_row":
                        imgs = comp.get("images", [])
                        alts = ", ".join(im.get("alt", "?") for im in imgs)
                        layout_lines.append(f"  [{i+1}] IMAGE ROW ({len(imgs)} columns) — sponsor logos: {alts}")
                    elif ctype == "rich_text":
                        preview = _re.sub(r"<[^>]+>", "", comp.get("html", ""))[:80].strip()
                        layout_lines.append(f"  [{i+1}] RICH TEXT — \"{preview}…\"")
                    elif ctype == "button":
                        layout_lines.append(
                            f"  [{i+1}] BUTTON — \"{comp.get('text','')}\" "
                            f"bg={comp.get('background_color','#04c0da')}"
                        )
                    elif ctype == "divider":
                        layout_lines.append(f"  [{i+1}] DIVIDER — {comp.get('style','solid')} {comp.get('height',1)}px")
                    elif ctype == "social_icons":
                        layout_lines.append(f"  [{i+1}] SOCIAL ICONS — {comp.get('networks', [])}")

                layout_desc = "\n".join(layout_lines)

                ref_block = (
                    f"━━━ REFERENCE EMAIL ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Name    : {ref_name}\n"
                    f"Subject : {ref_subj}\n"
                    f"Preview : {ref_prev}\n\n"
                    f"COMPONENT LAYOUT (replicate this exact sequence):\n"
                    f"{layout_desc}\n\n"
                    f"RICH TEXT HTML (actual HTML from each text block, in order):\n"
                    f"{ref_body_html}\n"
                )
                _log.info(
                    f"[GEN_EMAIL] reference loaded: {ref_name!r} "
                    f"components={len(ref_sections)} html={len(ref_body_html)} chars"
                )
            else:
                _log.warning(f"[GEN_EMAIL] reference fetch failed: {ref.get('error')}")
        except Exception as exc:
            _log.warning(f"[GEN_EMAIL] reference email exception: {exc}")

    # ── Fallback to official marketing stage template ──────────────────────────
    template_block = ""
    if not ref_block:
        from email_templates import get_template
        tmpl = get_template(stage_name) or get_template("Event Announcement")
        template_block = (
            f"━━━ STAGE TEMPLATE (use when no reference email is available) ━━━━━━━━━━━━\n"
            f"Subject   : {tmpl['subject']}\n"
            f"Preheader : {tmpl['preheader']}\n\n"
            f"Body:\n{tmpl['body']}\n"
        )
        _log.info(f"[GEN_EMAIL] using fallback template for stage={stage_name!r}")

    # ── Build the prompt ───────────────────────────────────────────────────────
    if ref_block:
        # Derive button color from reference (default teal if not found)
        ref_btn_color = "#04c0da"
        for comp in (ref.get("sections") or []):
            if comp.get("type") == "button" and comp.get("background_color"):
                ref_btn_color = comp["background_color"]
                break

        task_instructions = f"""\
━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You are given a COMPONENT LAYOUT and RICH TEXT HTML from a real previously sent
email. Build a new email for the event below that follows the same design exactly.

═══ COMPONENT-BY-COMPONENT RULES ═══════════════════════════════════════════════

For each component in the COMPONENT LAYOUT above, output the matching HTML:

▸ IMAGE (hero banner)
  — The system injects the hero banner automatically. Skip this in your output.

▸ RICH TEXT blocks
  — Copy the inline CSS from the reference HTML exactly (font-size, line-height,
    color, background-color, text-align, font-weight).
  — Keep the same heading style: if the reference uses <p> with inline bold+size,
    use <p>; if it uses <h2>, use <h2>. Do NOT switch tag types.
  — Keep emoji prefixes on section headings (💡 🎟️ 🤝 etc.) — pick appropriate
    emoji for each section based on the stage context.
  — Replace all event-specific text (name, date, location, URL, topics, speakers,
    sponsors) with the new event's details.
  — Keep body text font-size and color identical to the reference.

▸ BUTTON
  — For every CTA, output a SEPARATE button section object:
    {{"type": "button", "text": "REGISTER NOW >>", "url": "https://...", "color": "{ref_btn_color}"}}
  — Do NOT embed button HTML inside a rich_text section.
  — Button text must match the stage CTA: "{cta_label}"
  — If reference has multiple CTAs (one per section), output the same number of button sections.

▸ DIVIDER
  — Between major content sections, end the rich_text html with:
    <hr style="border:none;border-top:1px solid #000000;margin:20px 0;">

▸ IMAGE ROW (sponsor logos)
  — The system adds sponsor images automatically as native HubSpot image modules.
  — Do NOT include sponsor images or logos in any section.
  — Do NOT include sponsor names in the HTML sections either — the system handles them.
  — Do NOT include a "Thank You to Our Sponsors!" heading or any sponsor section header —
    the system injects this heading automatically before the sponsor logos.

▸ STRICT SECTION ORDER — output section objects in this exact sequence:
  1. Greeting / intro paragraph  (rich_text)
  2. Event highlights / main body  (rich_text)
  3. Speakers section if speakers available  (rich_text)
  4. Topics / tracks if available  (rich_text)
  5. CTA button  (button section)
  6. Additional CTAs if reference had multiple  (button sections)
  Sponsors are added by the system after your last section — do NOT output them.

▸ SOCIAL ICONS / FOOTER / BANNER
  — The system injects banner, footer, social icons automatically. Skip in your output.
  — Do NOT include: "This email was sent by", address, "Subscription Center", "Unsubscribe",
    "{{ unsubscribe_link }}", or any footer-related text — the system adds these.

═══ STAGE & CONTENT RULES ═══════════════════════════════════════════════════════
Stage: {stage_name} ({funnel})
Primary CTA: "{cta_label}"
- Tailor headlines, urgency wording, and section focus to match this stage.
- CFP stage → focus on speaking topics, deadline, submission link.
- Registration stage → focus on early bird pricing, date, venue.
- Announcement stage → focus on event overview, why attend, save the date.

{("MARKETING STRATEGY FOR THIS STAGE (use as messaging direction):\n  " + marketing_strategy) if marketing_strategy else ""}

{("CONTENT IDEAS FOR THIS STAGE (draw from these for section headlines & copy):\n" + chr(10).join(f"  • {idea}" for idea in content_ideas[:6])) if content_ideas else ""}

DESIGN RULE: Copy the EXACT design, layout, and component structure from the reference email
above. Only the copy/messaging/content changes — never the visual structure or styling.

Speaker list: include ALL confirmed speakers (never say "and more").
Sponsor list: include ALL sponsors (never say "and more" — but do NOT render them in sections).

HubSpot personalization tokens (exact syntax — spaces and dots matter):
  First name : {hs_firstname}
  Company    : {hs_company}

═══ OUTPUT FORMAT ════════════════════════════════════════════════════════════════
- Output sections in the JSON sections array — NOT as a single HTML block.
- Each rich_text "html" value: inline HTML paragraphs/lists only. No outer <div> wrapper.
  Use inline CSS (font-size, line-height, color, text-align, etc.) — no <style> tags.
- Each CTA button: a separate button section object — NOT embedded HTML in rich_text.
- Do NOT include: <html>, <head>, <body>, outer <div> wrapper, banner image,
  sponsor images/names, social icons, footer, or unsubscribe content.
- Bullet lists: <ul>/<li> tags — never the • character."""
    else:
        task_instructions = f"""\
━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Replace every placeholder ([Event Name], [City], [Dates], [LINK], etc.) with
the real event details above and produce an ordered sections array.

1. Stage: {stage_name} ({funnel}) — CTA: "{cta_label}"
{("   Marketing strategy: " + marketing_strategy) if marketing_strategy else ""}
{("   Content ideas (draw from these for section copy):" + chr(10) + chr(10).join("   • " + idea for idea in content_ideas[:5])) if content_ideas else ""}

2. Include ALL speakers listed (with names — do not say "and more").
3. Do NOT include sponsor images/names — the system adds them as native modules.

4. HubSpot personalization tokens (EXACT syntax):
   - First name : {hs_firstname}
   - Company    : {hs_company}

5. Output sections array — NOT a single HTML block:
   - rich_text sections: inline HTML only (no outer div wrapper, no style tags)
   - button sections: {{"type":"button","text":"...","url":"...","color":"#04c0da"}}
   - Do NOT include banner, sponsor images, footer, or unsubscribe content.
   Bullet lists as <ul>/<li>. Inline CSS only."""

    _stage_num_label = f"Stage {stage_info.get('stage_number')} — " if stage_info.get("stage_number") else ""
    prompt = f"""You are a senior email marketer for Linux Foundation open source events.

{ref_block or template_block}
━━━ NEW EVENT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Event Name  : {event_name}
Date        : {dates_display}
Location    : {location}
Event URL   : {url}
Description : {description}
Stage       : {_stage_num_label}{stage_name} ({funnel})

Confirmed Speakers:
{speakers_str}

Sponsors / Partners:
{sponsors_str}

Topics      : {topics_str}
{reg_info}

{task_instructions}

Return ONLY a JSON object — no markdown fences, no text before or after:
{{"subject": "...", "preview_text": "...", "sections": [...]}}

subject: email subject line (max 60 chars, matches {stage_name} urgency)
preview_text: preheader text (max 90 chars)
sections: ordered array of content blocks. The system automatically adds the hero
  banner image, sponsor images/names, social icons footer, and unsubscribe footer —
  do NOT include those.

  Each block must be one of:
    Rich text: {{"type": "rich_text", "html": "<p style='...'>...</p>"}}
    CTA button: {{"type": "button", "text": "REGISTER NOW >>", "url": "https://...", "color": "#46b6b3"}}

  CRITICAL:
    - Do NOT embed buttons as HTML in rich_text blocks — separate button objects only.
    - Do NOT include sponsor images, sponsor names, banner, footer, or social icons.
    - rich_text "html" must NOT have an outer <div> wrapper — just the inner content.
{("" if not change_request else f"{chr(10)}━━━ CHANGE REQUEST ━━━{chr(10)}{change_request}{chr(10)}")}"""

    raw = _claude_text(prompt, max_tokens=6000, timeout=240)

    # Strip markdown fences
    raw = _re.sub(r'^```(?:json)?\s*', '', raw.strip())
    raw = _re.sub(r'\s*```\s*$', '', raw)

    # Extract outermost JSON object
    depth, start = 0, -1
    for i, ch in enumerate(raw):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    data = json.loads(raw[start:i + 1])
                    sections_list = data.get("sections") or []
                    # Backwards compat: if Claude returned "html" instead of "sections"
                    if not sections_list and data.get("html"):
                        sections_list = [{"type": "rich_text", "html": str(data["html"])}]
                    body_html    = _sections_to_html(sections_list, ref_btn_color, sponsors)
                    preview_html = _build_email_preview(
                        banner_url, body_html, url, event_name
                    )
                    return {
                        "subject":      str(data.get("subject", "")),
                        "preview_text": str(data.get("preview_text", "")),
                        "html":         preview_html,   # full HTML for UI iframe
                        "body_html":    body_html,      # flat HTML fallback
                        "sections":     sections_list,  # structured sections for native modules
                        "sponsors":     sponsors,       # CDN-uploaded sponsors
                        "banner_url":   banner_url,     # uploaded HubSpot CDN URL (or "")
                    }
                except json.JSONDecodeError:
                    break

    raise ValueError(f"Claude did not return valid JSON. Raw[:400]: {raw[:400]}")


def ai_select_source_email(
    event_name: str,
    event_short_name: str,
    location: str,
    candidates: list,
    url: str = "",
    max_attempts: int = 5,
) -> dict | None:
    """
    Ask Claude to pick the best source email to clone from a pre-filtered candidate list.

    Candidates are already location-filtered by the caller (main.py) so Claude sees
    the most relevant emails first, with a fallback to all candidates when the
    filtered list is too small.

    Each attempt:
      1. Show Claude the email list + full event context (name, short name, location, URL).
      2. Claude follows a 3-tier priority rubric and replies structured:
           SELECT: <id>  /  CONFIDENT: YES or NO  /  REASON: ...
      3. CONFIDENT YES + valid ID → done.
      4. CONFIDENT NO or bad ID  → inject feedback and retry up to max_attempts.
    Returns None after all attempts (caller falls back to keyword scoring).
    """
    if not candidates:
        return None

    from datetime import datetime as _dt

    def _fmt_pub(ts) -> str:
        try:
            return _dt.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")
        except Exception:
            return str(ts)

    lines = [
        f"  ID: {e['id']}  |  {e.get('name', '(no name)')}  |  sent: {_fmt_pub(e.get('publishDate', 0))}"
        for e in candidates
    ]
    email_list = "\n".join(lines)
    url_line = f"Event URL  : {url}\n" if url else ""

    rejection_hint = ""

    for attempt in range(1, max_attempts + 1):
        prompt = (
            "You are a marketing operations specialist selecting the best HubSpot email\n"
            "template to clone for a new event campaign.\n\n"
            "━━━ NEW EVENT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Event Name : {event_name}\n"
            f"Short Name : {event_short_name}\n"
            f"Location   : {location}\n"
            f"{url_line}"
            "\n"
            "━━━ CANDIDATE EMAILS (sent emails for this brand, newest first) ━━━━━━━━━━━\n"
            f"{email_list}\n"
            "\n"
            f"{rejection_hint}"
            "━━━ SELECTION RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "PRIORITY 1 — EXACT MATCH (preferred):\n"
            f"  Same event series + same city/region → look for '{location.split(',')[0]}' in the name.\n"
            "\n"
            "PRIORITY 2 — SERIES MATCH:\n"
            f"  Same event series, any location → look for '{event_short_name}' or key words\n"
            f"  from '{event_name}' in the name.\n"
            "\n"
            "PRIORITY 3 — BRAND MATCH (last resort):\n"
            "  Same brand, most recently sent — only if no series match exists.\n"
            "\n"
            "CRITICAL RULES:\n"
            "  • NEVER pick an email from a different region when a location-specific\n"
            f"    email exists (e.g. do NOT pick 'North America' if '{location.split(',')[0]}' is available).\n"
            "  • Prefer the most recent edition of the matched series.\n"
            "  • A 'Last Chance' or 'Save the Date' email for the correct event is\n"
            "    better than an 'Invite' for the wrong location.\n"
            "  • Match on event series keywords: ignore generic words like 'summit',\n"
            "    'conference', 'register', 'join', 'meet'.\n"
            "\n"
            "━━━ YOUR ANSWER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Reply in EXACTLY this format (3 lines, nothing else):\n"
            "SELECT: <email_id>\n"
            "CONFIDENT: YES or NO\n"
            "REASON: <one sentence explaining priority tier used and why>"
        )

        try:
            raw = _claude_text(prompt, max_tokens=150)
        except Exception as exc:
            _log.warning(f"[AI SELECT] attempt {attempt}: Claude call failed: {exc}")
            continue

        _log.info(f"[AI SELECT] attempt {attempt} response: {raw!r}")

        sel_id, confident = None, False
        for line in raw.splitlines():
            ls = line.strip()
            if ls.upper().startswith("SELECT:"):
                sel_id = ls.split(":", 1)[1].strip().split()[0]
            if ls.upper().startswith("CONFIDENT:"):
                confident = "YES" in ls.upper()

        if not sel_id:
            _log.warning(f"[AI SELECT] attempt {attempt}: no SELECT: line found")
            rejection_hint = (
                "⚠️  Your previous response did not contain a SELECT: line.\n"
                "Follow the 3-line format exactly.\n\n"
            )
            continue

        matched = next((e for e in candidates if str(e.get("id")) == sel_id), None)
        if not matched:
            _log.warning(f"[AI SELECT] attempt {attempt}: ID {sel_id} not in candidate list")
            rejection_hint = (
                f"⚠️  ID {sel_id} does not appear in the candidate list above.\n"
                "Choose an ID exactly as shown.\n\n"
            )
            continue

        if confident:
            _log.info(f"[AI SELECT] ✓ attempt {attempt}: '{matched.get('name')}' (id={sel_id})")
            return matched

        _log.info(f"[AI SELECT] attempt {attempt}: not confident about '{matched.get('name')}', retrying")
        rejection_hint = (
            f"⚠️  Attempt {attempt}: you selected '{matched.get('name')}' but marked CONFIDENT: NO.\n"
            f"Re-examine the list focusing on '{location.split(',')[0]}' and '{event_short_name}'.\n\n"
        )

    _log.warning(f"[AI SELECT] all {max_attempts} attempts exhausted — returning None")
    return None


# ── Public interface — called by main.py ──────────────────────────────────────

def run_turn(messages: list, user_message: str) -> tuple[str, list]:
    """Route: LiteLLM/Anthropic SDK if any key available, else Claude Code CLI."""
    if _has_sdk_key():
        return _sdk_run_turn(messages, user_message)
    return _sdk_run_turn_cc(messages, user_message)


def plan_turn(session, url: str, extra_context: str = None) -> tuple[str, list]:
    prompt = (
        f"The user wants to stage an email for this event URL:\n{url}\n\n"
        "CRITICAL — follow this order STRICTLY:\n"
        "  STEP 1: Call fetch_url to extract event_name, brand_name, location, event_dates.\n"
        "  STEP 2: Call search_emails_for_event(brand_name, event_name, location).\n"
        "          If event_match=False, also call lookup_brand_history as fallback.\n"
        "  STEP 3: ONLY AFTER both tool calls above are done, write the full plan.\n\n"
        "⚠️  DO NOT write any plan content before completing STEP 1 and STEP 2.\n"
        "⚠️  DO NOT say 'the plan above', 'as shown above', or 'presented above'.\n"
        "⚠️  Your FINAL message must contain the COMPLETE plan written from scratch.\n\n"
        "Your final response MUST contain the full plan in this EXACT format "
        "(all four sections — Stage & Content Overview FIRST, then Settings, then Audience):\n\n"
        "---\n"
        "## Email Staging Plan — [Event Name]\n\n"
        "One sentence: what event, what type of email, which stage.\n\n"
        "### Stage & Content Overview\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        "| **Current Stage** | [stage name] ([funnel] — [N] days to event) |\n"
        "| **Stage Goal** | [what this email is trying to achieve] |\n"
        "| **Email Type** | [Invite / Last Chance / Reminder / Newsletter / etc.] |\n"
        "| **CTA** | [call-to-action label] |\n"
        "| **Event Date** | [event date] |\n"
        "| **Content Reference** | [name of previous email used as style reference, or 'Stage template'] |\n\n"
        "**What will be included in the generated email:**\n"
        "- **Speakers**: [list ALL confirmed speaker names, or 'To be announced']\n"
        "- **Sponsors / Partners**: [list ALL confirmed sponsor names, or 'None found']\n"
        "- **Topics / Tracks**: [list]\n"
        "- **Email Sections**: [intro paragraph → [stage-specific content] → speaker highlights → "
        "registration CTA → closing]\n\n"
        "### Settings\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        "| **Email Name** | `26QN - Brand - Event - Suffix` |\n"
        "| **From Name** | (from brand history) |\n"
        "| **From Address** | (from brand history) |\n"
        "| **Email Type** | (from brand history) |\n"
        "| **Subject Line** | *(auto-generated — shown below the plan)* |\n"
        "| **Preview Text** | *(auto-generated — shown below the plan)* |\n"
        "| **Send Date** | [REQUIRED — provide below] |\n\n"
        "### Audience\n\n"
        "| | |\n"
        "|---|---|\n"
        "| **Send List** | (list name and contact count from brand history) |\n"
        "| **Suppression Lists** | (all suppression list IDs/names from brand history) |\n\n"
        "---\n\n"
        "Then ask ONLY for Send Date (the only [REQUIRED] field).\n"
        "Do NOT ask for subject or preview text — those are auto-generated separately.\n"
        "Do NOT mention cloning, source emails, or templates anywhere.\n"
        "Do NOT say 'the plan above' or 'as shown above' — write everything in this single response."
    )
    if extra_context:
        prompt += f"\n\nAdditional context: {extra_context}"
    return run_turn(session.messages, prompt)


def clone_turn(session, subject=None, preview_text=None, send_list_id=None) -> tuple[str, list]:
    global _session_email_id
    _session_email_id = None

    brand = session.meta.get("brand_history") or extract_brand_history_from_messages(session.messages)

    # search_emails_for_event returns matched_email_id; lookup_brand_history returns last_email_id
    source_id = (brand or {}).get("last_email_id") or (brand or {}).get("matched_email_id")
    if not source_id:
        raise RuntimeError(
            "No source email found for cloning. Please re-run the plan step so the system "
            "can locate a previous email for this brand/event."
        )
    from_name   = brand.get("from_name", "")
    from_addr   = brand.get("from_address", "")
    suppression = brand.get("suppression_list_ids", [])
    email_type  = brand.get("email_type", "BATCH_EMAIL")

    email_name = session.meta.get("email_name") or f"{brand.get('brand_name', 'Brand')} - Email"

    _log.info(f"[CLONE] brand_history keys: {list((brand or {}).keys())}")
    _log.info(f"[CLONE] source_id={source_id!r} from_name={from_name!r} from_addr={from_addr!r}")
    _log.info(f"[CLONE] suppression={suppression!r}")
    _log.info(f"[CLONE] included_list_ids={brand.get('included_list_ids')!r}")

    # Fall back to auto-generated subject/preview from plan phase if user didn't provide them
    effective_subject      = subject      or session.meta.get("generated_subject", "")
    effective_preview_text = preview_text or session.meta.get("generated_preview", "")

    # Auto-detect send list — priority: user pick > built audience > brand history
    effective_send_list = send_list_id
    if not effective_send_list:
        audience_list_id = session.meta.get("audience_list_id")
        if audience_list_id:
            effective_send_list = str(audience_list_id)
            _log.info(f"[CLONE] using built audience list: {effective_send_list}")
    if not effective_send_list:
        included = (brand or {}).get("included_list_ids", [])
        if included:
            effective_send_list = str(included[0])

    _log.info(f"[CLONE] effective_send_list={effective_send_list!r} effective_subject={effective_subject[:40]!r}")

    # Step 1: Clone directly — bypass Claude to avoid hallucination in CLI mode
    clone_result = json.loads(
        _execute_tool("clone_email", {"source_email_id": source_id, "clone_name": email_name})
    )
    if "error" in clone_result:
        raise RuntimeError(f"Clone failed: {clone_result['error']}")

    new_email_id = clone_result["email_id"]
    draft_url    = clone_result.get("draft_url", "")

    # Step 2: Update settings directly (from/subject/preview_text — NOT the send list)
    # The send list is applied last via set_email_send_list() so content patches
    # can't accidentally interfere with the `to` field.
    settings: dict = {
        "email_id":             new_email_id,
        "from_name":            from_name,
        "from_address":         from_addr,
        "email_type":           email_type,
    }
    if effective_subject:      settings["subject"]       = effective_subject
    if effective_preview_text: settings["preview_text"]  = effective_preview_text

    update_result = json.loads(
        _execute_tool("update_email_settings", settings, session_email_id=new_email_id)
    )
    if "error" in update_result:
        _log.warning(f"Settings update partial error: {update_result['error']}")

    # Step 3: Auto-apply generated content if available from plan phase.
    # Prefer structured sections (native HubSpot modules) over flat body_html.
    content_applied    = False
    content_sections   = session.meta.get("sections") or []
    sponsors_list      = session.meta.get("sponsors") or []
    body_html          = session.meta.get("body_html") or session.meta.get("generated_html", "")
    banner_url         = session.meta.get("banner_url", "")
    event_url          = (session.meta.get("url_data") or {}).get("url", "")
    if content_sections or body_html:
        try:
            content_result = hubspot_tools.update_email_content(
                new_email_id,
                html_content=body_html if not content_sections else "",
                banner_url=banner_url,
                event_url=event_url,
                content_sections=content_sections or None,
                sponsors=sponsors_list or None,
            )
            if "error" not in content_result:
                content_applied = True
                _log.info(
                    f"[CLONE] Content applied method={content_result.get('method')!r} "
                    f"body={len(body_html):,} chars banner={'yes' if banner_url else 'no'}"
                )
            else:
                _log.warning(f"[CLONE] Content apply failed: {content_result.get('error')}")
        except Exception as e:
            _log.warning(f"[CLONE] Content apply exception: {e}")

    # Step 4: Validate the staged email content before surfacing the URL.
    # Re-fetch from HubSpot and verify widgets, footer, and body sections are present.
    # On failure, retry the content patch once before giving up.
    validation_passed = False
    validation_issues: list = []
    if content_applied:
        try:
            val = hubspot_tools.validate_staged_email(
                new_email_id,
                expect_banner=bool(banner_url),
                expect_sections=max(1, len([s for s in content_sections if s.get("type") == "rich_text"])) if content_sections else 1,
            )
            validation_passed = val.get("valid", False)
            validation_issues = val.get("issues", [])
            _log.info(f"[CLONE] validation={'PASS' if validation_passed else 'FAIL'} "
                      f"summary={val.get('summary')} issues={validation_issues}")

            if not validation_passed:
                # Retry content patch once
                _log.info("[CLONE] Retrying content patch after validation failure…")
                try:
                    retry_result = hubspot_tools.update_email_content(
                        new_email_id,
                        html_content=body_html if not content_sections else "",
                        banner_url=banner_url,
                        event_url=event_url,
                        content_sections=content_sections or None,
                        sponsors=sponsors_list or None,
                    )
                    if "error" not in retry_result:
                        val2 = hubspot_tools.validate_staged_email(
                            new_email_id,
                            expect_banner=bool(banner_url),
                            expect_sections=max(1, len([s for s in content_sections if s.get("type") == "rich_text"])) if content_sections else 1,
                        )
                        validation_passed = val2.get("valid", False)
                        validation_issues = val2.get("issues", [])
                        _log.info(f"[CLONE] retry validation={'PASS' if validation_passed else 'FAIL'} "
                                  f"issues={validation_issues}")
                    else:
                        _log.warning(f"[CLONE] Retry patch failed: {retry_result.get('error')}")
                except Exception as retry_exc:
                    _log.warning(f"[CLONE] Retry patch exception: {retry_exc}")
        except Exception as val_exc:
            _log.warning(f"[CLONE] Validation exception: {val_exc}")
            validation_passed = False
            validation_issues = [str(val_exc)]
    else:
        validation_issues = ["Content was not applied to the email"]

    # Step 5: Apply send list LAST — after all content patches so nothing can
    # overwrite the `to` field.  Uses set_email_send_list() which looks up the
    # list's processingType and uses the correct contactLists vs contactIlsLists
    # sub-field; mixing them in a single PATCH causes HubSpot to silently reject
    # the entire `to` object.
    if effective_send_list:
        try:
            sls = hubspot_tools.set_email_send_list(new_email_id, effective_send_list, suppression)
            _log.info(f"[CLONE] set_email_send_list → success={sls.get('success')} type={sls.get('list_type')}")
        except Exception as exc:
            _log.warning(f"[CLONE] set_email_send_list exception: {exc}")

    # Store flags so main.py can gate the draft URL
    session.meta["content_applied"]   = content_applied
    session.meta["validation_passed"]  = validation_passed
    session.meta["validation_issues"]  = validation_issues

    if validation_passed:
        text = (
            f"Email staged and validated successfully!\n\n"
            f"**Email Name:** {email_name}\n"
            f"**Subject:** {effective_subject}\n"
            f"**Preview Text:** {effective_preview_text}\n"
            f"**Draft URL:** {draft_url}\n\n"
            "All content sections, banner, and footer were confirmed in HubSpot. "
            "Review it and schedule when ready."
        )
    elif content_applied:
        issues_str = "\n".join(f"- {i}" for i in validation_issues)
        text = (
            f"Email was created but validation found issues:\n\n"
            f"**Email Name:** {email_name}\n\n"
            f"Issues detected:\n{issues_str}\n\n"
            "A retry was attempted. Please check the email in HubSpot and verify the content manually."
        )
    else:
        text = (
            f"Email staged successfully!\n\n"
            f"**Email Name:** {email_name}\n\n"
            "Please provide the email content (Google Doc URL, raw HTML, or plain text) "
            "and I'll update the email body."
        )

    updated_messages = session.messages + [
        {"role": "user",      "content": "I approve the plan."},
        {"role": "assistant", "content": text},
    ]
    return text, updated_messages


def content_turn(session, content_input: str) -> tuple[str, list]:
    prompt = (
        f"Content provided:\n\n{content_input}\n\n"
        "1. Call fetch_content to process it.\n"
        "2. Call update_email_content to update the body.\n"
        "3. Run QA and return final summary with draft URL."
    )
    return run_turn(session.messages, prompt)


def chat_turn(session, message: str) -> tuple[str, list]:
    return run_turn(session.messages, message)


def extract_brand_history_from_messages(messages: list) -> dict | None:
    """
    Scan plan-phase messages to find brand/event history for the clone phase.
    Checks both SDK-style tool_result blocks (Anthropic API mode) and
    __tool_log__ entries (Claude Code CLI mode).
    """
    def _check_block(block: dict) -> dict | None:
        if block.get("type") != "tool_result":
            return None
        try:
            data = json.loads(block.get("content", "{}"))
            has_id = data.get("matched_email_id") or data.get("last_email_id")
            if data.get("found") and has_id:
                # Normalise search_emails_for_event → same keys as lookup_brand_history
                if "matched_email_id" in data and "last_email_id" not in data:
                    data["last_email_id"]   = data["matched_email_id"]
                    data["last_email_name"] = data.get("matched_email_name", "")
                return data
        except Exception:
            pass
        return None

    for msg in messages:
        role    = msg.get("role", "")
        content = msg.get("content", [])

        # Claude Code CLI mode — tool results stored in __tool_log__ message
        if role == "__tool_log__" and isinstance(content, list):
            for block in content:
                result = _check_block(block)
                if result:
                    return result

        # Anthropic SDK mode — tool results in regular message content lists
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                result = _check_block(block)
                if result:
                    return result

    return None


def extract_email_id_from_messages(messages: list) -> str | None:
    for msg in reversed(messages):
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                try:
                    data = json.loads(block.get("content", "{}"))
                    if "email_id" in data:
                        return data["email_id"]
                except Exception:
                    pass
    return None
