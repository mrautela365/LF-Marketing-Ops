"""
Multi-stage Asana task briefing.

The Asana tasks this service processes follow a fixed 6-subtask pipeline, each
owned by a different assignee with its own due date:

    Content -> Provide List -> Staging -> Approval -> Launch -> Campaign Update

Content and Provide List are owned upstream (by whoever writes the copy and
pulls the send list) and require NO action from this service - it only reads
their comments once both are marked complete. Everything from Staging onward
is this service's job.
"""
import os
import re
import sys
import json
import html as html_lib
import asyncio
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emailcreationskill', 'backend'))

import asana_tools
import llm_gateway
from config import ASANA_ACCESS_TOKEN

log = logging.getLogger("survey-workflow.stage-brief")

STAGE_ORDER = ["Content", "Provide List", "Staging", "Approval", "Launch", "Campaign Update"]

# Subtasks in these two stages are owned upstream - the service only reads them.
NO_ACTION_STAGES = {"Content", "Provide List"}

_STAGE_KEYWORDS = [
    ("Content", ("content",)),
    ("Provide List", ("provide list", "list pull", "audience list")),
    ("Staging", ("staging", "stage")),
    ("Approval", ("approval", "approve")),
    ("Launch", ("launch", "send")),
    ("Campaign Update", ("campaign update",)),
]


def _match_stage(name: str) -> str:
    n = (name or "").lower()
    for canon, keywords in _STAGE_KEYWORDS:
        if any(kw in n for kw in keywords):
            return canon
    return ""


def extract_hubspot_list_id(url: str) -> str:
    m = re.search(r"objectLists/(\d+)", url or "")
    return m.group(1) if m else ""


def extract_hubspot_workflow_flow_id(url: str) -> str:
    m = re.search(r"/flow/(\d+)", url or "")
    return m.group(1) if m else ""


# ── Fetch ──────────────────────────────────────────────────────────────────

def fetch_task_data(asana_url: str) -> dict:
    """
    Fetch the parent task + all subtasks with completed/assignee/due_on/comments.
    Uses the REST API when ASANA_ACCESS_TOKEN is configured, otherwise falls back
    to the Asana MCP connector via a Claude Code subprocess.
    """
    if ASANA_ACCESS_TOKEN:
        log.info("Fetching task via Asana REST API...")
        return _fetch_via_rest(asana_url)
    log.info("No ASANA_ACCESS_TOKEN configured - fetching via Asana MCP connector...")
    return _fetch_via_mcp(asana_url)


def _fetch_via_rest(asana_url: str) -> dict:
    gid = asana_tools.parse_task_gid(asana_url)
    log.info(f"Reading parent task {gid}...")
    task = asana_tools.get_task_full(gid)
    log.info(f"Task: {task.get('name', gid)!r} - listing subtasks...")
    subtasks = asana_tools.get_subtasks_full(gid)
    log.info(f"Found {len(subtasks)} subtask(s) - reading comments for each...")

    result_subtasks = []
    for st in subtasks:
        log.info(f"Reading comments: {st.get('name', st.get('gid',''))!r}...")
        stories = asana_tools.get_stories(st.get("gid", ""))
        log.info(f"  -> {len(stories)} comment(s) found on {st.get('name','')!r}")
        result_subtasks.append({
            "name": st.get("name", ""),
            "gid": st.get("gid", ""),
            "completed": bool(st.get("completed", False)),
            "assignee": (st.get("assignee") or {}).get("name", ""),
            "due_on": st.get("due_on", "") or "",
            "notes": st.get("notes", "") or "",
            "comments": [s.get("text", "") for s in stories],
        })

    return {
        "task_name": task.get("name", ""),
        "task_gid": gid,
        "task_completed": bool(task.get("completed", False)),
        "task_due_on": task.get("due_on", "") or "",
        "subtasks": result_subtasks,
    }


_MCP_PROMPT = """Use the Asana MCP tools to fetch FULL task data and return it as JSON.
Asana task URL: {url}

Steps:
1. Extract the task GID from the URL (the numeric ID after /task/).
2. Call get_task for that GID with fields: name, notes, due_on, completed, assignee.
3. List ALL subtasks of this task with fields: name, notes, completed, assignee, due_on, gid.
4. For EACH subtask, fetch its comments/stories (the task's comment thread, NOT just its notes field).

Return ONLY this JSON (no markdown fences, no explanation, raw JSON only):
{{
  "task_name": "...", "task_gid": "...", "task_completed": true/false, "task_due_on": "...",
  "subtasks": [
    {{"name": "...", "gid": "...", "completed": true/false, "assignee": "...",
      "due_on": "...", "notes": "...", "comments": ["...", ...]}}
  ]
}}"""


def _fetch_via_mcp(asana_url: str) -> dict:
    prompt = _MCP_PROMPT.format(url=asana_url)
    log.info("Asking Claude (Asana MCP connector) to read the task + all subtask comments...")
    raw, success = llm_gateway.run_cli_skill(prompt, timeout=180)
    if not success:
        raise RuntimeError(f"Asana MCP fetch failed: {raw[:500]}")
    log.info("Asana MCP fetch complete - parsing task data...")

    text = raw.strip()
    # Strip markdown code fences if the model added them despite instructions.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*$", "", text)

    # The model may prepend/append prose - find the outermost JSON object.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError(f"Asana MCP fetch returned no JSON:\n{raw[:1000]}")

    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Asana MCP fetch returned malformed JSON: {e}\n{text[:1000]}")


async def fetch_task_data_async(asana_url: str) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fetch_task_data, asana_url)


# ── Brief ──────────────────────────────────────────────────────────────────

def build_brief(raw: dict, overrides: dict = None) -> dict:
    """
    Normalize raw task+subtask data into a stage-by-stage brief:
    which stage we're at, whether we're gated on upstream work, and the
    content doc / send list links pulled from comments.

    `overrides` is an optional {stage_name: bool} map used ONLY for local
    testing - it force-sets a stage's `completed` flag without touching
    Asana, so gating logic can be exercised without editing the real task.
    """
    overrides = overrides or {}
    subtasks = raw.get("subtasks", [])
    stage_map = {}
    for st in subtasks:
        canon = _match_stage(st.get("name", ""))
        if canon and canon not in stage_map:
            stage_map[canon] = st

    stages = []
    current_stage = None
    for canon in STAGE_ORDER:
        st = stage_map.get(canon, {})
        real_completed = bool(st.get("completed", False))
        completed = bool(overrides[canon]) if canon in overrides else real_completed
        entry = {
            "name": canon,
            "found": canon in stage_map,
            "assignee": st.get("assignee", ""),
            "completed": completed,
            "real_completed": real_completed,
            "overridden": canon in overrides,
            "due_on": st.get("due_on", ""),
            "no_action_required": canon in NO_ACTION_STAGES,
            "notes": st.get("notes", ""),
            "comments": st.get("comments", []),
        }
        stages.append(entry)
        if not entry["completed"] and current_stage is None:
            current_stage = canon

    if current_stage is None:
        current_stage = "Done" if stages else "Unknown"

    stage_by_name = {s["name"]: s for s in stages}
    content_done = stage_by_name["Content"]["completed"]
    list_done = stage_by_name["Provide List"]["completed"]
    staging_done = stage_by_name["Staging"]["completed"]

    return {
        "task_name": raw.get("task_name", ""),
        "task_gid": raw.get("task_gid", ""),
        "stages": stages,
        "current_stage": current_stage,
        "content_done": content_done,
        "list_done": list_done,
        "ready_to_build": content_done and list_done,
        "staging_done": staging_done,
        # Filled in by analyze_stages() - an AI decision, not a regex guess.
        "staging_email_links": [],
        "content_doc_url": "",
        "content_doc_description": "",
        "hubspot_list_url": "",
        "hubspot_list_description": "",
        "hubspot_list_id": "",
        "hubspot_workflow_url": "",
        "hubspot_workflow_description": "",
        "hubspot_workflow_flow_id": "",
    }


# ── AI stage analysis ────────────────────────────────────────────────────────
#
# Every decision here mirrors agent.ai_select_source_email's pattern: a confident/
# retry loop with every attempt logged via `log.info` so the reasoning is visible
# in real time, not a silent regex guess. Nothing about link detection, what's
# "done" in a stage, or how many drafts a doc contains is hard-coded - the model
# decides, and re-tries itself when it isn't confident.

_STAGE_ANALYSIS_SYSTEM = (
    "You are a marketing-ops analyst reviewing ONE stage of an email campaign's Asana "
    "task pipeline. Base every statement ONLY on the notes/comments given - never invent "
    "names, dates, or links. Return ONLY raw JSON, no markdown fences, no commentary."
)

_STAGE_ANALYSIS_PROMPT = """Stage: {stage_name}
Assignee: {assignee}
Due: {due_on}
Completed (per Asana): {completed}
Notes: {notes}
Comments:
{comment_block}

{rejection_hint}Read the comment thread carefully and decide:

1. A detailed 2-4 sentence description of what has ACTUALLY happened in this stage -
   what's done, what's still outstanding, any blockers, decisions, or context mentioned.
   Go as detailed as the comments allow - do not just say "no comments" if there IS
   discussion; pull out the substance.
2. Every link mentioned in the comments (Google Doc, HubSpot send list, HubSpot email
   edit/preview links, HubSpot workflow/automation links, or anything else). For EACH
   link, give the exact URL, its type, and a one-sentence description of what it is /
   why it's there, grounded in the surrounding comment text. NEVER return a link with
   an empty or generic description.

Reply with ONLY this JSON (no markdown fences):
{{
  "description": "...",
  "links": [
    {{"url": "...", "type": "google_doc|hubspot_list|hubspot_email|hubspot_workflow|other", "description": "..."}}
  ],
  "confident": true/false
}}

Set "confident" to false only if the comments are too ambiguous to describe reliably."""


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*$", "", text)
    return text


def _parse_json_object(text: str):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _ai_analyze_stage(stage: dict, max_attempts: int = 3) -> dict:
    """
    Confidence-retry AI analysis of one stage's comment thread. Returns
    {"description": str, "links": [{"url","type","description"}], "confident": bool}.
    Falls back to an honest "couldn't analyze" result only after every attempt fails.
    """
    name = stage["name"]
    comments = stage.get("comments") or []
    comment_block = "\n".join(f"  - {c}" for c in comments) if comments else "  (no comments)"
    rejection_hint = ""

    for attempt in range(1, max_attempts + 1):
        prompt = _STAGE_ANALYSIS_PROMPT.format(
            stage_name=name,
            assignee=stage.get("assignee") or "unassigned",
            due_on=stage.get("due_on") or "none",
            completed=stage.get("completed", False),
            notes=stage.get("notes") or "(none)",
            comment_block=comment_block,
            rejection_hint=rejection_hint,
        )

        log.info(f"[AI STAGE] {name} attempt {attempt}: analyzing {len(comments)} comment(s)...")
        try:
            raw = llm_gateway.complete_text(prompt, system=_STAGE_ANALYSIS_SYSTEM, max_tokens=600, timeout=60)
        except Exception as e:
            log.warning(f"[AI STAGE] {name} attempt {attempt}: call failed: {e}")
            rejection_hint = ""
            continue

        parsed = _parse_json_object(_strip_json(raw))
        if parsed is None:
            log.warning(f"[AI STAGE] {name} attempt {attempt}: no valid JSON in response")
            rejection_hint = "Your previous reply had no valid JSON. Reply with ONLY the JSON object.\n\n"
            continue

        if not parsed.get("description"):
            log.warning(f"[AI STAGE] {name} attempt {attempt}: empty description")
            rejection_hint = "You must include a non-empty 'description'. Retry.\n\n"
            continue

        bad_link = next((l for l in parsed.get("links", []) if not l.get("description")), None)
        if bad_link:
            log.warning(f"[AI STAGE] {name} attempt {attempt}: link with no description ({bad_link.get('url')})")
            rejection_hint = "Every link needs a non-empty 'description'. Retry.\n\n"
            continue

        if not parsed.get("confident", True):
            log.info(f"[AI STAGE] {name} attempt {attempt}: not confident, retrying")
            rejection_hint = "Re-read the comments more carefully and try again.\n\n"
            continue

        log.info(f"[AI STAGE] {name}: {parsed['description']}")
        for l in parsed.get("links", []):
            log.info(f"[AI STAGE] {name}  -> found {l.get('type', 'link')}: {l.get('description', '')}")
        return parsed

    log.warning(f"[AI STAGE] {name}: all {max_attempts} attempts exhausted - using best-effort fallback")
    return {"description": "Could not reliably analyze this stage's comments.", "links": [], "confident": False}


_OVERALL_SYSTEM = (
    "You summarize the overall status of a marketing email campaign's Asana task pipeline. "
    "Base every statement only on the per-stage descriptions given - never invent anything. "
    "Return ONLY raw JSON, no markdown fences, no commentary."
)

_OVERALL_PROMPT_TMPL = """Task: {task_name}

Here is each stage of this task's pipeline with its completion status and AI-analyzed description:

{stage_blocks}

Give one 2-4 sentence overall summary of where the whole task stands: what's complete,
what's next, and any blockers.

Reply with ONLY this JSON (no markdown fences):
{{"overall_summary": "..."}}"""


def _ai_overall_summary(brief: dict, max_attempts: int = 3) -> str:
    stage_blocks = "\n".join(
        f"- {s['name']} (completed: {s['completed']}): {s.get('summary', '')}"
        for s in brief["stages"]
    )
    rejection_hint = ""
    for attempt in range(1, max_attempts + 1):
        prompt = _OVERALL_PROMPT_TMPL.format(task_name=brief.get("task_name", ""), stage_blocks=stage_blocks)
        if rejection_hint:
            prompt += f"\n\n{rejection_hint}"

        log.info(f"[AI OVERALL] attempt {attempt}: synthesizing overall status...")
        try:
            raw = llm_gateway.complete_text(prompt, system=_OVERALL_SYSTEM, max_tokens=400, timeout=45)
        except Exception as e:
            log.warning(f"[AI OVERALL] attempt {attempt}: call failed: {e}")
            continue

        parsed = _parse_json_object(_strip_json(raw))
        if parsed is None or not parsed.get("overall_summary"):
            log.warning(f"[AI OVERALL] attempt {attempt}: no valid summary in response")
            rejection_hint = "Reply with ONLY the JSON object, with a non-empty 'overall_summary'."
            continue

        log.info(f"[AI OVERALL] {parsed['overall_summary']}")
        return parsed["overall_summary"]

    log.warning(f"[AI OVERALL] all {max_attempts} attempts exhausted - no overall summary")
    return ""


def analyze_stages(brief: dict) -> dict:
    """
    AI-driven analysis of every stage (replaces regex link-scraping entirely):
    each stage's comment thread is read by the model, which decides the
    description and every doc/list/email link (with a real description, never
    a bare URL). Then one final AI call synthesizes the overall status.
    """
    for stage in brief["stages"]:
        result = _ai_analyze_stage(stage)
        stage["summary"] = result["description"]
        stage["ai_links"] = result.get("links", [])

    stage_by_name = {s["name"]: s for s in brief["stages"]}

    def _first_link(stage_name: str, link_type: str) -> dict:
        for l in stage_by_name[stage_name]["ai_links"]:
            if l.get("type") == link_type:
                return l
        return {}

    content_link = _first_link("Content", "google_doc")
    list_link = _first_link("Provide List", "hubspot_list")
    staging_links = [l for l in stage_by_name["Staging"]["ai_links"] if l.get("type") == "hubspot_email"]

    workflow_link = {}
    for stage_name in ("Launch", "Approval", "Staging", "Campaign Update"):
        workflow_link = _first_link(stage_name, "hubspot_workflow")
        if workflow_link:
            break

    brief["content_doc_url"] = content_link.get("url", "")
    brief["content_doc_description"] = content_link.get("description", "")
    brief["hubspot_list_url"] = list_link.get("url", "")
    brief["hubspot_list_description"] = list_link.get("description", "")
    brief["hubspot_list_id"] = extract_hubspot_list_id(list_link.get("url", ""))
    brief["staging_email_links"] = staging_links
    brief["hubspot_workflow_url"] = workflow_link.get("url", "")
    brief["hubspot_workflow_description"] = workflow_link.get("description", "")
    brief["hubspot_workflow_flow_id"] = extract_hubspot_workflow_flow_id(workflow_link.get("url", ""))

    brief["overall_summary"] = _ai_overall_summary(brief)
    log.info("AI stage analysis complete.")
    return brief


# ── Draft-count detection ───────────────────────────────────────────────────

_DRAFT_SPLIT_SYSTEM = (
    "You are a marketing-ops analyst reading a content doc for an email campaign. Base "
    "every statement only on the doc content given - never invent anything. Return ONLY "
    "raw JSON, no markdown fences, no commentary."
)

_DRAFT_SPLIT_PROMPT = """Content doc (as extracted from the source doc):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{doc_content}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{rejection_hint}Decide how many separate draft emails this doc actually specifies (often 1, but
can be 3 if the doc has clearly separate sections like "Email 1"/"Draft 2"/"Version 3",
or distinct subject lines per email). For EACH draft, give:
  - "heading": the EXACT text (a verbatim substring of the doc above) marking where this
    draft begins - the heading/subject line itself. For a single-draft doc, use the very
    first line of the doc.
  - "description": a 1-2 sentence description of that draft's subject/theme/CTA.

Reply with ONLY this JSON (no markdown fences):
{{
  "draft_count": N,
  "drafts": [{{"heading": "...", "description": "..."}}],
  "confident": true/false
}}"""


def ai_split_drafts(doc_content: str, max_attempts: int = 3) -> list:
    """
    AI decides how many draft emails a content doc specifies and describes each
    one - mirrors agent.ai_select_source_email's confidence-retry pattern. The
    text segments are then sliced mechanically at the exact heading text the
    model identified, so the built email content is never paraphrased by the
    model - only the *decision* of where the drafts split is AI-driven.
    """
    rejection_hint = ""
    for attempt in range(1, max_attempts + 1):
        prompt = _DRAFT_SPLIT_PROMPT.format(doc_content=doc_content, rejection_hint=rejection_hint)
        log.info(f"[AI DRAFTS] attempt {attempt}: reading content doc ({len(doc_content or '')} chars)...")
        try:
            raw = llm_gateway.complete_text(prompt, system=_DRAFT_SPLIT_SYSTEM, max_tokens=700, timeout=60)
        except Exception as e:
            log.warning(f"[AI DRAFTS] attempt {attempt}: call failed: {e}")
            rejection_hint = ""
            continue

        parsed = _parse_json_object(_strip_json(raw))
        if parsed is None or not parsed.get("drafts"):
            log.warning(f"[AI DRAFTS] attempt {attempt}: no valid JSON/drafts in response")
            rejection_hint = "Reply with ONLY the JSON object, with a non-empty 'drafts' list.\n\n"
            continue

        drafts = parsed["drafts"]
        positions, ok = [], True
        for d in drafts:
            pos = doc_content.find(d.get("heading", "")) if d.get("heading") else -1
            if pos == -1:
                ok = False
                break
            positions.append(pos)

        if not ok or not parsed.get("confident", True):
            reason = "a heading it gave doesn't appear verbatim in the doc" if not ok else "not confident"
            log.info(f"[AI DRAFTS] attempt {attempt}: retrying ({reason})")
            rejection_hint = (
                "Your previous 'heading' values must be EXACT substrings copied from the doc "
                "above, and you must be confident. Retry.\n\n"
            )
            continue

        order = sorted(range(len(drafts)), key=lambda i: positions[i])
        segments = []
        for rank, i in enumerate(order):
            start = positions[i]
            end = positions[order[rank + 1]] if rank + 1 < len(order) else len(doc_content)
            segments.append({
                "heading": drafts[i].get("heading", ""),
                "description": drafts[i].get("description", ""),
                "content": doc_content[start:end].strip(),
            })

        log.info(f"[AI DRAFTS] found {len(segments)} draft(s):")
        for s in segments:
            log.info(f"[AI DRAFTS]  -> {s['heading'][:60]!r}: {s['description']}")
        return segments

    log.warning(f"[AI DRAFTS] all {max_attempts} attempts exhausted - treating doc as a single draft")
    return [{
        "heading": "",
        "description": "Could not reliably split this doc - treating it as one draft.",
        "content": doc_content,
    }]


# ── Send-date extraction (for workflow delay steps) ─────────────────────────

_SEND_DATES_SYSTEM = (
    "You are a marketing-ops analyst reading a content doc for an email campaign. Base "
    "every statement only on the doc content given - never invent or guess a date that "
    "isn't written there. Return ONLY raw JSON, no markdown fences, no commentary."
)

_SEND_DATES_PROMPT = """Content doc (as extracted from the source doc):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{doc_content}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{rejection_hint}This doc specifies {num_dates} email send(s), in order. Find the intended SEND DATE
explicitly written in the doc for each one, in the same order as the emails appear
(e.g. "Send 1: June 12, 2026", "Reminder email - send July 14", a table of send dates,
etc). Only use dates that are actually written in the doc - if the doc gives a year,
use it; if it doesn't, infer the year from any other dated context in the doc.

Reply with ONLY this JSON (no markdown fences):
{{"dates": ["YYYY-MM-DD", ...], "confident": true/false}}

"dates" must have EXACTLY {num_dates} entries, in the same order as the emails.
Set "confident" to false if you cannot find {num_dates} explicit dates in the doc."""


def ai_extract_send_dates(doc_content: str, num_dates: int, max_attempts: int = 3) -> list:
    """
    AI-driven extraction of the explicit send date(s) mentioned in a content doc,
    one per draft email, in order - mirrors ai_split_drafts's confidence-retry
    pattern. Returns a list of 'YYYY-MM-DD' strings of length `num_dates`, or []
    if no reliable dates could be found after `max_attempts` tries.
    """
    if num_dates <= 0:
        return []

    rejection_hint = ""
    for attempt in range(1, max_attempts + 1):
        prompt = _SEND_DATES_PROMPT.format(
            doc_content=doc_content, num_dates=num_dates, rejection_hint=rejection_hint,
        )
        log.info(f"[AI SEND DATES] attempt {attempt}: looking for {num_dates} send date(s) in doc...")
        try:
            raw = llm_gateway.complete_text(prompt, system=_SEND_DATES_SYSTEM, max_tokens=300, timeout=60)
        except Exception as e:
            log.warning(f"[AI SEND DATES] attempt {attempt}: call failed: {e}")
            rejection_hint = ""
            continue

        parsed = _parse_json_object(_strip_json(raw))
        dates = parsed.get("dates") if parsed else None
        valid = bool(dates) and len(dates) == num_dates and all(
            re.match(r"^\d{4}-\d{2}-\d{2}$", d or "") for d in dates
        )
        if not valid:
            log.warning(f"[AI SEND DATES] attempt {attempt}: invalid/wrong-count dates in response")
            rejection_hint = (
                f"'dates' must be EXACTLY {num_dates} strings in YYYY-MM-DD format, "
                "each one actually written in the doc. Retry.\n\n"
            )
            continue

        if not parsed.get("confident", True):
            log.info(f"[AI SEND DATES] attempt {attempt}: not confident, retrying")
            rejection_hint = "Re-read the doc more carefully for explicit send dates and try again.\n\n"
            continue

        log.info(f"[AI SEND DATES] found send dates: {dates}")
        return dates

    log.warning(f"[AI SEND DATES] all {max_attempts} attempts exhausted - no reliable send dates found")
    return []


# ── Polish manually-pasted content (fallback for when the doc fetch fails) ──

_POLISH_SYSTEM = (
    "You are an email copy editor turning rough pasted text into clean, well-structured "
    "HTML for a marketing email body. Never invent facts, claims, or URLs that aren't "
    "given to you. Return ONLY raw JSON, no markdown fences, no commentary."
)

_POLISH_PROMPT = """Raw pasted content:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{raw_content}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Links to place (each has an id, the anchor text/description of where it belongs, and
whether it should be an inline text link or a standalone call-to-action button):
{link_block}

{rejection_hint}Rewrite the raw content above into clean email-ready HTML:
- Use <p> for paragraphs, <strong>/<em> for emphasis already implied by the text, <ul>/<li>
  for lists if the content is clearly list-like. Do NOT add headings that aren't implied by
  the text, and do NOT add new claims, stats, or sentences that aren't in the raw content.
- The raw content may ALREADY contain real hyperlinks, in either of two forms - both carry a
  real, trusted URL, so do not discard them and do not put them through the placeholder
  system below:
    (a) An actual HTML anchor tag, e.g. <a href="https://...">some text</a> - this happens when
        the user pasted rich text (e.g. copied straight from Google Docs) where the link was a
        real hyperlink, not typed-out markdown.
    (b) Markdown-style link syntax, "[some text](https://...)", or the same thing wrapped in an
        extra pair of brackets, "[[some text](https://...)]" (this double-bracket form usually
        marks an image/graphic or an existing call-to-action in the source doc).
  For either form:
    - If it's a plain inline link (not a CTA) -> render/keep it as a plain inline
      <a href="url">text</a> in place, using the URL exactly as given.
    - If it reads like a call-to-action (e.g. "read report", "register", "click here"),
      especially the double-bracket markdown form -> render as a standalone centered button
      using EXACTLY this markup, with the real url and text substituted in:
      <p style="text-align:center;margin:24px 0;"><a href="url" style="background-color:#0068B5;color:#ffffff;padding:12px 28px;border-radius:4px;text-decoration:none;font-weight:bold;display:inline-block;font-family:Arial,sans-serif;">text</a></p>
    - A link that is clearly just a header/banner graphic (e.g. "email header graphic") rather
      than a CTA or real inline link -> drop it entirely, it's a design element from the source
      doc, not email copy.
- Separately, for each INLINE link in the "Links to place" list above (a link the user typed
  into the UI, NOT already present as markdown in the raw text), wrap the most natural
  matching phrase already in the text with <a href="__LINK_<id>__">that exact phrase</a> -
  use the literal placeholder "__LINK_<id>__" as the href value (not the real URL).
- For each BUTTON link in the "Links to place" list, insert a standalone line
  "[[BUTTON_<id>]]" (nothing else on that line) at the point in the flow where that
  call-to-action belongs (usually near the end, or right after the most relevant paragraph).
- Keep the email's original meaning and tone - this is a cleanup/formatting pass, not a
  rewrite of the message.

Reply with ONLY this JSON (no markdown fences):
{{"html": "...", "confident": true/false}}"""


_SHARE_MARKER_RE = re.compile(r"\[?\s*click\s*to\s*share\s*function\s*:?\s*", re.IGNORECASE)
_BUTTON_HREF_RE = re.compile(r'<a href="([^"]+)"\s+style="background-color:#0068B5')
_ANY_HREF_RE = re.compile(r'<a href="([^"]+)"')


def _split_share_section(raw_content: str):
    """
    Docs sometimes end with a "click to share function:" marker followed by
    freeform social-copy text. Everything from that marker onward is pulled
    out here (code, not AI - this is a literal marker, not a judgment call) so
    it isn't polished as regular email body copy; the text after it becomes
    the pre-written share-post copy.

    Returns (body_content, share_text_or_None).
    """
    m = _SHARE_MARKER_RE.search(raw_content)
    if not m:
        return raw_content, None
    body = raw_content[:m.start()].rstrip()
    share_text = raw_content[m.end():].strip().rstrip("]").strip()
    share_text = _strip_html_to_text(share_text)
    return body, (share_text or None)


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html_to_text(fragment: str) -> str:
    """
    The "click to share function:" text comes straight from the raw pasted
    content, which (via the rich-paste contenteditable box) may itself be
    HTML - <p>, <span>, <br>, &nbsp; etc. The X/LinkedIn share text param
    must be plain text, so tags are stripped and entities decoded here
    before anything gets URL-encoded.
    """
    text = _TAG_RE.sub(" ", fragment)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_main_cta_url(html: str) -> str:
    """The real URL of the doc's own CTA button/link (already resolved to a
    real href by the AI polish pass, never a placeholder) - used as the
    article link for the share buttons. Prefers the styled CTA button; falls
    back to the first link in the content if there's no button."""
    m = _BUTTON_HREF_RE.search(html)
    if m:
        return m.group(1)
    m = _ANY_HREF_RE.search(html)
    return m.group(1) if m else ""


def _build_share_block(share_text: str, main_url: str) -> str:
    """
    Deterministic (no AI) construction of the X / LinkedIn share buttons,
    matching the reference design: two bold underlined links side by side
    with a rule underneath. URL-encoding is done here in code, never by the
    model, so the share links can never be malformed or hallucinated.
    """
    from urllib.parse import quote

    x_url = f"https://x.com/intent/post?text={quote(share_text)}&url={quote(main_url, safe='')}"
    linkedin_url = f"https://www.linkedin.com/sharing/share-offsite/?url={quote(main_url, safe='')}"
    # HubSpot's rich-text/HTML module strips <table>/<tr>/<td> wrappers on
    # save, which collapsed the two links together with no gap ("SHARE ON
    # XSHARE ON LINKEDIN") because the padding lived on the <td>, not the
    # <a>. Putting the spacing directly on each <a>'s own inline style
    # survives that strip, the same way the CTA button's inline style does.
    link_style = "font-weight:bold;text-decoration:underline;color:#0f172a;font-family:Arial,sans-serif;padding:0 24px;display:inline-block;"
    return (
        '<p style="text-align:center;margin:24px 0 0 0;">'
        f'<a href="{x_url}" target="_blank" style="{link_style}">SHARE ON X</a>'
        f'<a href="{linkedin_url}" target="_blank" style="{link_style}">SHARE ON LINKEDIN</a>'
        "</p>"
        '<hr style="border:none;border-top:1px solid #0068B5;margin:16px 0 0 0;">'
    )


def ai_polish_pasted_content(raw_content: str, links: list = None, max_attempts: int = 3) -> str:
    """
    Turn manually-pasted raw text (the content-doc-fetch fallback) into clean
    email HTML, with user-specified links placed by the AI as inline <a> tags
    or button placeholders - mirrors ai_split_drafts's confidence-retry pattern.

    `links`: list of {"id": str, "text": str (description of where it goes),
    "url": str, "is_button": bool}. The AI only decides WHERE each link goes
    (as a placeholder token) - the real URL is substituted in mechanically
    afterward, so the AI can never invent or alter a URL.

    If the raw content has a "click to share function:" marker, everything
    after it is split off (in code) as pre-written share-post copy, and a
    SHARE ON X / SHARE ON LINKEDIN button row is appended to the end of the
    output - both links built deterministically from the doc's own CTA link,
    never AI-encoded.

    Returns clean HTML with __LINK_<id>__ placeholders (inline) and
    [[BUTTON_<id>]] tokens (buttons) still unresolved - callers must run the
    result through `resolve_polish_placeholders()` before use.
    """
    links = links or []
    if not raw_content.strip():
        return ""

    body_content, share_text = _split_share_section(raw_content)
    if share_text:
        log.info(f"[AI POLISH] found 'click to share function' marker - splitting off {len(share_text)} chars of share copy")

    link_block = "\n".join(
        f'  - id={l["id"]!r}, type={"BUTTON" if l.get("is_button") else "INLINE"}, '
        f'placement hint: {l.get("text") or "(no hint given - use your best judgment)"!r}'
        for l in links
    ) or "  (none - just clean up the text, no links to place)"

    rejection_hint = ""
    for attempt in range(1, max_attempts + 1):
        prompt = _POLISH_PROMPT.format(raw_content=body_content, link_block=link_block, rejection_hint=rejection_hint)
        log.info(f"[AI POLISH] attempt {attempt}: cleaning up {len(body_content)} chars, placing {len(links)} link(s)...")
        try:
            raw = llm_gateway.complete_text(prompt, system=_POLISH_SYSTEM, max_tokens=2000, timeout=60)
        except Exception as e:
            log.warning(f"[AI POLISH] attempt {attempt}: call failed: {e}")
            rejection_hint = ""
            continue

        parsed = _parse_json_object(_strip_json(raw))
        html = (parsed or {}).get("html") or ""
        missing = [l["id"] for l in links if f'__LINK_{l["id"]}__' not in html and f'[[BUTTON_{l["id"]}]]' not in html]

        if not html or missing or not (parsed or {}).get("confident", True):
            reason = f"missing placeholder(s) for link id(s) {missing}" if missing else "empty/not confident"
            log.info(f"[AI POLISH] attempt {attempt}: retrying ({reason})")
            rejection_hint = (
                "Every link id given above MUST appear exactly once, either as "
                '"__LINK_<id>__" (inline) or "[[BUTTON_<id>]]" (button). Retry.\n\n'
            )
            continue

        log.info(f"[AI POLISH] cleaned up content, placed {len(links)} link(s)")
        if share_text:
            main_url = _extract_main_cta_url(html)
            if main_url:
                html += _build_share_block(share_text, main_url)
                log.info(f"[AI POLISH] appended SHARE ON X / SHARE ON LINKEDIN buttons, article url={main_url!r}")
            else:
                log.warning("[AI POLISH] found share copy but no CTA link to build share buttons from - skipping share block")
        return html

    log.warning(f"[AI POLISH] all {max_attempts} attempts exhausted - falling back to plain paragraphs")
    fallback_html = "\n".join(f"<p>{line}</p>" for line in body_content.split("\n") if line.strip())
    if share_text:
        main_url = _extract_main_cta_url(fallback_html)
        if main_url:
            fallback_html += _build_share_block(share_text, main_url)
    return fallback_html


def resolve_polish_placeholders(html: str, links: list) -> str:
    """
    Mechanically substitute ai_polish_pasted_content's placeholders with the
    REAL urls/text - never AI-generated, so a URL can never be hallucinated.
    Inline links become plain <a href>; buttons become a centered,
    inline-styled anchor (the standard technique for clickable "buttons" in
    HTML email, since many email clients don't render <button>/CSS classes).
    """
    for l in links or []:
        lid, url, text = l["id"], l["url"], l.get("text") or "Learn more"
        html = html.replace(f"__LINK_{lid}__", url)
        button_html = (
            f'<p style="text-align:center;margin:24px 0;">'
            f'<a href="{url}" style="background-color:#0068B5;color:#ffffff;padding:12px 28px;'
            f'border-radius:4px;text-decoration:none;font-weight:bold;display:inline-block;'
            f'font-family:Arial,sans-serif;">{text}</a></p>'
        )
        html = html.replace(f"[[BUTTON_{lid}]]", button_html)
    return html
