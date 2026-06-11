"""
Claude agentic loop.

Two modes — same interface, same tools:
  • Anthropic SDK mode  (ANTHROPIC_API_KEY set)   → structured tool_use via API
  • Claude Code mode    (no key)                  → tool-use loop via `claude -p` CLI subprocess

Claude decides which HubSpot APIs to call in both modes.
"""
import json
import os
import subprocess
import asyncio
import nest_asyncio
nest_asyncio.apply()  # allows asyncio.run() inside FastAPI's event loop
from datetime import datetime
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
import hubspot_tools
import content_tools

import shutil

# Find the claude CLI — explicit Windows path as fallback
def _find_claude_cli() -> str:
    if found := shutil.which("claude"):
        return found
    fallback = r"C:\Users\VinayU\AppData\Roaming\npm\claude.cmd"
    if os.path.exists(fallback):
        return fallback
    raise RuntimeError("claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code")

CLAUDE_CLI = os.getenv("CLAUDE_CLI_PATH") or _find_claude_cli()

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
            result = content_tools.fetch_url(inputs["url"])
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
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
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
            [CLAUDE_CLI, "--print", "--dangerously-skip-permissions"],
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
            raise RuntimeError(f"Claude CLI error: {stderr_b.decode('utf-8', errors='replace').strip()}")
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
    if ANTHROPIC_API_KEY:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
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
            [CLAUDE_CLI, "--print", "--dangerously-skip-permissions"],
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
            raise RuntimeError(f"Claude CLI: {stderr_b.decode('utf-8', errors='replace').strip()}")
        return stdout_b.decode("utf-8", errors="replace").strip()


def generate_email_content(
    event_details: dict,
    stage_info: dict,
    brand_history: dict | None,
    change_request: str = "",
) -> dict:  # noqa: C901
    """
    Generate subject, preview text, and full HTML email body.

    Uses the official LF Events Marketing Journey stage templates as the base,
    then asks Claude to substitute real event details and render as HTML.
    Returns: {subject, preview_text, html}
    """
    import re as _re
    from email_templates import get_template

    event_name    = event_details.get("event_name", "")
    event_dates   = event_details.get("event_dates", [])
    location      = event_details.get("location", "")
    description   = (event_details.get("description") or "")[:400]
    url           = event_details.get("url", "")
    hero_img      = event_details.get("hero_image_url", "")
    speakers      = event_details.get("speakers", [])
    topics        = event_details.get("topics", [])
    reg           = event_details.get("registration") or {}

    stage_name    = stage_info.get("name", "")
    funnel        = stage_info.get("funnel", "")
    cta_label     = stage_info.get("cta_label", "Register Now")
    event_date    = stage_info.get("event_date_str", "") or (event_dates[0] if event_dates else "")
    from_name     = (brand_history or {}).get("from_name") or "Linux Foundation Events"
    dates_display = event_dates[0] if event_dates else event_date

    # Get the official stage template from the Marketing Journey dashboard
    tmpl = get_template(stage_name) or get_template("Event Announcement")
    template_subject  = tmpl["subject"]
    template_preheader = tmpl["preheader"]
    template_body     = tmpl["body"]

    # Build supplementary context
    reg_lines = []
    if reg.get("ticket_types"):
        reg_lines.append(f"Ticket info: {'; '.join(reg['ticket_types'][:2])}")
    if reg.get("deadlines"):
        reg_lines.append(f"Deadline: {reg['deadlines'][0]}")
    if reg.get("url"):
        reg_lines.append(f"Register at: {reg['url']}")
    reg_info = "\n".join(reg_lines)

    speakers_str = ", ".join(speakers[:3]) if speakers else ""
    topics_str   = ", ".join(topics[:4])   if topics   else "Open Source, Cloud Native, Linux"

    hero_tag = (
        f'<img src="{hero_img}" width="600" alt="{event_name}" '
        'style="display:block;width:100%;max-width:600px;height:auto">'
        if hero_img
        else '<div style="background:#0099CC;height:10px;width:100%"></div>'
    )

    prompt = f"""You are a senior email marketer for Linux Foundation open source events.

Your job: take the official stage template below and personalise it for a specific event,
then render it as a production-ready HTML email.

━━━ EVENT DETAILS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Event Name  : {event_name}
Date        : {dates_display}
Location    : {location}
Event URL   : {url}
Description : {description}
Speakers    : {speakers_str or "To be announced"}
Topics      : {topics_str}
{reg_info}

━━━ CAMPAIGN STAGE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stage  : {stage_name} ({funnel})
CTA    : {cta_label}

━━━ OFFICIAL TEMPLATE (substitute [Event Name], [City], [Dates], [Date] etc.) ━━━
Subject   : {template_subject}
Preheader : {template_preheader}

Body:
{template_body}

━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Replace every placeholder ([Event Name], [City], [Dates], [Date], [LINK], etc.)
   with the real event details provided above.
2. Keep {{{{first_name}}}}, {{{{company_name}}}} and similar HubSpot tokens as-is.
3. Remove any sections that don't apply (e.g. co-located events if none listed).
4. Render everything as a complete HTML email with:
   - DOCTYPE, <html>, <head>, <body>
   - Table-based layout, max-width 600px, centered, inline CSS only
   - Header: {hero_tag}
   - Body text in Arial, #333333, line-height 1.6
   - CTA button: background #0099CC, white text, border-radius 4px, links to {url}
   - Footer: "Linux Foundation Events" + <a href="{{{{unsubscribe_url}}}}">Unsubscribe</a>
   - Colors: headers #003366, accents/buttons #0099CC

Return ONLY a JSON object — no markdown fences, nothing before or after:
{{"subject": "...", "preview_text": "...", "html": "..."}}

subject: personalised version of the template subject (max 60 chars)
preview_text: personalised version of the template preheader (max 90 chars)
html: the complete rendered HTML email
{("" if not change_request else f"{chr(10)}━━━ CHANGE REQUEST (apply this on top of everything above) ━━━{chr(10)}{change_request}{chr(10)}")}"""

    raw = _claude_text(prompt, max_tokens=4000, timeout=180)

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
                    return {
                        "subject":      str(data.get("subject", "")),
                        "preview_text": str(data.get("preview_text", "")),
                        "html":         str(data.get("html", "")),
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
    """Route: Anthropic SDK if key available, else Claude Code SDK."""
    if ANTHROPIC_API_KEY:
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
        "Your final response MUST contain the full plan in this exact format:\n\n"
        "---\n"
        "## Email Staging Plan — [Event Name]\n\n"
        "Brief 1-2 sentence summary of what will be staged.\n\n"
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

    # Auto-detect send list from brand history if user didn't pick one
    effective_send_list = send_list_id
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

    # Step 2: Update settings directly
    settings: dict = {
        "email_id":             new_email_id,
        "from_name":            from_name,
        "from_address":         from_addr,
        "suppression_list_ids": suppression,
        "email_type":           email_type,
    }
    if effective_subject:      settings["subject"]       = effective_subject
    if effective_preview_text: settings["preview_text"]  = effective_preview_text
    if effective_send_list:    settings["send_list_id"]  = effective_send_list

    update_result = json.loads(
        _execute_tool("update_email_settings", settings, session_email_id=new_email_id)
    )
    if "error" in update_result:
        _log.warning(f"Settings update partial error: {update_result['error']}")

    # Step 3: Auto-apply generated HTML content if available from plan phase
    content_applied = False
    generated_html = session.meta.get("generated_html", "")
    if generated_html:
        try:
            content_result = hubspot_tools.update_email_content(
                new_email_id, generated_html
            )
            if "error" not in content_result:
                content_applied = True
                _log.info(f"[CLONE] Auto-applied HTML ({len(generated_html):,} chars) method={content_result.get('method')!r}")
            else:
                _log.warning(f"[CLONE] Content apply failed: {content_result.get('error')}")
        except Exception as e:
            _log.warning(f"[CLONE] Content apply exception: {e}")

    # Store flag so main.py can include it in the response
    session.meta["content_applied"] = content_applied

    if content_applied:
        text = (
            f"Email staged successfully with AI-generated content!\n\n"
            f"**Email Name:** {email_name}\n"
            f"**Subject:** {effective_subject}\n"
            f"**Preview Text:** {effective_preview_text}\n"
            f"**Draft URL:** {draft_url}\n\n"
            "The email body has been populated with AI-generated content. "
            "Review it in HubSpot and make any edits before scheduling."
        )
    else:
        text = (
            f"Email staged successfully!\n\n"
            f"**Email Name:** {email_name}\n"
            f"**Draft URL:** {draft_url}\n\n"
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
