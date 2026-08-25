"""
Find the actual list(s) used in the last real send for an event — a
deterministic (non-LLM) "direct reuse" lookup, complementary to the agentic
discovery flow.

Ported/adapted from emailcreationskill/backend/audience_builder/last_sent.py.
Adapted to this project's module layout: `import audience_tools` -> calls into
`audience_builder.tools` (search_emails/search_lists) and `integrations.hubspot`
(legacy_v1_list_name) directly, since audience_tools.py does not exist here.
"""
import re
from typing import Optional

from audience_builder import tools as abt
from config import HUBSPOT_PORTAL_ID
from integrations import hubspot as hs

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at",
    "by", "with", "is", "are", "summit", "conference", "event",
}
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _keywords(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _strip_year(text: str) -> str:
    """Strip 4-digit years so name__icontains search still matches an email
    named for a different edition/year of the same event."""
    return _YEAR_RE.sub("", text or "").strip()


def _legacy_v1_list_name(list_id: str) -> Optional[str]:
    return hs.legacy_v1_list_name(list_id)


def _resolve_list_brief(list_id: str, cache: dict) -> dict:
    """Resolve a list ID (as frozen into an old email's to.contactLists/
    to.contactIlsLists) to a name/size brief. Falls back to the legacy v1
    endpoint, then a v3 name search re-match, on a 404 (renumbered list)."""
    list_id = str(list_id)
    if list_id in cache:
        return cache[list_id]

    brief: dict
    try:
        data = abt.hubspot_get_list(list_id)
        list_obj = data.get("list", data)
        brief = {
            "list_id": list_id,
            "name": list_obj.get("name") or f"List {list_id}",
            "size": (list_obj.get("additionalProperties") or {}).get("hs_list_size") or list_obj.get("size"),
            "missing": False,
        }
    except Exception:
        legacy_name = _legacy_v1_list_name(list_id)
        if legacy_name:
            rematch = abt.hubspot_search_lists(legacy_name)
            results = rematch.get("results", [])
            current = next((r for r in results if r.get("name") == legacy_name), None)
            brief = {
                "list_id": str(current["listId"]) if current and current.get("listId") else list_id,
                "name": legacy_name,
                "size": current.get("size") if current else None,
                "missing": False,
            }
        else:
            brief = {"list_id": list_id, "name": None, "size": None, "missing": True}

    cache[list_id] = brief
    return brief


def _dedupe_briefs(briefs: list) -> list:
    seen = set()
    out = []
    for b in briefs:
        key = b.get("list_id")
        if key and key not in seen:
            seen.add(key)
            out.append(b)
    return out


def find_last_sent_emails(event_name: str, brand_short: str = "", limit: int = 3) -> list:
    """Find the most recent PUBLISHED marketing email(s) that match this
    event, and resolve which lists they were actually sent to / suppressed
    against. Returns up to `limit` emails, most recent first."""
    if not event_name:
        raise ValueError("event_name is required")

    search_term = _strip_year(event_name) or event_name
    raw = abt.hubspot_search_emails_raw(search_term, limit=30)
    published = [e for e in raw if e.get("state") == "PUBLISHED"]

    if not published and brand_short:
        raw = abt.hubspot_search_emails_raw(brand_short, limit=30)
        published = [e for e in raw if e.get("state") == "PUBLISHED"]

    if not published:
        return []

    target_kw = _keywords(event_name) | _keywords(brand_short)

    def _score(e: dict) -> tuple:
        name = e.get("name") or ""
        overlap = len(target_kw & _keywords(name))
        return (overlap, e.get("publishDate") or 0)

    published.sort(key=_score, reverse=True)

    cache: dict = {}
    out = []
    for email in published[:limit]:
        to = email.get("to") or {}
        include_ids = list(to.get("contactLists") or [])
        exclude_ids = list(to.get("contactIlsLists") or [])

        included = _dedupe_briefs([_resolve_list_brief(lid, cache) for lid in include_ids])
        suppressed = _dedupe_briefs([_resolve_list_brief(lid, cache) for lid in exclude_ids])

        out.append({
            "email_id": email.get("id"),
            "email_name": email.get("name"),
            "sent_at": email.get("publishDate"),
            "hubspot_url": f"https://app.hubspot.com/email/{HUBSPOT_PORTAL_ID}/edit/{email.get('id')}/settings",
            "included_lists": included,
            "suppression_lists": suppressed,
        })

    return out
