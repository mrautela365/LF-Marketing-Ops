"""
Deterministic (non-LLM) "what was sent last time" lookup for the Audience
Builder tab. Reuses the same /marketing/v3/emails list-search endpoint as
hubspot_tools.lookup_brand_history. The include/exclude list IDs live under
each email's `to.contactLists` (static/manual lists) and `to.contactIlsLists`
(active/dynamic lists) — NOT a top-level `sendOptions` field (that field does
not exist on either the list-search or single-email-GET response; confirmed
against live HubSpot data) — so both are read directly off these list-search
results with no extra per-email GET needed.
"""
import re

import requests

import audience_tools
from config import HUBSPOT_PORTAL_ID

_STOPWORDS = {"the", "a", "an", "and", "of", "for", "in", "on", "to"}
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in _STOPWORDS}


def _strip_year(text: str) -> str:
    """Drop a trailing/embedded 4-digit year, e.g. 'MCP Dev Summit Seoul 2026' ->
    'MCP Dev Summit Seoul'. The discovery agent often appends the event's year
    to event_name, which breaks HubSpot's name__icontains search since most
    email names for an event don't repeat the year literally."""
    stripped = _YEAR_RE.sub("", text or "")
    return re.sub(r"\s+", " ", stripped).strip()


def _legacy_v1_list_name(list_id: str) -> str | None:
    """Fall back to the legacy /contacts/v1/lists endpoint when a list ID
    404s on v3. Confirmed against live data: a marketing email's frozen
    include/exclude list ID (e.g. 18087) can 404 on crm/v3/lists while the
    SAME list still resolves via the legacy v1 endpoint — HubSpot carries the
    list forward under a new v3 listId (e.g. 26783) when it's rebuilt/
    migrated, but the old numeric ID keeps resolving only through v1. The v1
    record's `name` is what we use to re-locate the list's current v3 ID."""
    try:
        r = requests.get(
            f"{audience_tools._HS_BASE}/contacts/v1/lists/{list_id}",
            headers=audience_tools._hs_headers(), timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("name") if not data.get("deleted") else None
    except Exception:
        return None


def _resolve_list_brief(list_id, cache: dict) -> dict:
    """Resolve a list ID referenced on a past send to {list_id, name, size}.

    The email's `to.contactLists`/`to.contactIlsLists` fields freeze whatever
    list ID was attached at send time. When that ID 404s on v3, it usually
    isn't gone — it's the old (v1) numbering for a list HubSpot has since
    carried forward under a new v3 listId. We recover the live v3 list via
    the legacy v1 endpoint (for the name) + a v3 name search (for the current
    ID/size), and only fall back to `missing: True` if that recovery fails
    too — i.e. the list is actually gone, not just renumbered."""
    list_id = str(list_id)
    if list_id in cache:
        return cache[list_id]

    try:
        raw = audience_tools.hubspot_get_list(list_id)
        info = raw.get("list", raw)
        brief = {"list_id": list_id, "name": info.get("name") or list_id, "size": info.get("size"), "missing": False}
        cache[list_id] = brief
        return brief
    except requests.exceptions.HTTPError as exc:
        if exc.response is None or exc.response.status_code != 404:
            brief = {"list_id": list_id, "name": f"List {list_id} (lookup failed)", "size": None, "missing": True}
            cache[list_id] = brief
            return brief
    except Exception:
        brief = {"list_id": list_id, "name": f"List {list_id} (lookup failed)", "size": None, "missing": True}
        cache[list_id] = brief
        return brief

    # v3 404 — try the legacy-ID recovery path before giving up.
    legacy_name = _legacy_v1_list_name(list_id)
    if legacy_name:
        try:
            search = audience_tools.hubspot_search_lists(legacy_name)
            match = next((r for r in search.get("results", []) if r.get("name") == legacy_name), None)
        except Exception:
            match = None
        if match and match.get("listId"):
            brief = {
                "list_id": str(match["listId"]), "name": match["name"], "size": match.get("size"),
                "missing": False, "resolved_from_legacy_id": list_id,
            }
            cache[list_id] = brief
            return brief
        brief = {
            "list_id": list_id,
            "name": f'"{legacy_name}" (renumbered in HubSpot; original ID {list_id} could not be re-matched)',
            "size": None, "missing": True,
        }
        cache[list_id] = brief
        return brief

    brief = {"list_id": list_id, "name": f"List {list_id} (no longer exists in HubSpot)", "size": None, "missing": True}
    cache[list_id] = brief
    return brief


def find_last_sent_emails(event_name: str = "", brand_short: str = "", limit: int = 3) -> list[dict]:
    """Up to `limit` most-recently-published marketing emails whose name
    references this event, sorted by publishDate desc, with each email's
    included/suppression list IDs resolved to {list_id, name, size}.

    Searches by event_name first (server-side name__icontains, same pattern
    as lookup_brand_history), falling back to brand_short if that comes back
    empty — event names are often abbreviated differently across editions, so
    results are additionally ranked by keyword overlap rather than trusted
    on substring match alone."""
    term = (event_name or brand_short or "").strip()
    if not term:
        return []

    search_term = _strip_year(term) or term
    raw = audience_tools.hubspot_search_emails_raw(search_term, limit=30)
    published = [e for e in raw if e.get("state") == "PUBLISHED"]

    # Retry with brand_short whenever the primary term yields no *published*
    # candidate, not only when it yields none at all — a term can still match
    # a stray AUTOMATED/DRAFT email (e.g. a travel-fund approval notice) while
    # missing every real campaign send.
    if not published and brand_short and brand_short.strip().lower() != search_term.lower():
        raw = audience_tools.hubspot_search_emails_raw(brand_short.strip(), limit=30)
        published = [e for e in raw if e.get("state") == "PUBLISHED"]

    query_kw = _keywords(event_name) | _keywords(brand_short)
    if query_kw:
        scored = [(len(query_kw & _keywords(e.get("name", ""))), e) for e in published]
        matched = [pair for pair in scored if pair[0] > 0]
        candidates = matched if matched else [(0, e) for e in published]
    else:
        candidates = [(0, e) for e in published]

    # hubspot_search_emails_raw already sorts -publishDate server-side;
    # a stable sort on keyword score alone preserves that as the tiebreak.
    candidates.sort(key=lambda pair: pair[0], reverse=True)

    cache: dict = {}
    results = []
    for _, e in candidates[:limit]:
        to = e.get("to") or {}
        static_lists = to.get("contactLists") or {}
        active_lists = to.get("contactIlsLists") or {}
        included_ids = list(static_lists.get("include") or []) + list(active_lists.get("include") or [])
        excluded_ids = list(static_lists.get("exclude") or []) + list(active_lists.get("exclude") or [])
        email_id = e.get("id")
        results.append({
            "email_id": email_id,
            "email_name": e.get("name"),
            "sent_at": e.get("publishDate") or e.get("updatedAt"),
            "hubspot_url": (
                f"https://app.hubspot.com/email/{HUBSPOT_PORTAL_ID}/edit/{email_id}"
                if email_id else ""
            ),
            "included_lists": [_resolve_list_brief(lid, cache) for lid in included_ids],
            "suppression_lists": [_resolve_list_brief(lid, cache) for lid in excluded_ids],
        })
    return results
