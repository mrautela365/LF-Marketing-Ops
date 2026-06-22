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


def get_brand_emails(short_brand_name: str, brand_name: str,
                     event_short_names: list = None, limit_per_call: int = 20) -> list:
    """
    Fetch 30-40 published emails for a brand by searching across multiple terms:
      1. short_brand_name  (e.g. "AIF", "CNCF") — matches new "26QN - AIF - ..." naming
      2. Each event_short_name from the brand's full event list in BRAND_MAP
      3. brand_name fallback if results are still thin

    Results are deduplicated by email ID and sorted newest-first.
    """
    seen: set = set()
    all_emails: list = []

    def _fetch_and_add(filt: str) -> None:
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

    # Primary: brand short code (catches all new-style emails)
    _fetch_and_add(short_brand_name)

    # Expand: each known event short name for this brand
    for esn in (event_short_names or []):
        _fetch_and_add(esn)

    # Fallback: full brand name (catches older naming conventions)
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

    # HubSpot stores send/suppression lists in contactIlsLists (v3 ILS) and/or
    # contactLists (legacy). We write to both so the setting lands regardless of
    # which format the receiving email expects.
    if send_list_id or suppression_list_ids is not None:
        ils: dict = {}
        legacy: dict = {}
        if send_list_id:
            ils["include"]    = [str(send_list_id)]
            legacy["include"] = [int(send_list_id)]
        if suppression_list_ids is not None:
            ils["exclude"]    = [str(s) for s in suppression_list_ids]
            legacy["exclude"] = [int(s) for s in suppression_list_ids if str(s).isdigit()]
        payload["to"] = {
            "contactIlsLists": ils,
            "contactLists":    legacy,
        }

    _patch(f"/marketing/v3/emails/{email_id}", payload)
    return {"success": True, "email_id": email_id, "fields_updated": list(payload.keys())}


# ── Tool 4: Update email body content ───────────────────────────────────────

def update_email_content(
    email_id: str,
    html_content: str,
    banner_url: str = "",
    event_url: str = "",
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
            },
        }
        sections.append({
            "id":      "section-staging-banner",
            "columns": [{"id": "col-banner-0", "widgets": [BANNER], "width": 12}],
            "path":    None,
            "style":   _section_style,
        })
        log.info(f"[CONTENT] banner widget added: {banner_url!r}")

    # Body rich-text
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
    method = "image+rich_text" if banner_url else "rich_text_only"
    log.info(f"[CONTENT] patched OK method={method!r} sections={len(sections)}")
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
