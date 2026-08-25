"""
HubSpot integration for the Survey/Report promo tab's approve + implementation
steps: find the most recent same-brand+type published email, clone it, and
surgically swap only the hero image + body copy — header/footer/template are
left byte-for-byte untouched because we PATCH back the full fetched content
object with just those nested values mutated in place (no section/flexArea
rebuild). Also clones the fixed 3-email sequence workflow.

Ported from Survey_Workflow_automation/backend/integrations/hubspot.py. Its
list-management helpers (search_lists / create_list / get_list_size / ...) are
NOT ported — the Audience step uses this repo's Audience Builder, which has its
own HubSpot list layer in backend/audience_builder.

This module is kept separate from backend/integrations/hubspot.py because the
two have incompatible signatures for clone_email / update_email_settings, and
the survey flow needs helpers the other lacks (find_latest_email,
apply_body_and_banner, clone_sequence_workflow, ...). set_email_send_list is
the one exception — it delegates to the other module rather than duplicating
its ILS-vs-legacy routing.
"""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import HUBSPOT_ACCESS_TOKEN, HUBSPOT_PORTAL_ID

log = logging.getLogger("survey-promo")

_FOOTER_MARKERS = (
    "unsubscribe", "manage preferences", "manage your", "follow us",
    "sent by", "subscription center", "footer", "divider", "social",
)

# HubSpot's Marketing Emails/CRM APIs intermittently return a bare 500/502/503
# under normal load with no code-level cause on our side; a short retry clears
# most of them. 429 (rate limit) gets the same treatment since it's equally
# transient. Non-transient errors (4xx other than 429) are raised immediately.
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 1.5


def _headers() -> dict:
    return {"Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}", "Content-Type": "application/json"}


def _request(method: str, path: str, *, params: dict = None, json: dict = None) -> dict:
    url = f"https://api.hubapi.com{path}"
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        resp = requests.request(method, url, headers=_headers(), params=params, json=json, timeout=30)
        if resp.ok:
            return resp.json() if resp.content else {}

        if resp.status_code in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES:
            log.warning(
                f"[HS {method}] {path} -> HTTP {resp.status_code} (attempt {attempt + 1}/"
                f"{_MAX_RETRIES + 1}, retrying): {resp.text[:300]}"
            )
            time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        log.error(f"[HS {method}] {path} -> HTTP {resp.status_code}: {resp.text[:500]}")
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            break

    if last_exc:
        raise last_exc
    raise RuntimeError(f"[HS {method}] {path} failed after {_MAX_RETRIES + 1} attempts with no response.")


def _get(path: str, params: dict = None) -> dict:
    return _request("GET", path, params=params)


def _post(path: str, payload: dict) -> dict:
    return _request("POST", path, json=payload)


def _patch(path: str, payload: dict) -> dict:
    return _request("PATCH", path, json=payload)


def _search_published_by_name(name_term: str, max_pages: int = 5, page_size: int = 100) -> list:
    """Paginated PUBLISHED-email search, anchored on `name_term` via name__icontains."""
    results = []
    after = None
    for _ in range(max_pages):
        params = {"limit": page_size, "name__icontains": name_term, "orderBy": "-publishDate"}
        if after:
            params["after"] = after
        data = _get("/marketing/v3/emails", params=params)
        results.extend(e for e in data.get("results", []) if e.get("state") == "PUBLISHED")
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    return results


def find_latest_email(brand_term: str, type_term: str) -> dict:
    """Most recent PUBLISHED email matching this brand+type. Brand identity is
    non-negotiable here (the whole point of cloning is to reuse that brand's exact
    header/footer), so this anchors the search on `brand_term` and only accepts
    results that also contain `type_term` — it never falls back to a different
    brand's email, since that would silently clone the wrong header/footer/logo."""
    if not HUBSPOT_ACCESS_TOKEN:
        raise RuntimeError("HUBSPOT_ACCESS_TOKEN is not configured.")

    candidates = [
        e for e in _search_published_by_name(brand_term)
        if type_term.lower() in (e.get("name") or "").lower()
    ]

    if not candidates:
        return {"found": False, "brand_term": brand_term, "type_term": type_term}

    candidates.sort(key=lambda e: e.get("publishDate") or 0, reverse=True)
    best = candidates[0]

    return {
        "found": True,
        "email_id": best.get("id"),
        "name": best.get("name"),
        "publish_date": best.get("publishDate"),
    }


def find_email_by_name(exact_name: str) -> dict:
    """Look up a specific email by (close to) exact name — used for a manual
    clone-source override when the generic brand+type search misses it."""
    if not HUBSPOT_ACCESS_TOKEN:
        raise RuntimeError("HUBSPOT_ACCESS_TOKEN is not configured.")

    candidates = _search_published_by_name(exact_name)
    if not candidates:
        return {"found": False, "name": exact_name}

    exact = [e for e in candidates if (e.get("name") or "").strip().lower() == exact_name.strip().lower()]
    best = (exact or candidates)[0]

    return {
        "found": True,
        "email_id": best.get("id"),
        "name": best.get("name"),
        "publish_date": best.get("publishDate"),
    }


def clone_email(source_email_id: str, clone_name: str) -> dict:
    """Clone a HubSpot email. Returns new email id + draft edit URL. Verifies creation."""
    email = _post("/marketing/v3/emails/clone", {
        "id": source_email_id,
        "cloneName": clone_name,
        "language": "en",
    })
    email_id = email.get("id")
    if not email_id:
        raise ValueError(f"Clone API did not return an email ID. Response: {email}")

    verify = _get(f"/marketing/v3/emails/{email_id}")
    if not verify.get("id"):
        raise ValueError(f"Email {email_id} was not found in HubSpot after cloning.")

    return {
        "email_id": email_id,
        "name": verify.get("name"),
        "state": verify.get("state"),
        "draft_url": f"https://app.hubspot.com/email/{HUBSPOT_PORTAL_ID}/edit/{email_id}/settings",
    }


def update_email_settings(email_id: str, subject: str = "", preview_text: str = "") -> dict:
    payload = {}
    if subject:
        payload["subject"] = subject

    if preview_text:
        try:
            current = _get(f"/marketing/v3/emails/{email_id}")
            current_content = dict(current.get("content") or {})
            current_widgets = dict(current_content.get("widgets") or {})
            current_widgets["preview_text"] = {"body": {"value": preview_text}}
            current_content["widgets"] = current_widgets
            payload["content"] = current_content
        except Exception:
            payload["content"] = {"widgets": {"preview_text": {"body": {"value": preview_text}}}}

    if not payload:
        return {"success": True, "email_id": email_id, "fields_updated": []}

    _patch(f"/marketing/v3/emails/{email_id}", payload)
    return {"success": True, "email_id": email_id, "fields_updated": list(payload.keys())}


def upload_local_image_to_hubspot(file_path: str, filename: str = "") -> str:
    """Upload a LOCAL file (already staged on disk after user approval) to HubSpot's
    File Manager. Returns the CDN URL.

    Raises RuntimeError (rather than silently returning "") on failure — a swallowed
    failure here previously meant the hero-image swap was silently skipped, producing
    a draft that looked fine but still had the CLONE SOURCE's original banner."""
    if not HUBSPOT_ACCESS_TOKEN:
        raise RuntimeError("HUBSPOT_ACCESS_TOKEN is not configured.")

    path = Path(file_path)
    if not path.exists():
        raise RuntimeError(f"Local hero image file not found: {file_path}")

    filename = filename or path.name
    ext = path.suffix.lower().lstrip(".") or "jpg"
    content_type = f"image/{'jpeg' if ext == 'jpg' else ext}"

    try:
        with open(path, "rb") as fh:
            up = requests.post(
                "https://api.hubapi.com/files/v3/files",
                headers={"Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}"},
                files={"file": (filename, fh, content_type)},
                data={
                    "options": '{"access":"PUBLIC_INDEXABLE","overwrite":true}',
                    "folderPath": "/email-staging",
                },
                timeout=30,
            )
        up.raise_for_status()
        cdn_url = up.json().get("url", "")
        log.info(f"[IMAGE] uploaded {filename!r} -> {cdn_url!r}")
        return cdn_url
    except requests.exceptions.HTTPError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        log.error(f"[IMAGE] upload failed ({file_path!r}): HTTP {exc.response.status_code if exc.response is not None else '?'}: {detail}")
        raise RuntimeError(f"HubSpot rejected the hero image upload: {detail}") from exc


def email_edit_url(email_id: str) -> str:
    return f"https://app.hubspot.com/email/{HUBSPOT_PORTAL_ID}/edit/{email_id}/settings"


def flow_url(flow_id: str) -> str:
    return f"https://app.hubspot.com/workflows/{HUBSPOT_PORTAL_ID}/platform/flow/{flow_id}/edit"


def set_email_send_list(email_id: str, list_id: str, suppression_list_ids: list = None) -> dict:
    """Set a marketing email's recipient list, plus the lists it must never go
    to (`to.*.exclude`). Does not touch state/publish/schedule — a draft stays
    a draft; this only attaches lists.

    Delegates to integrations.hubspot rather than PATCHing here, because the
    routing is not obvious: a list id goes into `contactIlsLists` if it exists
    in CRM v3 and `contactLists` if it doesn't, and putting an ILS id (every
    Audience-Builder list is DYNAMIC, hence ILS) into `contactLists` makes
    HubSpot silently reject the whole `to` object — leaving the draft with no
    recipients and no error. That module also clears the clone source's stale
    contactIds and splits suppressions by namespace.
    """
    from integrations import hubspot as _core

    suppression_ids = [str(x) for x in (suppression_list_ids or []) if str(x).strip()]
    result = _core.set_email_send_list(email_id, str(list_id), suppression_list_ids=suppression_ids)
    return {
        "email_id": email_id,
        "list_id": str(list_id),
        "suppression_list_ids": suppression_ids,
        "success": result.get("success", False),
    }


# Fixed source workflow for the invite/reminder/deadline sequence feature:
# "26Q2 - LF Research - FINOS 2026: Workflow (Survey Promo)". All 3 emails
# are sent BY this workflow itself: action 2 (invite), action 8 (reminder),
# action 15 (deadline) — each gated by its own DELAY_UNTIL_DATE action
# (4, 9, 13 respectively).
SEQUENCE_WORKFLOW_SOURCE_ID = "1841232183"

# The same workflow's own 3 SEND_EMAIL actions (2, 8, 15) reference these email
# ids as content_id. Each is already type=AUTOMATED_EMAIL / "Send: Through an
# automation" with no audience list attached (that lives on the workflow's
# enrollment criteria instead) — cloning FROM these for sequence-stage drafts
# is what makes new invite/reminder/deadline drafts inherit that same send
# method from birth, instead of the "To a segment of contacts" method a
# regular published (batch) email clone would carry.
SEQUENCE_STAGE_TEMPLATE_EMAIL_IDS = {
    "invite": "215683844442",
    "reminder": "215677811259",
    "deadline": "215677725611",
}


def _date_to_static_value_ms(date_str: str) -> str:
    """HubSpot's DELAY_UNTIL_DATE actions store the calendar date as a
    midnight-UTC epoch-ms string; the actual send time comes from the
    sibling time_of_day field, not from this value."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return str(int(dt.timestamp() * 1000))


def clone_sequence_workflow(
    *, name: str, list_id: str,
    invite_email_id: str, invite_date: str, invite_time: dict,
    reminder_email_id: str, reminder_date: str, reminder_time: dict,
    deadline_email_id: str, deadline_date: str, deadline_time: dict,
) -> dict:
    """Clone SEQUENCE_WORKFLOW_SOURCE_ID, swapping its three SEND_EMAIL
    actions' content_id to the new invite/reminder/deadline email ids, its
    three DELAY_UNTIL_DATE actions' dates/times to the caller-supplied
    values, and its enrollment list to the caller-supplied audience list.
    Always created with isEnabled=False — this never activates anything;
    the user must manually enable the clone in HubSpot when ready."""
    source = _get(f"/automation/v4/flows/{SEQUENCE_WORKFLOW_SOURCE_ID}")
    actions = source["actions"]
    by_id = {a["actionId"]: a for a in actions}

    by_id["4"]["fields"]["date"]["staticValue"] = _date_to_static_value_ms(invite_date)
    by_id["4"]["fields"]["time_of_day"] = dict(invite_time)
    by_id["2"]["fields"]["content_id"] = str(invite_email_id)

    by_id["9"]["fields"]["date"]["staticValue"] = _date_to_static_value_ms(reminder_date)
    by_id["9"]["fields"]["time_of_day"] = dict(reminder_time)
    by_id["8"]["fields"]["content_id"] = str(reminder_email_id)

    by_id["13"]["fields"]["date"]["staticValue"] = _date_to_static_value_ms(deadline_date)
    by_id["13"]["fields"]["time_of_day"] = dict(deadline_time)
    by_id["15"]["fields"]["content_id"] = str(deadline_email_id)

    new_enrollment = dict(source["enrollmentCriteria"])
    new_enrollment["listFilterBranch"] = {
        "filterBranches": [{
            "filterBranches": [],
            "filters": [{"listId": str(list_id), "operator": "IN_LIST", "filterType": "IN_LIST"}],
            "filterBranchType": "AND",
            "filterBranchOperator": "AND",
        }],
        "filters": [],
        "filterBranchType": "OR",
        "filterBranchOperator": "OR",
    }

    body = {
        "isEnabled": False,
        "flowType": source["flowType"],
        "name": name,
        "startActionId": source["startActionId"],
        "actions": actions,
        "enrollmentCriteria": new_enrollment,
        "timeWindows": source.get("timeWindows", []),
        "blockedDates": source.get("blockedDates", []),
        "customProperties": source.get("customProperties", {}),
        "dataSources": source.get("dataSources", []),
        "suppressionListIds": source.get("suppressionListIds", []),
        "goalFilterBranch": source.get("goalFilterBranch"),
        "canEnrollFromSalesforce": source.get("canEnrollFromSalesforce", False),
        "type": source.get("type"),
        "objectTypeId": source.get("objectTypeId"),
    }
    created = _post("/automation/v4/flows", body)
    flow_id = created.get("id")
    if not flow_id:
        raise ValueError(f"Flow clone did not return an id. Response: {created}")
    return {
        "flow_id": flow_id,
        "name": created.get("name", name),
        "is_enabled": bool(created.get("isEnabled", False)),
        "url": flow_url(flow_id),
    }


def _is_footerish(widget_key: str, html_text: str) -> bool:
    text = f"{widget_key} {html_text}".lower()
    return any(marker in text for marker in _FOOTER_MARKERS)


def apply_body_and_banner(email_id: str, hero_image_url: str = "", body_html: str = "") -> dict:
    """Surgically mutate the cloned email's content: swap the first banner image's
    src, and the largest non-footer rich_text widget's html, then PATCH back the
    FULL content object fetched from HubSpot so everything else (header module,
    footer sections, templatePath, flexAreas, styleSettings) round-trips unchanged."""
    email = _get(f"/marketing/v3/emails/{email_id}")
    content = dict(email.get("content") or {})
    widgets = dict(content.get("widgets") or {})

    banner_widget_key = None
    if hero_image_url:
        # Emails commonly have >1 image widget (header logo + hero banner). The
        # header logo is always much smaller than the hero banner (e.g. 281x50
        # vs 600x314 observed on real FINOS/LF Research emails), so picking the
        # LARGEST-area image widget reliably finds the hero banner instead of
        # accidentally overwriting the logo, which is what the first-match
        # approach used to do.
        best_area = -1
        for key, widget in widgets.items():
            body = (widget or {}).get("body") or {}
            img = body.get("img")
            if not isinstance(img, dict):
                continue
            area = (img.get("width") or 0) * (img.get("height") or 0)
            if area > best_area:
                best_area = area
                banner_widget_key = key
        if banner_widget_key:
            widgets[banner_widget_key]["body"]["img"]["src"] = hero_image_url

    body_widget_key = None
    if body_html:
        best_len = -1
        for key, widget in widgets.items():
            if key == banner_widget_key:
                continue
            body = (widget or {}).get("body") or {}
            html_text = body.get("html")
            if not isinstance(html_text, str):
                continue
            if _is_footerish(key, html_text):
                continue
            if len(html_text) > best_len:
                best_len = len(html_text)
                body_widget_key = key
        if body_widget_key:
            widgets[body_widget_key]["body"]["html"] = body_html

    content["widgets"] = widgets
    _patch(f"/marketing/v3/emails/{email_id}", {"content": content})

    return {
        "success": True,
        "email_id": email_id,
        "banner_widget_updated": banner_widget_key,
        "body_widget_updated": body_widget_key,
    }
