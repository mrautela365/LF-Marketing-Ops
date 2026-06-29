"""
HubSpot API functions exposed as Claude tools.
All functions return dicts that Claude can reason about.
"""
import json
import re
import requests
from config import HUBSPOT_ACCESS_TOKEN, HUBSPOT_PORTAL_ID


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _get(path: str, params: dict = None) -> dict:
    resp = requests.get(f"https://api.hubapi.com{path}", headers=_headers(), params=params)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, payload: dict) -> dict:
    resp = requests.post(f"https://api.hubapi.com{path}", headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


def _patch(path: str, payload: dict) -> dict:
    resp = requests.patch(f"https://api.hubapi.com{path}", headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


# ── Tool 1: Brand history lookup ────────────────────────────────────────────

def lookup_brand_history(brand_name: str, email_type_hint: str = None) -> dict:
    """
    Find the most recently sent email for a brand and extract reusable settings.
    email_type_hint: optional keyword (e.g. 'newsletter', 'invite') to prefer
    a matching email as clone source while still using the most recent for settings.
    """
    # Sort by publishDate descending server-side — avoids the updatedAt trap
    # where old emails edited recently rank above newer sent ones.
    data = _get("/marketing/v3/emails", params={
        "limit": 30,
        "name__icontains": brand_name,
        "orderBy": "-publishDate",
    })
    emails = data.get("results", [])

    # Keep only PUBLISHED (sent/delivered) — filter out DRAFT, AUTOMATED
    brand_emails = [
        e for e in emails
        if e.get("state") == "PUBLISHED"
        and brand_name.lower() in e.get("name", "").lower()
    ]
    if not brand_emails:
        return {
            "found": False,
            "message": f"No sent emails found for brand '{brand_name}'. This appears to be a new brand — you must ask the user for: from_name, from_address, subscription_type, and suppression_list_ids.",
        }

    # For settings (from name/address) use the most recently sent email of any type
    settings_source = brand_emails[0]

    # For clone source, prefer an email whose name matches the type hint
    # so a newsletter clones from a newsletter, an invite from an invite
    clone_source = settings_source
    if email_type_hint:
        hint = email_type_hint.lower()
        type_matches = [
            e for e in brand_emails
            if hint in e.get("name", "").lower()
        ]
        if type_matches:
            clone_source = type_matches[0]  # most recent of matching type

    latest = clone_source

    send_opts = latest.get("sendOptions") or {}
    settings = latest.get("settings") or {}
    frm = latest.get("from") or {}

    return {
        "found": True,
        "last_email_id": latest.get("id"),
        "last_email_name": latest.get("name"),
        "from_name": frm.get("fromName") or settings.get("fromName"),
        "from_address": frm.get("replyTo") or settings.get("replyTo"),
        "suppression_list_ids": send_opts.get("suppressionListIds") or [],
        "included_list_ids": send_opts.get("contactListIds") or [],
        "email_type": latest.get("type") or "BATCH_EMAIL",
        "subscription_type_id": send_opts.get("subscriptionId"),
    }


# ── Tool 2: Clone email ──────────────────────────────────────────────────────

def search_emails_for_event(brand_name: str, event_name: str, location: str = "",
                             short_brand_name: str = "", event_short_name: str = "",
                             email_type: str = "", is_transactional: bool = None) -> dict:
    """
    Find the most recently sent HubSpot email for a specific brand + event.

    Search waterfall (stops at the first tier that returns results):
      Tier 1 — exact event name phrase:  name__icontains="Open Source Summit Japan"
      Tier 2 — short event name:         name__icontains="OSS Japan"
      Tier 3 — short brand fallback:     name__icontains="LF"
      Tier 4 — full brand name:          name__icontains="The Linux Foundation"

    Among the results from whichever tier matched, rank by:
      • email_type suffix bonus (+2 if name contains e.g. "invite")
      • publishDate descending (most recently sent wins all ties)
    """
    type_hint = email_type.lower().strip() if email_type else ""

    def _fetch(filter_str: str) -> list:
        data = _get("/marketing/v3/emails", params={
            "limit": 100,
            "name__icontains": filter_str,
            "orderBy": "-publishDate",
        })
        return [e for e in data.get("results", []) if e.get("state") == "PUBLISHED"]

    # Waterfall — use the first tier that returns any results
    emails = []
    matched_tier = ""
    for tier, filt in [
        ("event_name",       event_name),
        ("event_short_name", event_short_name),
        ("short_brand_name", short_brand_name),
        ("brand_name",       brand_name),
    ]:
        if filt:
            emails = _fetch(filt)
            if emails:
                matched_tier = tier
                break

    if not emails:
        return {
            "found": False,
            "message": f"No sent emails found for event '{event_name}' / brand '{brand_name}'.",
        }

    def sort_key(e):
        pub = e.get("publishDate") or 0
        name = e.get("name", "").lower()
        # publishDate is primary — always pick most recently sent.
        # type_bonus is tiebreaker only (emails sent on the exact same date).
        type_bonus = 1 if type_hint and type_hint in name else 0
        return (pub, type_bonus)

    emails.sort(key=sort_key, reverse=True)
    best_email = emails[0]
    best_score = sort_key(best_email)[1]  # type match tiebreaker (0 or 1)

    frm    = best_email.get("from") or {}
    to_obj = best_email.get("to") or {}
    ils    = to_obj.get("contactIlsLists") or {}   # ILS (v3) lists
    cls    = to_obj.get("contactLists") or {}       # legacy static lists

    # Combine ILS + legacy IDs, deduplicated
    suppression_ids   = list({*ils.get("exclude", []), *cls.get("exclude", [])})
    included_list_ids = list({*ils.get("include", []), *cls.get("include", [])})

    return {
        "found": True,
        "event_match": matched_tier in ("event_name", "event_short_name"),
        "matched_tier": matched_tier,
        "matched_email_id": best_email.get("id"),
        "matched_email_name": best_email.get("name"),
        "matched_score": best_score,
        "from_name": frm.get("fromName"),
        "from_address": frm.get("replyTo"),
        "email_type": best_email.get("type") or "BATCH_EMAIL",
        "suppression_list_ids": suppression_ids,
        "included_list_ids": included_list_ids,
    }


# Generic conference words to strip when building slug search tokens.
# We keep brand-specific abbreviations (mcp, cfp, kcd, etc.) and locations.
_SLUG_GENERIC = {
    "summit", "conference", "con", "forum", "day", "days",
    "event", "events", "virtual", "online", "global",
    "north", "south", "east", "west", "central",
}


def _slug_key_tokens(url: str) -> list[str]:
    """
    Extract meaningful search tokens from an event URL slug.

    Examples:
      mcp-dev-summit-toronto  →  ["mcp", "dev", "toronto"]
      open-source-summit-india →  ["open", "source", "india"]
      kubecon-cloudnativecon-eu →  ["kubecon", "cloudnativecon", "eu"]
    """
    import re as _re
    from urllib.parse import urlparse
    try:
        path   = urlparse(url).path.strip("/")
        slug   = path.split("/")[-1]
        tokens = [t.lower() for t in _re.split(r"[-_]", slug) if len(t) > 1]
        return [t for t in tokens if t not in _SLUG_GENERIC]
    except Exception:
        return []


def get_brand_emails(short_brand_name: str, brand_name: str,
                     event_short_names: list = None,
                     event_url: str = "",
                     limit_per_call: int = 20) -> list:
    """
    Fetch 30-40 published emails for a brand by searching across multiple terms.

    Search order:
      1. short_brand_name        — catches new "26QN - AIF - …" naming
      2. event_short_names       — each term searched as TOKEN-ANCHORED:
                                   search by first word, filter results by the rest.
                                   Fixes contiguous-substring failures like
                                   "MCP Toronto" not matching "MCP Dev Summit Toronto".
      3. URL slug tokens         — parse event_url slug, search by first key token,
                                   filter results by remaining tokens.
                                   e.g. mcp-dev-summit-toronto → anchor "mcp",
                                   filter by ["dev","toronto"] → finds all emails
                                   whose names contain every key word from the slug.
      4. brand_name fallback     — only when results are still thin (<10)

    Results are deduplicated by email ID and sorted newest-first.
    """
    seen: set       = set()
    all_emails: list = []

    def _fetch_and_add(filt: str) -> None:
        """Exact-phrase icontains search."""
        if not filt or len(filt) < 2:
            return
        data = _get("/marketing/v3/emails", params={
            "limit": limit_per_call,
            "name__icontains": filt,
            "orderBy": "-publishDate",
        })
        for e in data.get("results", []):
            eid = e.get("id")
            if e.get("state") == "PUBLISHED" and eid and eid not in seen:
                seen.add(eid)
                all_emails.append(e)

    def _fetch_tokenized(anchor: str, rest: list[str]) -> None:
        """
        Search by `anchor` (icontains), then keep only results whose name also
        contains every word in `rest`. Handles multi-word terms where the words
        may not be adjacent in the HubSpot email name.
        """
        if not anchor or len(anchor) < 2:
            return
        data = _get("/marketing/v3/emails", params={
            "limit": limit_per_call * 3,   # cast a wider net before filtering
            "name__icontains": anchor,
            "orderBy": "-publishDate",
        })
        for e in data.get("results", []):
            eid = e.get("id")
            if e.get("state") != "PUBLISHED" or not eid or eid in seen:
                continue
            name_lc = (e.get("name") or "").lower()
            if all(r.lower() in name_lc for r in rest):
                seen.add(eid)
                all_emails.append(e)

    # ── Tier 1: brand short code — wrapped in " - " to match naming convention ──
    # "26Q2 - AIF - Event" → search "- AIF -" matches; "LFEducation_..." does NOT.
    if short_brand_name:
        _fetch_and_add(f"- {short_brand_name} -")
        _fetch_and_add(f"- {short_brand_name} ")  # end-of-segment: "- LFE Summit"

    # ── Tier 2: event short names — smart anchor selection ───────────────────
    # Skip generic/short first words (LF, the, etc.) so "LF Energy Summit EU"
    # uses anchor="Energy" not anchor="LF" (which is on every LF email).
    _ANCHOR_SKIP = {"lf", "the", "a", "an", "of", "for", "and", "or"}
    for esn in (event_short_names or []):
        if not esn:
            continue
        parts = esn.split()
        if len(parts) == 1:
            _fetch_and_add(esn)
        else:
            # Find first meaningful anchor word (not in skip list, length > 2)
            anchor_idx = 0
            for i, p in enumerate(parts):
                if p.lower() not in _ANCHOR_SKIP and len(p) > 2:
                    anchor_idx = i
                    break
            anchor = parts[anchor_idx]
            rest   = [p for i, p in enumerate(parts) if i != anchor_idx]
            _fetch_tokenized(anchor, rest)

    # ── Tier 3: URL slug tokens ───────────────────────────────────────────────
    # mcp-dev-summit-toronto → ["mcp","dev","toronto"]
    # search anchor="mcp", filter by ["dev","toronto"]
    if event_url:
        slug_tokens = _slug_key_tokens(event_url)
        if len(slug_tokens) >= 2:
            _fetch_tokenized(slug_tokens[0], slug_tokens[1:])
        elif len(slug_tokens) == 1:
            _fetch_and_add(slug_tokens[0])

    # ── Tier 4: full brand name fallback ─────────────────────────────────────
    if len(all_emails) < 10:
        _fetch_and_add(brand_name)

    # Return sorted newest-first, capped at 60
    all_emails.sort(key=lambda e: e.get("publishDate") or 0, reverse=True)
    return all_emails[:60]


def search_lists(query: str, limit: int = 10) -> dict:
    """Search HubSpot contact lists by name using the v3 CRM Lists search API."""
    if not query or len(query) < 2:
        return {"lists": []}
    try:
        data = _post("/crm/v3/lists/search", {
            "query": query,
            "count": limit,
            "processingTypes": ["MANUAL", "SNAPSHOT"],
        })
        lists = data.get("lists") or []
        return {
            "lists": [
                {
                    "id": str(l.get("listId") or l.get("id") or ""),
                    "name": l.get("name", ""),
                    "size": int((l.get("additionalProperties") or {}).get("hs_list_size") or 0),
                }
                for l in lists
                if l.get("name") and (l.get("listId") or l.get("id"))
            ]
        }
    except Exception as e:
        return {"lists": [], "error": str(e)}


def clone_email(source_email_id: str, clone_name: str) -> dict:
    """Clone a HubSpot email. Returns new email ID and draft URL. Verifies creation."""
    email = _post("/marketing/v3/emails/clone", {
        "id": source_email_id,
        "cloneName": clone_name,
        "language": "en",
    })
    email_id = email.get("id")
    if not email_id:
        raise ValueError(f"Clone API did not return an email ID. Response: {email}")

    # Verify the email actually exists in HubSpot before returning
    verify = _get(f"/marketing/v3/emails/{email_id}")
    if not verify.get("id"):
        raise ValueError(f"Email {email_id} was not found in HubSpot after cloning.")

    draft_url = f"https://app.hubspot.com/email/{HUBSPOT_PORTAL_ID}/edit/{email_id}/settings"
    return {
        "email_id": email_id,
        "name": verify.get("name"),
        "state": verify.get("state"),
        "draft_url": draft_url,
        "verified": True,
    }


# ── Tool 3: Update email settings ───────────────────────────────────────────

def update_email_settings(
    email_id: str,
    subject: str = None,
    preview_text: str = None,
    from_name: str = None,
    from_address: str = None,
    suppression_list_ids: list = None,
    send_list_id: str = None,
    email_type: str = None,
) -> dict:
    payload = {}

    if subject:
        payload["subject"] = subject
    if email_type:
        payload["type"] = email_type

    if preview_text:
        # DnD emails store preview text in content.widgets.preview_text.
        # Fetch the current content first and merge — sending a partial content
        # object risks wiping templatePath/flexAreas/body widgets if HubSpot
        # does a shallow replace of the content field on PATCH.
        try:
            current = _get(f"/marketing/v3/emails/{email_id}")
            current_content = dict(current.get("content") or {})
            current_widgets = dict(current_content.get("widgets") or {})
            current_widgets["preview_text"] = {"body": {"value": preview_text}}
            current_content["widgets"] = current_widgets
            payload["content"] = current_content
        except Exception:
            # Fallback: set only the preview_text widget (may wipe other
            # content fields if HubSpot shallow-replaces, but update_email_content
            # will restore them when it runs next).
            payload["content"] = {
                "widgets": {"preview_text": {"body": {"value": preview_text}}}
            }

    frm = {}
    if from_name:
        frm["fromName"] = from_name
    if from_address:
        frm["replyTo"] = from_address
    if frm:
        payload["from"] = frm

    result = _patch(f"/marketing/v3/emails/{email_id}", payload)
    return {"success": True, "email_id": email_id, "fields_updated": list(payload.keys())}


# ── Tool 3b: Set email send / suppression lists ──────────────────────────────

def _get_list_processing_type(list_id: str) -> str:
    """Return 'SNAPSHOT', 'DYNAMIC', 'MANUAL', or 'UNKNOWN' for a HubSpot contact list.

    The CRM v3 GET /lists/{id} response nests the list under a top-level "list"
    key: {"list": {"processingType": "DYNAMIC", ...}}. Reading processingType
    from the top level always yields UNKNOWN — which made set_email_send_list
    misclassify every dynamic list as static and silently drop the `to` update.

    Returns 'UNKNOWN' when the list is not found in CRM v3 (i.e. a legacy list
    that only exists in the old /contacts/v1/lists namespace).
    """
    import logging as _logging
    _l = _logging.getLogger("email-staging")
    try:
        data = requests.get(
            f"https://api.hubapi.com/crm/v3/lists/{list_id}",
            headers=_headers(),
            timeout=10,
        )
        if data.ok:
            body = data.json()
            # processingType lives under the "list" wrapper; fall back to top level
            list_obj = body.get("list") if isinstance(body.get("list"), dict) else body
            ptype = list_obj.get("processingType", "UNKNOWN")
            _l.info(f"[HS-LISTS] list {list_id} processingType={ptype!r}")
            return ptype
        _l.warning(f"[HS-LISTS] list type lookup for {list_id}: HTTP {data.status_code}")
    except Exception as exc:
        _l.warning(f"[HS-LISTS] list type lookup for {list_id} failed: {exc}")
    return "UNKNOWN"


# CRM v3 processing types — any list with one of these is an ILS list and must
# go into the email's contactIlsLists field. Lists not found in CRM v3 (returns
# UNKNOWN) are legacy lists and go into contactLists.
_ILS_PROCESSING_TYPES = {"DYNAMIC", "MANUAL", "SNAPSHOT"}


def _is_ils_list(list_id: str) -> bool:
    """True if the list lives in the CRM v3 (ILS) namespace → contactIlsLists.

    False for legacy lists (404 in CRM v3) → contactLists. Audience-built lists
    are always created via CRM v3, so they are always ILS.
    """
    return _get_list_processing_type(list_id) in _ILS_PROCESSING_TYPES


def set_email_send_list(
    email_id: str,
    send_list_id: str,
    suppression_list_ids: list = None,
) -> dict:
    """
    Set the recipient + suppression lists on a HubSpot marketing email.

    Sends a COMPLETE `to` object so HubSpot replaces all sub-fields:
      - contactIds.include cleared  → removes any individual contacts from the clone source
      - contactIlsLists.include     → ILS list (DYNAMIC/MANUAL/SNAPSHOT — incl. audience-built)
      - contactLists.include        → legacy list (not found in CRM v3)
      - suppression IDs are routed into the matching field by namespace

    Routing rule: a list goes into contactIlsLists if it exists in CRM v3
    (any processingType), else contactLists. This is ILS-vs-legacy, NOT
    dynamic-vs-static — putting an ILS list ID in contactLists makes HubSpot
    silently reject the entire `to` object, leaving the email with no recipients.

    Why complete object: HubSpot's PATCH keeps sub-fields you omit, so a partial
    `to` patch leaves stale contactIds / stale list IDs from the clone source.
    """
    import logging as _logging
    _log = _logging.getLogger("email-staging")

    send_list_id = str(send_list_id)
    list_type = _get_list_processing_type(send_list_id)
    send_is_ils = list_type in _ILS_PROCESSING_TYPES
    _log.info(
        f"[HS-LISTS] set_email_send_list email={email_id} list={send_list_id} "
        f"type={list_type} → {'contactIlsLists' if send_is_ils else 'contactLists'}"
    )

    # Split suppressions by namespace. HubSpot mirrors excludes across the two
    # namespaces automatically (an ILS list and its legacy mirror are the same
    # logical list), so we only set them in the SAME namespace as the send list
    # and let HubSpot create the mirror. Opposite-namespace suppressions can't be
    # added in the same PATCH — doing so makes HubSpot drop the send-list include.
    same_ns_suppress: list = []
    other_ns_suppress: list = []
    for sid in (suppression_list_ids or []):
        sid = str(sid).strip()
        if not sid:
            continue
        is_ils = _is_ils_list(sid)
        if is_ils == send_is_ils:
            same_ns_suppress.append(sid if send_is_ils else int(sid) if sid.isdigit() else sid)
        else:
            other_ns_suppress.append(sid)
    if other_ns_suppress:
        _log.info(
            f"[HS-LISTS] {len(other_ns_suppress)} opposite-namespace suppression(s) "
            f"{other_ns_suppress} left to HubSpot's automatic exclude-mirroring"
        )

    # Build a MINIMAL `to` payload — only the namespace we're setting, plus a
    # contactIds clear. Critically, do NOT send the OPPOSITE namespace at all
    # (not even an empty include or an exclude-only): when setting an ILS list,
    # any `contactLists` key in the same PATCH makes HubSpot reject the ILS
    # include. Setting contactIlsLists alone already replaces the stale legacy
    # list with the correct mirror.
    to_payload: dict = {
        # Clearing contactIds removes any individual contacts the clone carried over.
        "contactIds": {"include": [], "exclude": []},
    }
    if send_is_ils:
        to_payload["contactIlsLists"] = {"include": [send_list_id], "exclude": same_ns_suppress}
    else:
        legacy_include = [int(send_list_id)] if send_list_id.isdigit() else []
        to_payload["contactLists"] = {"include": legacy_include, "exclude": same_ns_suppress}

    _log.info(f"[HS-LISTS] PATCHing to={to_payload}")
    result = _patch(f"/marketing/v3/emails/{email_id}", {"to": to_payload})

    applied_to = result.get("to") or {}
    all_applied = (
        [str(x) for x in (applied_to.get("contactLists")    or {}).get("include", [])] +
        [str(x) for x in (applied_to.get("contactIlsLists") or {}).get("include", [])]
    )
    success = str(send_list_id) in all_applied
    if success:
        _log.info(f"[HS-LISTS] ✓ send list {send_list_id} applied (type={list_type})")
    else:
        _log.warning(
            f"[HS-LISTS] ⚠ send_list_id={send_list_id!r} not in PATCH response "
            f"to={applied_to} — full response keys: {list(result.keys())}"
        )

    return {
        "success": success,
        "email_id": email_id,
        "send_list_id": send_list_id,
        "list_type": list_type,
        "to": applied_to,
    }


# ── Tool 3c: Read a sent email's content and structure as reference ───────────

def get_email_content_text(email_id: str) -> dict:
    """
    Extract full content and layout structure from a HubSpot marketing email.

    HubSpot module-based emails store data in two places:
      - content.widgets : flat dict keyed by module-ID string → actual widget data
      - content.flexAreas.main.sections[].columns[].widgets[] : ordered list of
        those module-ID strings (NOT dicts — just references)

    The old code looked for body["value"] inside the section widget dicts, but
    those are just string IDs. The real content is in content.widgets[id].body
    with field names: "html" (rich text), "text"/"destination"/"background_color"
    (button), "img" (image), "line_type" (divider), "social" (social icons).

    Returns:
      sections     : ordered list of component dicts (type, html, button attrs…)
      body_html    : concatenated rich-text HTML blocks (for AI style reference)
      body_text    : stripped plain text (for logging/fallback)
      subject, preview_text, email_name
    """
    import re as _re
    import logging as _logging
    _log = _logging.getLogger("email-staging")
    try:
        email   = _get(f"/marketing/v3/emails/{email_id}")
        content = email.get("content") or {}

        subject      = email.get("subject") or ""
        preview_text = ""

        # content.widgets is the flat lookup dict for ALL module widget data
        top_widgets = content.get("widgets") or {}

        # Preview text is a special top-level key (DnD emails only)
        pt_body = (top_widgets.get("preview_text") or {}).get("body") or {}
        preview_text = pt_body.get("value", "")

        # Walk flexAreas in section order.  Each section's widgets list holds
        # MODULE-ID STRINGS — resolve each to its actual data in top_widgets.
        html_parts:  list[str]  = []   # rich-text HTML blocks, in order
        sections_out: list[dict] = []  # structured component map for the AI

        for _area_name, area in (content.get("flexAreas") or {}).items():
            for section in (area.get("sections") or []):
                col_count = len(section.get("columns") or [])
                # Multi-column sections (e.g. sponsor logo row)
                if col_count > 1:
                    col_images = []
                    for col in (section.get("columns") or []):
                        for wid in (col.get("widgets") or []):
                            if not isinstance(wid, str):
                                continue
                            body = (top_widgets.get(wid) or {}).get("body") or {}
                            img  = body.get("img") or {}
                            if isinstance(img, dict) and img.get("src"):
                                col_images.append({
                                    "src": img["src"],
                                    "alt": img.get("alt", ""),
                                })
                    if col_images:
                        sections_out.append({"type": "image_row", "images": col_images})
                    continue  # skip per-widget walk for multi-col sections

                # Single-column sections — walk widgets in order
                for col in (section.get("columns") or []):
                    for wid in (col.get("widgets") or []):
                        if not isinstance(wid, str):
                            continue
                        wdata = top_widgets.get(wid) or {}
                        body  = wdata.get("body") or {}

                        # ── Rich text ────────────────────────────────────────
                        html = body.get("html", "")
                        if html and html.strip():
                            html_parts.append(html)
                            sections_out.append({"type": "rich_text", "html": html})
                            continue

                        # ── Button ───────────────────────────────────────────
                        btn_text = body.get("text", "")
                        if btn_text:
                            sections_out.append({
                                "type":             "button",
                                "text":             btn_text,
                                "background_color": body.get("background_color", "#04c0da"),
                                "destination":      str(body.get("destination", "")),
                            })
                            continue

                        # ── Single image ─────────────────────────────────────
                        img = body.get("img") or {}
                        if isinstance(img, dict) and img.get("src"):
                            sections_out.append({
                                "type": "image",
                                "src":  img["src"],
                                "alt":  img.get("alt", ""),
                            })
                            continue

                        # ── Divider ──────────────────────────────────────────
                        if body.get("line_type"):
                            sections_out.append({
                                "type":   "divider",
                                "style":  body.get("line_type", "solid"),
                                "height": body.get("height", 1),
                            })
                            continue

                        # ── Social icons ─────────────────────────────────────
                        social = body.get("social")
                        if social:
                            nets = [s.get("network", "") for s in social if isinstance(s, dict)]
                            sections_out.append({"type": "social_icons", "networks": nets})

        # Concatenated rich-text HTML (preserves inline CSS, emoji, heading styles)
        body_html = "\n\n".join(h for h in html_parts if h.strip())

        # Stripped plain text for logging / fallback
        def _strip(html: str) -> str:
            html = _re.sub(r"<br\s*/?>",            "\n",  html, flags=_re.I)
            html = _re.sub(r"</?(p|div|tr)[^>]*>",  "\n",  html, flags=_re.I)
            html = _re.sub(r"</?(h[1-6])[^>]*>",    "\n",  html, flags=_re.I)
            html = _re.sub(r"<li[^>]*>",            "• ",  html, flags=_re.I)
            html = _re.sub(r"<[^>]+>",              "",    html)
            html = _re.sub(r"[ \t]+",               " ",   html)
            html = _re.sub(r"\n{3,}",               "\n\n",html)
            return html.strip()

        body_text = "\n\n".join(_strip(h) for h in html_parts if h.strip())
        body_text = _re.sub(r"\n{3,}", "\n\n", body_text).strip()

        _log.info(
            f"[REF-EMAIL] {email_id} — subject={subject!r} "
            f"components={len(sections_out)} html_blocks={len(html_parts)} "
            f"body_html={len(body_html)} chars"
        )
        return {
            "success":      True,
            "email_id":     email_id,
            "email_name":   email.get("name", ""),
            "subject":      subject,
            "preview_text": preview_text,
            "body_text":    body_text[:4000],
            "body_html":    body_html[:12000],
            "sections":     sections_out,   # structured component list for AI
        }
    except Exception as exc:
        _log.warning(f"[REF-EMAIL] failed to read {email_id}: {exc}")
        return {"success": False, "email_id": email_id, "error": str(exc)}


# ── Tool 4: Update email body content ───────────────────────────────────────

def update_email_content(
    email_id: str,
    html_content: str = "",
    banner_url: str = "",
    event_url: str = "",
    content_sections: list = None,
    sponsors: list = None,
) -> dict:
    """
    Replace email body using HubSpot's DnD widget/flexArea structure.

    Layout (when banner_url provided):
      Section 1 — @hubspot/image widget   ← banner image (proper image module, never stripped)
      Section 2 — @hubspot/rich_text widget ← body HTML only (no header/footer tables)

    Layout (no banner_url):
      Section 1 — @hubspot/rich_text widget ← full body HTML
    """
    import logging, re
    log = logging.getLogger("email-staging")

    # Fetch current state to preserve templatePath, styleSettings, and the
    # preview_text widget already applied by update_email_settings.
    email   = _get(f"/marketing/v3/emails/{email_id}")
    content = email.get("content") or {}

    # Discover the actual flex area name (do NOT hardcode "main")
    current_flex   = content.get("flexAreas") or {}
    flex_area_name = next(iter(current_flex), "main")
    template_path  = content.get("templatePath") or "@hubspot/email/dnd/Start_from_scratch.html"
    style_settings = content.get("styleSettings") or {}

    log.info(f"[CONTENT] email={email_id} flex={flex_area_name!r} "
             f"banner={'yes' if banner_url else 'no'} event_url={bool(event_url)}")

    # Strip outer DOCTYPE/html/head/body — HubSpot wraps content itself
    body_match = re.search(r"<body[^>]*>([\s\S]*?)</body\s*>", html_content, re.IGNORECASE)
    inner_html  = body_match.group(1).strip() if body_match else html_content.strip()
    log.info(f"[CONTENT] inner_html={len(inner_html):,} chars")

    # ── Carry over preview_text widget ─────────────────────────────────────
    preview_text_widget = (content.get("widgets") or {}).get("preview_text")

    # ── Build widgets dict ──────────────────────────────────────────────────
    widgets: dict  = {}
    sections: list = []

    _section_style = {
        "backgroundType": "CONTENT",
        "breakpointStyles": {"default": {"backgroundType": "CONTENT"}},
    }

    # Banner image — uses HubSpot's dedicated image module so it is NEVER stripped
    if banner_url:
        BANNER = "staging_banner"
        widgets[BANNER] = {
            "type": "module",
            "body": {
                "path": "@hubspot/image",
                "schema_version": 2,
                "img": {
                    "src": banner_url,
                    "alt": "Email Banner",
                    "width": 600,
                    "loading": "lazy",
                },
                "href": event_url or "",
                "align": "center",
                "target": "_blank",
                "max_width": 600,
                # Full-bleed hero: disable the image module's DEFAULT wrapper padding.
                # Without this HubSpot adds ~20px left/right, so a 600px image inside a
                # 560px padded column overflows by 40px (the "hero going out" bug).
                "hs_enable_module_padding": False,
                "hs_wrapper_css": {
                    "padding-top":    "0px",
                    "padding-bottom": "0px",
                    "padding-left":   "0px",
                    "padding-right":  "0px",
                },
            },
        }
        sections.append({
            "id":      "section-staging-banner",
            "columns": [{"id": "col-banner-0", "widgets": [BANNER], "width": 12}],
            "path":    None,
            "style":   _section_style,
        })
        log.info(f"[CONTENT] banner widget added: {banner_url!r}")

    # Body content — structured sections (native modules) or fallback rich_text
    if content_sections:
        for _idx, _sec in enumerate(content_sections):
            _stype = _sec.get("type", "")
            if _stype == "rich_text":
                _wid = f"staging_sec_{_idx}"
                widgets[_wid] = {
                    "type": "module",
                    "body": {
                        "path":      "@hubspot/rich_text",
                        "module_id": 1155639,
                        "html":      _sec.get("html", ""),
                        "hs_enable_module_padding": True,
                        "hs_wrapper_css": {
                            "padding-bottom": "10px",
                            "padding-left":   "20px",
                            "padding-right":  "20px",
                            "padding-top":    "15px",
                        },
                    },
                }
                sections.append({
                    "id":      f"section-sec-{_idx}",
                    "columns": [{"id": f"col-sec-{_idx}-0", "widgets": [_wid], "width": 12}],
                    "path":    None,
                    "style":   _section_style,
                })
            elif _stype == "button":
                _btn_color = _sec.get("color") or "#04c0da"
                _wid = f"staging_btn_{_idx}"
                widgets[_wid] = {
                    "type": "module",
                    "body": {
                        "module_id":      1976948,
                        "background_color": _btn_color,
                        "corner_radius":  8,
                        "destination":    _sec.get("url", "#"),
                        "font":           "Arial, sans-serif",
                        "font_color":     "#ffffff",
                        "font_size":      16,
                        "font_style": {
                            "color":  "#ffffff",
                            "font":   "Arial, sans-serif",
                            "size":   {"units": "px", "value": 16},
                            "styles": {"bold": True, "font-weight": "bold",
                                       "italic": False, "underline": False},
                        },
                        "text": _sec.get("text", "Register Now"),
                        "hs_enable_module_padding": True,
                        "hs_wrapper_css": {
                            "padding-bottom": "5px",
                            "padding-left":   "20px",
                            "padding-right":  "20px",
                            "padding-top":    "5px",
                        },
                    },
                }
                sections.append({
                    "id":      f"section-btn-{_idx}",
                    "columns": [{"id": f"col-btn-{_idx}-0", "widgets": [_wid], "width": 12}],
                    "path":    None,
                    "style":   _section_style,
                })

        # Sponsors as native @hubspot/image modules (visible in DnD editor)
        if sponsors:
            _SPON_HDR = "staging_sponsor_header"
            widgets[_SPON_HDR] = {
                "type": "module",
                "body": {
                    "path":      "@hubspot/rich_text",
                    "module_id": 1155639,
                    "html":      '<p style="font-weight:bold;text-align:center;font-size:18px;line-height:175%;">Thank You to Our Sponsors!</p>',
                    "hs_enable_module_padding": True,
                    "hs_wrapper_css": {
                        "padding-bottom": "10px",
                        "padding-left":   "20px",
                        "padding-right":  "20px",
                        "padding-top":    "10px",
                    },
                },
            }
            sections.append({
                "id":      "section-sponsor-header",
                "columns": [{"id": "col-sph-0", "widgets": [_SPON_HDR], "width": 12}],
                "path":    None,
                "style":   _section_style,
            })

            _logo_sp = [s for s in sponsors if isinstance(s, dict) and s.get("logo_url")]
            _name_sp = [s for s in sponsors if isinstance(s, dict) and not s.get("logo_url") and s.get("name")]

            if _logo_sp:
                _n     = len(_logo_sp)
                _col_w = max(2, 12 // _n)
                _cols  = []
                for _j, _sp in enumerate(_logo_sp):
                    _img_wid = f"staging_sponsor_img_{_j}"
                    widgets[_img_wid] = {
                        "type": "module",
                        "body": {
                            "module_id": 1367093,
                            "img": {
                                "alt":     _sp.get("name", "Sponsor"),
                                "height":  60,
                                "loading": "disabled",
                                "src":     _sp["logo_url"],
                                "width":   180,
                            },
                            "link": "",
                            "hs_enable_module_padding": True,
                            "hs_wrapper_css": {
                                "padding-bottom": "20px",
                                "padding-left":   "20px",
                                "padding-right":  "20px",
                                "padding-top":    "20px",
                            },
                        },
                    }
                    _cols.append({"id": f"col-sp-{_j}", "widgets": [_img_wid], "width": _col_w})
                sections.append({
                    "id":      "section-sponsor-row",
                    "columns": _cols,
                    "path":    None,
                    "style":   _section_style,
                })

            if _name_sp:
                _names_html = " &nbsp;|&nbsp; ".join(
                    f'<strong>{s.get("name", "")}</strong>' for s in _name_sp
                )
                _SPON_NAMES = "staging_sponsor_names"
                widgets[_SPON_NAMES] = {
                    "type": "module",
                    "body": {
                        "path":      "@hubspot/rich_text",
                        "module_id": 1155639,
                        "html":      f'<p style="text-align:center;font-size:14px;">{_names_html}</p>',
                        "hs_enable_module_padding": True,
                        "hs_wrapper_css": {
                            "padding-bottom": "10px",
                            "padding-left":   "20px",
                            "padding-right":  "20px",
                            "padding-top":    "10px",
                        },
                    },
                }
                sections.append({
                    "id":      "section-sponsor-names",
                    "columns": [{"id": "col-spn-0", "widgets": [_SPON_NAMES], "width": 12}],
                    "path":    None,
                    "style":   _section_style,
                })
    else:
        # Fallback: monolithic rich_text (used when no structured sections available)
        BODY = "staging_body"
        widgets[BODY] = {
            "type": "module",
            "body": {
                "path":           "@hubspot/rich_text",
                "schema_version": 2,
                "html":           inner_html,
            },
        }
        sections.append({
            "id":      "section-staging-body",
            "columns": [{"id": "col-body-0", "widgets": [BODY], "width": 12}],
            "path":    None,
            "style":   _section_style,
        })

    # ── Footer sections ────────────────────────────────────────────────────────
    # Mirrors the exact widget structure used in real published LF emails.
    # Order: divider → "FOLLOW US" heading → social icons → "sent by" text → HS footer

    # Pre-footer divider — must use @hubspot/email_divider (module_id 2191110),
    # NOT @hubspot/divider. Different module; HubSpot won't render the wrong one.
    FOOTER_DIV = "staging_footer_divider"
    widgets[FOOTER_DIV] = {
        "type": "module",
        "body": {
            "path":      "@hubspot/email_divider",
            "module_id": 2191110,
            "line_type": "solid",
            "color":     {"color": "#000000", "opacity": 100},
            "height":    1,
            "width":     100,
            "hs_enable_module_padding": True,
            "hs_wrapper_css": {
                "padding-bottom": "10px",
                "padding-left":   "20px",
                "padding-right":  "20px",
                "padding-top":    "5px",
            },
        },
    }
    sections.append({
        "id":      "section-footer-divider",
        "columns": [{"id": "col-footer-div-0", "widgets": [FOOTER_DIV], "width": 12}],
        "path":    None,
        "style":   _section_style,
    })

    # "FOLLOW US" heading above social icons
    FOOTER_FOLLOW_HDR = "staging_footer_follow_header"
    widgets[FOOTER_FOLLOW_HDR] = {
        "type": "module",
        "body": {
            "path":      "@hubspot/rich_text",
            "module_id": 1155639,
            "html":      '<p style="font-weight: bold; text-align: center;">FOLLOW US</p>',
            "hs_enable_module_padding": False,
            "hs_wrapper_css": {},
        },
    }
    sections.append({
        "id":      "section-footer-follow-header",
        "columns": [{"id": "col-footer-fhdr-0", "widgets": [FOOTER_FOLLOW_HDR], "width": 12}],
        "path":    None,
        "style":   _section_style,
    })

    # Social icons — module_id 2763545 is required; without it HubSpot cannot
    # resolve the follow_me_email module and renders nothing.
    # color_scheme and icon_shape must be non-empty strings, not "".
    # LFX icon entry requires network_image dict with CDN-hosted src.
    FOOTER_SOCIAL = "staging_footer_social"
    widgets[FOOTER_SOCIAL] = {
        "type": "module",
        "body": {
            "path":         "@hubspot/follow_me_email",
            "module_id":    2763545,
            "color_scheme": "black",
            "icon_shape":   "circle",
            "font_style": {
                "color":  "#000000",
                "font":   "Helvetica,Arial,sans-serif",
                "size":   {"units": "px", "value": 14},
                "styles": {"bold": True, "italic": False, "underline": False},
            },
            "hs_enable_module_padding": False,
            "hs_wrapper_css": {},
            "social": [
                {
                    "network": "icon",
                    "network_image": {
                        "alt":    "LFX Insights",
                        "height": 675,
                        "src":    "https://8112310.fs1.hubspotusercontent-na1.net/hubfs/8112310/LFX%20Logo%20-%20white%20-%203-1.png",
                        "width":  1536,
                    },
                    "url": (
                        "https://insights.linuxfoundation.org/"
                        "?utm_campaign=23551824-Q3-2025-LF-Awareness-LFX-Insights"
                        "&utm_source=email&utm_medium=LF-Events&utm_content=regular-email"
                    ),
                },
                {"network": "twitter",  "url": "https://twitter.com/linuxfoundation"},
                {"network": "linkedin", "url": "https://www.linkedin.com/company/the-linux-foundation/"},
                {"network": "youtube",  "url": "https://www.youtube.com/user/TheLinuxFoundation"},
                {"network": "facebook", "url": "https://www.facebook.com/TheLinuxFoundation/"},
            ],
        },
    }
    sections.append({
        "id":      "section-footer-social",
        "columns": [{"id": "col-footer-soc-0", "widgets": [FOOTER_SOCIAL], "width": 12}],
        "path":    None,
        "style":   _section_style,
    })

    # "Sent by" attribution text
    FOOTER_BODY = "staging_footer_body"
    widgets[FOOTER_BODY] = {
        "type": "module",
        "body": {
            "path":      "@hubspot/rich_text",
            "module_id": 1155639,
            "html": (
                '<h2 style="font-size:8px;line-height:175%;font-weight:normal;text-align:center;">'
                '<span style="font-size:12px;color:#000000;">'
                'This email was sent by: '
                '<span style="font-weight:normal;">The Linux Foundation Events</span>'
                '</span></h2>'
            ),
            "hs_enable_module_padding": True,
            "hs_wrapper_css": {
                "padding-bottom": "0px",
                "padding-left":   "20px",
                "padding-right":  "20px",
                "padding-top":    "0px",
            },
        },
    }
    sections.append({
        "id":      "section-footer-body",
        "columns": [{"id": "col-footer-body-0", "widgets": [FOOTER_BODY], "width": 12}],
        "path":    None,
        "style":   _section_style,
    })

    # Native HubSpot email footer module — module_id 2869621 handles the
    # unsubscribe link, physical address, and CAN-SPAM compliance automatically.
    FOOTER_HS = "staging_footer_hs"
    widgets[FOOTER_HS] = {
        "type": "module",
        "body": {
            "path":      "@hubspot/email_footer",
            "module_id": 2869621,
            "font": {
                "color":  "#000000",
                "font":   "Arial, sans-serif",
                "size":   {"units": "px", "value": 12},
                "styles": {"bold": False, "italic": False, "underline": False},
            },
            "link_font": {
                "color":    "#0094ff",
                "font":     "Arial, sans-serif",
                "font_set": "DEFAULT",
                "size":     {"units": "px", "value": 12},
                "styles":   {"bold": False, "italic": False, "underline": True},
            },
            "hs_enable_module_padding": False,
            "hs_wrapper_css": {},
        },
    }
    sections.append({
        "id":      "section-footer-hs",
        "columns": [{"id": "col-footer-hs-0", "widgets": [FOOTER_HS], "width": 12}],
        "path":    None,
        "style":   _section_style,
    })

    if preview_text_widget:
        widgets["preview_text"] = preview_text_widget

    flex_areas: dict = {
        flex_area_name: {
            "boxFirstElementIndex": None,
            "boxLastElementIndex":  None,
            "boxed":                False,
            "isSingleColumnFullWidth": False,
            "sections": sections,
        }
    }

    new_content: dict = {
        "templatePath": template_path,
        "widgets":      widgets,
        "flexAreas":    flex_areas,
    }
    if style_settings:
        new_content["styleSettings"] = style_settings

    _patch(f"/marketing/v3/emails/{email_id}", {"content": new_content})
    if content_sections:
        method = f"structured({len(content_sections)} sections, {len(sponsors or [])} sponsors)"
    else:
        method = "image+rich_text" if banner_url else "rich_text_only"
    log.info(f"[CONTENT] patched OK method={method!r} widgets={len(sections)}")
    return {"success": True, "email_id": email_id, "method": method}


# ── Image upload helper ──────────────────────────────────────────────────────

def upload_image_to_hubspot(image_url: str, filename: str = "") -> str:
    """
    Download an image from `image_url` and re-host it in HubSpot file manager.
    Returns the HubSpot CDN URL, or empty string if the upload fails.
    Using HubSpot-hosted URLs ensures images load reliably in email clients.
    """
    import io
    import logging
    from urllib.parse import urlparse

    log = logging.getLogger("email-staging")
    if not image_url or not HUBSPOT_ACCESS_TOKEN:
        return ""

    try:
        # Download the source image
        dl = requests.get(
            image_url, timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        dl.raise_for_status()

        content_type = dl.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if not content_type.startswith("image/"):
            log.warning(f"[IMAGE] not an image ({content_type!r}): {image_url}")
            return ""

        # Derive a safe filename
        if not filename:
            raw = urlparse(image_url).path.rsplit("/", 1)[-1].split("?")[0]
            if not raw or "." not in raw:
                ext = content_type.split("/")[-1].replace("jpeg", "jpg") or "jpg"
                raw = f"email_img.{ext}"
            filename = raw[:80]

        # Upload to HubSpot Files API v3 (multipart — NOT JSON)
        up = requests.post(
            "https://api.hubapi.com/files/v3/files",
            headers={"Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}"},
            files={"file": (filename, io.BytesIO(dl.content), content_type)},
            data={
                "options": '{"access":"PUBLIC_INDEXABLE","overwrite":true}',
                "folderPath": "/email-staging",
            },
            timeout=30,
        )
        up.raise_for_status()
        cdn_url = up.json().get("url", "")
        log.info(f"[IMAGE] uploaded {filename!r} → {cdn_url!r}")
        return cdn_url

    except Exception as exc:
        log.warning(f"[IMAGE] upload failed ({image_url!r}): {exc}")
        return ""


# ── Tool 5: Search contact lists ────────────────────────────────────────────

def search_hubspot_lists(search_term: str) -> dict:
    """Search HubSpot contact lists by name."""
    return search_lists(search_term)
