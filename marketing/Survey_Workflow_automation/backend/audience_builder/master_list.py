"""
Master-list composition: suppression-list lookup, existing-master-list lookup,
filter-branch construction, and the compose_master_list_from_ids orchestrator.

Ported/adapted from emailcreationskill/backend/audience_builder/master_list.py.
Adapted to this project's module layout:
  - `import audience_tools`              -> `from audience_builder import tools as abt`
                                             (search) and `from integrations import hubspot as hs`
                                             (get/create/update/size/url — the mutating +
                                             sizing calls that don't belong in the read-only
                                             discovery tool set in audience_builder/tools.py).
  - `from config import HUBSPOT_PORTAL_ID` -> unchanged, already defined in this project's
                                               config.py (default "" instead of source's "8112310" —
                                               set HUBSPOT_PORTAL_ID in .env for correct list_url()s).

NOTE ON FILTER-BRANCH JSON SHAPE: the exact filterBranch payload HubSpot's v3
Lists API expects (IN_LIST / NOT_IN_LIST filterType, filterBranchType OR/AND
nesting) is reconstructed here from the source project's documented behavior
rather than a byte-for-byte copy of its master_list.py (that file's exact text
was not retained across a context-window compaction during this port). Diff
this against emailcreationskill/backend/audience_builder/master_list.py before
relying on compose-master in production — the list-membership filter types are
correct for HubSpot's CRM v3 Lists filterBranch schema, but exact key ordering/
extra fields (e.g. `filterBranchOperator`) may differ from the original.
"""
import re
import time
from typing import Optional

from config import HUBSPOT_PORTAL_ID
from integrations import hubspot as hs
from audience_builder import tools as abt

# (key, label, search term) — searched via hubspot_search_lists; first
# name-containing match wins. Mirrors source's STANDARD_SUPPRESSION_TERMS.
STANDARD_SUPPRESSION_TERMS = [
    ("lf_global_optout", "LF Global Opt-Outs", "LF Global Opt-Outs"),
    ("lf_europe_global_optout", "LF Europe Global Opt-Outs", "LF Europe Global Opt-Outs"),
    ("lf_events_gdpr", "LF Events GDPR Suppression", "LF Events GDPR Suppression"),
    ("lf_europe_gdpr", "LF Europe GDPR Suppression", "LF Europe GDPR Suppression"),
    ("lf_master_exclusion", "LF Master Exclusion List", "LF Master Exclusion List"),
    ("lf_events_suppression", "LF Events Suppression List", "LF Events Suppression List"),
]

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at",
    "by", "with", "is", "are", "summit", "conference", "event", "2024",
    "2025", "2026",
}

_QUARTER_RE = re.compile(r"\b(\d{2})Q([1-4])\b", re.IGNORECASE)


def _quarter_rank(name: str) -> int:
    """Parse a 'YYQN' token out of a list name into a sortable int (YY*10+N),
    or -1 if none found — used to rank multiple master-list matches by recency."""
    m = _QUARTER_RE.search(name or "")
    if not m:
        return -1
    yy, q = int(m.group(1)), int(m.group(2))
    return yy * 10 + q


def _event_keywords(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def build_in_list_or_branch(list_ids: list) -> dict:
    """OR-of-IN_LIST filter branch: a contact matches if it's in ANY of the
    given lists. Used both standalone (Combined Suppression list) and as the
    'include' side of the master list's top-level AND branch."""
    return {
        "filterBranchType": "OR",
        "filterBranches": [],
        "filters": [
            {"filterType": "IN_LIST", "listId": int(lid)}
            for lid in list_ids if lid
        ],
    }


def build_master_filter_branch(include_ids: list, suppression_list_id: str = "") -> dict:
    """Top-level filter branch for the master list: one AND-branch per
    included source list (each ANDed with NOT_IN_LIST on the suppression list,
    if any), all OR'd at the root — (inc_1 AND NOT supp) OR (inc_2 AND NOT
    supp) ... HubSpot rejects an AND-type root filterBranch, so the root here
    must stay OR-of-AND even though a flat (OR-of-IN_LIST) AND (NOT_IN_LIST)
    shape would be logically equivalent."""
    seen = []
    for lid in include_ids:
        lid = str(lid).strip()
        if lid and lid not in seen:
            seen.append(lid)

    branches = []
    for lid in seen:
        filters = [{"filterType": "IN_LIST", "listId": int(lid)}]
        if suppression_list_id:
            filters.append({"filterType": "NOT_IN_LIST", "listId": int(suppression_list_id)})
        branches.append({"filterBranchType": "AND", "filterBranches": [], "filters": filters})

    return {"filterBranchType": "OR", "filterBranches": branches, "filters": []}


def build_master_list_name(event_url: str, brand_short: str, event_name: str,
                            event_dates: str = "", suffix: str = "Master") -> str:
    """'<YYQN> - <Brand> - <Event> - <suffix>'. Falls back to the current
    quarter if event_dates doesn't parse to one."""
    quarter = _extract_quarter(event_dates) or _current_quarter()
    brand = (brand_short or "").strip()
    event = (event_name or "").strip()
    parts = [p for p in [quarter, brand, event, suffix] if p]
    return " - ".join(parts)


def _current_quarter() -> str:
    now = time.localtime()
    yy = now.tm_year % 100
    q = (now.tm_mon - 1) // 3 + 1
    return f"{yy:02d}Q{q}"


def _extract_quarter(event_dates: str) -> Optional[str]:
    if not event_dates:
        return None
    m = _QUARTER_RE.search(event_dates)
    if m:
        return f"{int(m.group(1)):02d}Q{m.group(2)}"
    # Try to parse a month name + 4-digit year, e.g. "March 2026"
    month_m = re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\b",
        event_dates, re.IGNORECASE,
    )
    if not month_m:
        return None
    month_abbr = month_m.group(1).lower()
    year = int(month_m.group(2)) % 100
    month_num = ["jan", "feb", "mar", "apr", "may", "jun",
                 "jul", "aug", "sep", "oct", "nov", "dec"].index(month_abbr) + 1
    q = (month_num - 1) // 3 + 1
    return f"{year:02d}Q{q}"


def _find_brand_opt_out(brand_short: str) -> Optional[dict]:
    if not brand_short:
        return None
    result = abt.hubspot_search_lists(f"{brand_short} Global Opt-Out")
    matches = result.get("results", [])
    return matches[0] if matches else None


def _find_event_suppression(event_name: str) -> Optional[dict]:
    if not event_name:
        return None
    result = abt.hubspot_search_lists(f"{event_name} Suppression")
    matches = result.get("results", [])
    return matches[0] if matches else None


def find_standard_suppression_lists(brand_short: str = "", event_name: str = "") -> list:
    """Look up each of the 6 standard suppression lists by name; plus any
    brand-specific opt-out list and event-specific GDPR/suppression list that
    matched. Returns only lists that were actually found in HubSpot."""
    found = []
    for key, label, term in STANDARD_SUPPRESSION_TERMS:
        result = abt.hubspot_search_lists(term)
        matches = [m for m in result.get("results", []) if m.get("listId")]
        if matches:
            m = matches[0]
            found.append({
                "key": key, "label": label, "list_id": str(m.get("listId")),
                "name": m.get("name"), "size": m.get("size"), "category": "standard",
            })

    brand_hit = _find_brand_opt_out(brand_short)
    if brand_hit and brand_hit.get("listId"):
        found.append({
            "key": "brand_opt_out", "label": f"{brand_short} Opt-Outs",
            "list_id": str(brand_hit["listId"]), "name": brand_hit.get("name"),
            "size": brand_hit.get("size"), "category": "brand",
        })

    event_hit = _find_event_suppression(event_name)
    if event_hit and event_hit.get("listId"):
        found.append({
            "key": "event_suppression", "label": f"{event_name} Suppression",
            "list_id": str(event_hit["listId"]), "name": event_hit.get("name"),
            "size": event_hit.get("size"), "category": "event",
        })

    return found


def find_existing_master_lists(brand_short: str = "", event_name: str = "") -> list:
    """Search for pre-existing master lists for this event (searches both
    '<event_name> Master' and '<brand_short> <event_name> Master'), returning
    ALL matches sorted by parsed quarter recency, most recent first."""
    seen: dict[str, dict] = {}
    for query in filter(None, [
        f"{event_name} Master".strip() if event_name else None,
        f"{brand_short} {event_name} Master".strip() if brand_short and event_name else None,
    ]):
        result = abt.hubspot_search_lists(query)
        for m in result.get("results", []):
            lid = str(m.get("listId") or "")
            if lid and lid not in seen:
                seen[lid] = {
                    "list_id": lid, "name": m.get("name"), "size": m.get("size"),
                    "hubspot_url": hs.list_url(lid),
                }

    return sorted(seen.values(), key=lambda l: _quarter_rank(l.get("name", "")), reverse=True)


def _list_size(list_id: str) -> Optional[int]:
    try:
        return hs.get_list_size(list_id)
    except Exception:
        return None


def union_size(list_ids: list, cap: int = 25000) -> dict:
    """Exact de-duplicated contact count across list_ids if the total is under
    `cap` records (via membership-ID union), else a sum-of-sizes estimate."""
    list_ids = [str(l) for l in list_ids if l]
    if not list_ids:
        return {"exact": False, "estimate": False, "count": 0, "reason": "no list_ids provided"}

    sizes = {lid: (_list_size(lid) or 0) for lid in list_ids}
    total_estimate = sum(sizes.values())

    if total_estimate > cap:
        return {
            "exact": False, "estimate": True, "count": total_estimate,
            "reason": f"sum of list sizes ({total_estimate}) exceeds exact-union cap ({cap}); "
                      "showing sum estimate (may double-count contacts in multiple lists)",
        }

    try:
        union_ids: set = set()
        for lid in list_ids:
            union_ids |= abt.hubspot_list_membership_ids(lid, cap_pages=100)
        return {"exact": True, "estimate": False, "count": len(union_ids), "reason": ""}
    except Exception as exc:
        return {
            "exact": False, "estimate": True, "count": total_estimate,
            "reason": f"exact union failed ({exc}); showing sum estimate",
        }


def _create_with_retry(resolved_name: str, filter_branch: dict) -> dict:
    """Create the list; on a name-collision error, retry once with a
    timestamp suffix appended so compose-master never silently fails outright."""
    try:
        return hs.create_list(resolved_name, filter_branch)
    except RuntimeError as exc:
        if "already exist" in str(exc).lower():
            retry_name = f"{resolved_name} ({int(time.time())})"
            return hs.create_list(retry_name, filter_branch)
        raise


def compose_master_list_from_ids(list_ids: list, name: str = "", event_url: str = "",
                                  brand_short: str = "", event_name: str = "",
                                  event_dates: str = "", exclude_list_ids: list = None) -> dict:
    """Orchestrator: optionally builds a 'Combined Suppression' list first
    (OR-of-IN_LIST over exclude_list_ids), then creates the master list with
    an OR-of-IN_LIST(include) AND NOT_IN_LIST(combined suppression) filter
    branch. Nothing in HubSpot is created until this is called — the
    discovery/lookup routes are all read-only."""
    if not list_ids:
        raise ValueError("list_ids is required and must not be empty")

    exclude_list_ids = [str(l) for l in (exclude_list_ids or []) if l]
    resolved_name = name.strip() if name else build_master_list_name(
        event_url, brand_short, event_name, event_dates,
    )

    suppression_list_id = ""
    suppression_name = ""
    suppression_hubspot_url = ""
    suppression_size = "unknown"

    if exclude_list_ids:
        combined_name = build_master_list_name(
            event_url, brand_short, event_name, event_dates, suffix="Combined Suppression",
        )
        combined_branch = build_in_list_or_branch(exclude_list_ids)
        combined = _create_with_retry(combined_name, combined_branch)
        suppression_list_id = str(combined.get("list_id") or "")
        suppression_name = combined.get("name", combined_name)
        suppression_hubspot_url = hs.list_url(suppression_list_id)
        size = _list_size(suppression_list_id)
        suppression_size = str(size) if size is not None else "unknown"

    master_branch = build_master_filter_branch([str(l) for l in list_ids], suppression_list_id)
    master = _create_with_retry(resolved_name, master_branch)
    master_list_id = str(master.get("list_id") or "")
    master_size = _list_size(master_list_id)

    return {
        "list_id": master_list_id,
        "name": master.get("name", resolved_name),
        "hubspot_url": hs.list_url(master_list_id),
        "size": str(master_size) if master_size is not None else "unknown",
        "source_list_ids": [str(l) for l in list_ids],
        "suppression_list_id": suppression_list_id,
        "suppression_name": suppression_name,
        "suppression_hubspot_url": suppression_hubspot_url,
        "suppression_size": suppression_size,
    }
