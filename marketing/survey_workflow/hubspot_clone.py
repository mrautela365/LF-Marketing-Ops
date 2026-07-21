"""
Survey-workflow-only email cloning.

Unlike emailcreationskill's update_email_content() (which rebuilds a fixed
header/footer from scratch), this module clones a real, recently-sent HubSpot
email whose name contains "LF Research" or "Survey" — HubSpot's clone API
copies the whole email verbatim, so its header, footer, and social icons come
along for free — then uses AI to identify which section(s) of that clone hold
the main written body copy, and replaces ONLY those with the doc-extracted
draft content. Every other section (banner/header, footer divider, "FOLLOW US"
social icons, "sent by" text, HubSpot's native unsubscribe/address footer) is
left byte-for-byte as HubSpot cloned it.

Kept separate from emailcreationskill/backend so this preserve-original-footer
behavior only affects survey_workflow, not the general email creation service.
"""
import os
import re
import sys
import json
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emailcreationskill', 'backend'))

import llm_gateway
from hubspot_tools import _get, _patch, clone_email, set_email_send_list
from utm_tools import tag_html_links
from config import HUBSPOT_PORTAL_ID

log = logging.getLogger("survey-workflow.hubspot-clone")

_SOURCE_SEARCH_TERMS = ["LF Research", "Survey"]


def find_source_candidates(limit_per_term: int = 100) -> list:
    """
    Recent published HubSpot emails whose name contains BOTH 'LF Research' AND
    'Survey' (case-insensitive). Queries by the first term (narrower - fewer
    false positives to page through) then filters locally for the second, so
    an off-brand email like a CNCF survey (name has 'Survey' but not
    'LF Research') can never qualify as a candidate.
    """
    data = _get("/marketing/v3/emails", params={
        "limit": limit_per_term,
        "name__icontains": _SOURCE_SEARCH_TERMS[0],
        "orderBy": "-publishDate",
    })
    out = []
    for e in data.get("results", []):
        name = (e.get("name") or "").lower()
        if e.get("state") == "PUBLISHED" and e.get("id") and all(t.lower() in name for t in _SOURCE_SEARCH_TERMS):
            out.append(e)
    out.sort(key=lambda e: e.get("publishDate") or 0, reverse=True)
    return out


# ── AI: pick the best source email to clone from ────────────────────────────

_SELECT_SYSTEM = (
    "You are a marketing-ops analyst picking which past HubSpot email to clone "
    "as the starting point for a new survey campaign email. Base your choice only "
    "on the candidate list given - never invent an email. Return ONLY raw JSON, "
    "no markdown fences, no commentary."
)

_SELECT_PROMPT = """New campaign/task name: {task_name!r}

Candidate emails (most recently published first):
{candidate_block}

{rejection_hint}Pick the single candidate whose name/timing is the best template match for
this new campaign (e.g. same research report series, same survey program, most
recent if nothing else distinguishes them).

Reply with ONLY this JSON (no markdown fences):
{{"id": "<exact id from the list above>", "reason": "...", "confident": true/false}}"""


def ai_select_source_email(task_name: str, candidates: list, max_attempts: int = 3) -> dict:
    """Confidence-retry AI pick of a source email from `candidates` (list of HubSpot email dicts)."""
    by_id = {str(c.get("id")): c for c in candidates}
    candidate_block = "\n".join(
        f"  - id={c.get('id')!r} name={c.get('name')!r} publishDate={c.get('publishDate')!r}"
        for c in candidates
    )
    rejection_hint = ""

    for attempt in range(1, max_attempts + 1):
        prompt = _SELECT_PROMPT.format(
            task_name=task_name, candidate_block=candidate_block, rejection_hint=rejection_hint,
        )
        log.info(f"[AI SOURCE EMAIL] attempt {attempt}: choosing among {len(candidates)} candidate(s)...")
        try:
            raw = llm_gateway.complete_text(prompt, system=_SELECT_SYSTEM, max_tokens=300, timeout=60)
        except Exception as e:
            log.warning(f"[AI SOURCE EMAIL] attempt {attempt}: call failed: {e}")
            rejection_hint = ""
            continue

        parsed = _parse_json_object(_strip_json(raw))
        if parsed is None or str(parsed.get("id")) not in by_id:
            log.warning(f"[AI SOURCE EMAIL] attempt {attempt}: invalid or unknown id in response")
            rejection_hint = "You must reply with an 'id' EXACTLY matching one from the candidate list.\n\n"
            continue

        if not parsed.get("confident", True):
            log.info(f"[AI SOURCE EMAIL] attempt {attempt}: not confident, retrying")
            rejection_hint = "Re-read the candidates more carefully and try again.\n\n"
            continue

        chosen = by_id[str(parsed["id"])]
        log.info(f"[AI SOURCE EMAIL] selected {chosen.get('name')!r} (id={chosen.get('id')}): {parsed.get('reason', '')}")
        return chosen

    log.warning(f"[AI SOURCE EMAIL] all {max_attempts} attempts exhausted - falling back to most recent candidate")
    return candidates[0] if candidates else None


# ── AI: identify which cloned sections are the body copy ────────────────────

_SECTION_ROLE_SYSTEM = (
    "You are a marketing-ops analyst reading the JSON section/widget layout of a "
    "cloned HubSpot email. Base your answer only on the layout given - never invent "
    "sections. Return ONLY raw JSON, no markdown fences, no commentary."
)

_SECTION_ROLE_PROMPT = """This cloned email has {n} sections, in top-to-bottom order:
{section_block}

{rejection_hint}Identify which section_id(s) hold the MAIN WRITTEN BODY COPY of the email (the
part that should be replaced with new survey content) - as opposed to the
header/banner/logo image, footer divider, "FOLLOW US" social icons, "sent by"
attribution text, or HubSpot's native unsubscribe/address footer module, all of
which must be left untouched.

Reply with ONLY this JSON (no markdown fences):
{{"body_section_ids": ["..."], "confident": true/false}}"""


def ai_identify_body_sections(section_summary: list, max_attempts: int = 3) -> list:
    """Confidence-retry AI pick of which section ids are the email's body copy."""
    valid_ids = {s["section_id"] for s in section_summary}
    section_block = "\n".join(
        f"  {i}. section_id={s['section_id']!r} widgets={s['widget_paths']}"
        + (f" preview={s['preview']!r}" if s.get("preview") else "")
        for i, s in enumerate(section_summary)
    )
    rejection_hint = ""

    for attempt in range(1, max_attempts + 1):
        prompt = _SECTION_ROLE_PROMPT.format(
            n=len(section_summary), section_block=section_block, rejection_hint=rejection_hint,
        )
        log.info(f"[AI BODY SECTION] attempt {attempt}: reading {len(section_summary)} section(s)...")
        try:
            raw = llm_gateway.complete_text(prompt, system=_SECTION_ROLE_SYSTEM, max_tokens=300, timeout=60)
        except Exception as e:
            log.warning(f"[AI BODY SECTION] attempt {attempt}: call failed: {e}")
            rejection_hint = ""
            continue

        parsed = _parse_json_object(_strip_json(raw))
        ids = parsed.get("body_section_ids") if parsed else None
        if not ids or not all(i in valid_ids for i in ids):
            log.warning(f"[AI BODY SECTION] attempt {attempt}: invalid/unknown section id(s) in response")
            rejection_hint = "Every id in 'body_section_ids' must EXACTLY match a section_id listed above.\n\n"
            continue

        if not parsed.get("confident", True):
            log.info(f"[AI BODY SECTION] attempt {attempt}: not confident, retrying")
            rejection_hint = "Look again at the widget types/preview text and try again.\n\n"
            continue

        log.info(f"[AI BODY SECTION] identified body section(s): {ids}")
        return ids

    log.warning(f"[AI BODY SECTION] all {max_attempts} attempts exhausted - could not identify body section(s)")
    return []


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


def _summarize_sections(content: dict, flex_area_name: str) -> list:
    """Build a compact {section_id, widget_paths, preview} list for the AI section-role call."""
    sections = ((content.get("flexAreas") or {}).get(flex_area_name) or {}).get("sections") or []
    widgets = content.get("widgets") or {}
    out = []
    for sec in sections:
        widget_keys = [w for col in sec.get("columns", []) for w in col.get("widgets", [])]
        paths, preview = [], ""
        for wk in widget_keys:
            body = (widgets.get(wk) or {}).get("body") or {}
            path = body.get("path") or f"module_id:{body.get('module_id', '?')}"
            paths.append(path)
            if not preview and body.get("html"):
                preview = re.sub(r"<[^>]+>", "", body["html"]).strip()[:120]
        out.append({"section_id": sec.get("id"), "widget_paths": paths, "preview": preview})
    return out


def clone_and_replace_body(task_name: str, content_html: str, clone_name: str,
                            send_list_id: str = None, suppression_list_ids: list = None,
                            utm_params: dict = None) -> dict:
    """
    Full pipeline: find LF Research/Survey candidates -> AI select one -> clone
    it verbatim -> AI identify its body section(s) -> replace ONLY those with
    `content_html`, leaving header/footer/social untouched -> apply send list.

    Guardrail: the source email selected here is only ever READ, never
    written to. Every mutation (_patch, set_email_send_list) below targets
    `email_id` - the brand-new clone HubSpot just created - and nothing else.
    """
    candidates = find_source_candidates()
    if not candidates:
        raise ValueError("No published HubSpot emails found with 'LF Research' or 'Survey' in the name.")

    selected = ai_select_source_email(task_name, candidates)
    if not selected:
        raise ValueError("Could not confidently select a source email to clone from LF Research/Survey emails.")

    cloned = clone_email(selected["id"], clone_name)
    email_id = cloned["email_id"]
    assert str(email_id) != str(selected["id"]), (
        "Refusing to proceed: clone API returned the SOURCE email's own id - "
        "this would mean writing to an existing email instead of a new clone."
    )
    log.info(f"[CLONE] cloned source={selected['id']} ({selected.get('name')!r}) -> new={email_id}")

    email = _get(f"/marketing/v3/emails/{email_id}")
    content = email.get("content") or {}
    flex_areas = content.get("flexAreas") or {}
    flex_area_name = next(iter(flex_areas), "main")

    section_summary = _summarize_sections(content, flex_area_name)
    if not section_summary:
        raise ValueError(f"Cloned email {email_id} has no sections to analyze.")

    body_section_ids = ai_identify_body_sections(section_summary)
    if not body_section_ids:
        raise ValueError(
            f"Could not confidently identify the body/content section(s) in cloned email {email_id}."
        )

    primary_id = body_section_ids[0]
    extra_ids = set(body_section_ids[1:])

    widgets = dict(content.get("widgets") or {})
    new_widget_key = "survey_body_content"
    widgets[new_widget_key] = {
        "type": "module",
        "body": {
            "path": "@hubspot/rich_text",
            "module_id": 1155639,
            "html": tag_html_links(content_html, utm_params or {}),
            "hs_enable_module_padding": True,
            "hs_wrapper_css": {
                "padding-bottom": "10px", "padding-left": "20px",
                "padding-right": "20px", "padding-top": "15px",
            },
        },
    }

    sections = (flex_areas.get(flex_area_name) or {}).get("sections") or []
    new_sections, replaced = [], False
    for sec in sections:
        if sec.get("id") == primary_id:
            new_sections.append({
                "id": sec["id"],
                "columns": [{"id": f"col-{sec['id']}-0", "widgets": [new_widget_key], "width": 12}],
                "style": sec.get("style", {}),
            })
            replaced = True
        elif sec.get("id") in extra_ids:
            continue  # drop extra body sections; header/footer sections pass through untouched
        else:
            new_sections.append(sec)

    if not replaced:
        raise ValueError(f"Body section {primary_id!r} identified by AI was not found among cloned email sections.")

    new_content = {
        "templatePath": content.get("templatePath"),
        "widgets": widgets,
        "flexAreas": {flex_area_name: {**flex_areas[flex_area_name], "sections": new_sections}},
    }
    if content.get("styleSettings"):
        new_content["styleSettings"] = content["styleSettings"]

    _patch(f"/marketing/v3/emails/{email_id}", {"content": new_content})
    log.info(f"[CLONE] body section {primary_id!r} replaced with doc content on email {email_id}")

    if send_list_id:
        set_email_send_list(email_id, send_list_id, suppression_list_ids or [])

    verify = _get(f"/marketing/v3/emails/{email_id}")
    return {
        "email_id": email_id,
        "email_name": verify.get("name"),
        "draft_url": f"https://app.hubspot.com/email/{HUBSPOT_PORTAL_ID}/edit/{email_id}/settings",
        "source_email_id": selected["id"],
        "source_email_name": selected.get("name"),
        "body_section_id": primary_id,
    }
