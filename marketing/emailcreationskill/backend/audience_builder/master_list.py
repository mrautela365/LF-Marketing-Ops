"""
Composes a single "master" HubSpot list from a set of already-existing list IDs
selected in the Audience Builder tab, via an OR-of-IN_LIST filterBranch.

Reuses audience_tools.hubspot_create_list/hubspot_update_list_filters for the
actual HubSpot writes — those already apply FilterOptimizer and
config.tag_asset_name(); nothing here talks to HubSpot directly.
"""
import datetime
import re

import audience_tools
from config import HUBSPOT_PORTAL_ID


def build_in_list_or_branch(list_ids: list[str]) -> dict:
    """One AND-branch per de-duplicated list ID, all OR'd together.

    FilterOptimizer explicitly skips IN_LIST branches (see
    FilterOptimizer._is_eligible_for_combination), so passing this through
    hubspot_create_list's optimization pass never collapses or reorders these.
    """
    seen: list[str] = []
    for lid in list_ids:
        lid = str(lid).strip()
        if lid and lid not in seen:
            seen.append(lid)

    return {
        "filterBranchType": "OR",
        "filterBranches": [
            {
                "filterBranchType": "AND",
                "filterBranches": [],
                "filters": [
                    {"filterType": "IN_LIST", "listId": lid, "operator": "IN_LIST"}
                ],
            }
            for lid in seen
        ],
        "filters": [],
    }


def build_master_list_name(event_url: str = "", brand_short: str = "", event_name: str = "",
                            event_dates: list[str] | None = None, suffix: str = "Master") -> str:
    """`<YYQN> - <Brand> - <Event> - <suffix>`, matching the convention already
    established in audience_tools.PLANNING_PROMPT_TEMPLATE and main.py's
    _build_email_name(). Falls back to today's quarter / a generic body when
    brand/event/dates aren't available."""
    yyq = ""
    for ds in (event_dates or []):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(ds))
        if m:
            yyq = f"{int(m.group(1)) % 100:02d}Q{(int(m.group(2)) - 1) // 3 + 1}"
            break
    if not yyq:
        today = datetime.date.today()
        yyq = f"{today.year % 100:02d}Q{(today.month - 1) // 3 + 1}"

    parts = [p for p in (brand_short, event_name) if p]
    body = " - ".join(parts) if parts else "Audience"
    return f"{yyq} - {body} - {suffix}"


# Standard hygiene suppression lists, matching the search terms in
# audience_tools.PLANNING_PROMPT_TEMPLATE STEP 5. Each is resolved via
# hubspot_search_lists(term) — take the most recently updated (highest
# quarter-code) match, since these are recreated every quarter/year.
STANDARD_SUPPRESSION_TERMS = [
    ("lf_global_opt_outs", "LF Global Opt-Outs", "LF Global Opt-Outs"),
    ("lf_europe_global_opt_outs", "LF Europe Global Opt-Outs", "LF Europe Global Opt-Outs"),
    ("lf_events_gdpr", "LF Events GDPR Suppression", "LF Events GDPR Suppression"),
    ("lf_europe_gdpr", "LF Europe GDPR Suppression", "LF Europe GDPR Suppression"),
    ("lf_master_exclusion", "LF Master Exclusion List", "LF Master Exclusion"),
    ("lf_events_suppression", "LF Events Suppression List", "LF Events Suppression List"),
]


def _quarter_rank(name: str) -> tuple[int, int]:
    """Extracts a `YYQN` code from a list name for recency ranking (e.g. "25Q2"
    ranks above "24Q1"). Names with no quarter code rank lowest but are still
    eligible if they're the only match for their category."""
    m = re.search(r"(\d{2})Q([1-4])", name or "", re.IGNORECASE)
    if not m:
        return (-1, -1)
    return (int(m.group(1)), int(m.group(2)))


_STOPWORDS = {"the", "a", "an", "and", "of", "for", "in", "on", "to"}


def _event_keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in _STOPWORDS}


def _find_brand_opt_out(brand_short: str) -> dict | None:
    """Each project/brand often has its OWN "Global Opt Out" list distinct from
    the portfolio-wide "LF Global Opt-Outs" — confirmed via live HubSpot search:
    CNCF Global Opt Out, Hyperledger Global Opt Out, OpenSSF Global Opt Out,
    Pytorch Global Opt-Outs, and LFN Global Opt Outs all exist as separate
    lists. Not covered by STANDARD_SUPPRESSION_TERMS since it's brand-scoped."""
    if not brand_short:
        return None
    try:
        results = audience_tools.hubspot_search_lists(f"{brand_short} Global Opt")
    except Exception:
        return None
    candidates = [
        r for r in results.get("results", [])
        if r.get("listId")
        and brand_short.lower() in (r.get("name") or "").lower()
        and "opt" in (r.get("name") or "").lower()
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda r: (_quarter_rank(r.get("name", "")), r.get("size") or 0))
    return {
        "key": f"brand_opt_out_{brand_short.lower()}",
        "label": f"{brand_short} Global Opt-Out",
        "list_id": str(best["listId"]),
        "name": best.get("name", ""),
        "size": best.get("size"),
        "category": "brand",
    }


def _find_event_suppression(event_name: str) -> dict | None:
    """Recurring LF events often already have a dedicated per-event suppression
    list carried over from a prior edition (e.g. "24Q4 - Events - CNCF -
    Kubecon NA - Suppressions", "KCCNC EU 2026 - Suppression (Current Reg +
    Unsubscribes)") that already bundles current-registrant + unsubscribe
    exclusions for that specific event — surfaced as a high-priority
    recommended pick distinct from the generic portfolio-wide lists."""
    event_kw = _event_keywords(event_name)
    if not event_kw:
        return None
    by_id: dict[str, dict] = {}
    for probe in (f"{event_name} Suppression", f"{event_name} Exclusion"):
        try:
            results = audience_tools.hubspot_search_lists(probe)
        except Exception:
            continue
        for r in results.get("results", []):
            name = r.get("name") or ""
            if not r.get("listId"):
                continue
            if not (event_kw & _event_keywords(name)):
                continue
            if "suppress" not in name.lower() and "exclusion" not in name.lower():
                continue
            by_id[str(r["listId"])] = r
    if not by_id:
        return None
    best = max(by_id.values(), key=lambda r: (_quarter_rank(r.get("name", "")), r.get("size") or 0))
    return {
        "key": "event_suppression",
        "label": "Existing suppression for this event",
        "list_id": str(best["listId"]),
        "name": best.get("name", ""),
        "size": best.get("size"),
        "category": "event_specific",
    }


def find_standard_suppression_lists(brand_short: str = "", event_name: str = "") -> list[dict]:
    """Deterministically resolves the standard hygiene suppression lists by
    name search, picking the most recently updated (highest quarter-code)
    match per category. Returns one entry per category that resolved to a
    match; categories with no match are simply omitted.

    When brand_short/event_name are given, also looks for a brand-scoped
    "Global Opt Out" list and an event-specific pre-existing suppression list
    (see _find_brand_opt_out / _find_event_suppression) — both real patterns
    found in this portfolio's HubSpot data, not covered by the 6 generic
    portfolio-wide terms below."""
    found = []
    for key, label, term in STANDARD_SUPPRESSION_TERMS:
        try:
            results = audience_tools.hubspot_search_lists(term)
        except Exception:
            continue
        candidates = [
            r for r in results.get("results", [])
            if r.get("listId") and term.lower() in (r.get("name") or "").lower()
        ]
        if not candidates:
            continue
        best = max(candidates, key=lambda r: (_quarter_rank(r.get("name", "")), r.get("size") or 0))
        found.append({
            "key": key,
            "label": label,
            "list_id": str(best["listId"]),
            "name": best.get("name", label),
            "size": best.get("size"),
            "category": "standard",
        })

    brand_result = _find_brand_opt_out(brand_short)
    if brand_result:
        found.append(brand_result)

    event_result = _find_event_suppression(event_name)
    if event_result:
        found.append(event_result)

    return found


def find_existing_master_lists(brand_short: str = "", event_name: str = "") -> list[dict]:
    """Master lists already built for this event by an earlier Audience
    Builder run (or the legacy full-build agent) — surfaced so the user can
    reuse/inspect one instead of unknowingly rebuilding from scratch every
    time. Matches the same name-search + keyword-overlap pattern as
    _find_event_suppression, but for "master" instead of "suppression"/
    "exclusion", and returns EVERY match (not just the best one) since
    distinct past editions (one master list per quarter/year) can legitimately
    coexist — the caller decides which, if any, is still relevant."""
    event_kw = _event_keywords(event_name) | _event_keywords(brand_short)
    if not event_kw:
        return []

    by_id: dict[str, dict] = {}
    for probe in (f"{event_name} Master", f"{brand_short} {event_name} Master"):
        probe = probe.strip()
        if not probe:
            continue
        try:
            results = audience_tools.hubspot_search_lists(probe)
        except Exception:
            continue
        for r in results.get("results", []):
            name = r.get("name") or ""
            lid = r.get("listId")
            if not lid or "master" not in name.lower():
                continue
            if not (event_kw & _event_keywords(name)):
                continue
            by_id[str(lid)] = r

    ranked = sorted(by_id.values(), key=lambda r: _quarter_rank(r.get("name", "")), reverse=True)
    return [
        {
            "list_id": str(r["listId"]),
            "name": r.get("name", ""),
            "size": r.get("size"),
            "hubspot_url": f"https://app.hubspot.com/contacts/{HUBSPOT_PORTAL_ID}/objectLists/{r['listId']}/filters",
        }
        for r in ranked
    ]


def _list_size(list_id: str) -> int:
    """hubspot_get_list's raw response nests size under "list" (confirmed live:
    GET /crm/v3/lists/{id} returns {"list": {..., "size": N}}), unlike the
    create-list response which is flat — check both defensively."""
    try:
        raw = audience_tools.hubspot_get_list(list_id)
    except Exception:
        return 0
    return raw.get("list", {}).get("size") or raw.get("size") or 0


def union_size(list_ids: list[str], cap: int = 25000) -> dict:
    """De-duplicated contact count across multiple lists. HubSpot has no API
    to count an arbitrary OR-of-lists without either creating a real list
    (async-processed, size not immediately available) or paginating each
    list's membership IDs and unioning them client-side — this does the
    latter, capped at `cap` combined estimated contacts so a "Get exact
    count" click can't trigger an unbounded pagination sweep. Above the cap,
    falls back to a naive sum-of-sizes estimate (may double-count contacts
    that belong to more than one selected list)."""
    seen: list[str] = []
    for lid in list_ids:
        lid = str(lid).strip()
        if lid and lid not in seen:
            seen.append(lid)
    if not seen:
        return {"exact": False, "estimate": 0, "count": 0}

    estimate = sum(_list_size(lid) for lid in seen)
    if estimate > cap:
        return {
            "exact": False,
            "estimate": estimate,
            "count": estimate,
            "reason": f"combined size ~{estimate:,} exceeds live-count limit ({cap:,}); showing sum estimate",
        }

    union: set = set()
    for lid in seen:
        try:
            union |= audience_tools.hubspot_list_membership_ids(lid)
        except Exception:
            return {
                "exact": False,
                "estimate": estimate,
                "count": estimate,
                "reason": "live membership lookup failed; showing sum estimate",
            }
    return {"exact": True, "estimate": estimate, "count": len(union)}


def build_master_filter_branch(include_ids: list[str], suppression_list_id: str = "") -> dict:
    """One AND-branch per de-duplicated inclusion list ID, each ANDed with a
    NOT_IN_LIST filter on the single combined-suppression list (if given), all
    OR'd together — the shape required by BUILDING_PROMPT STEP 6 in
    audience_tools.py: (inc_1 AND NOT supp) OR (inc_2 AND NOT supp) ..."""
    seen: list[str] = []
    for lid in include_ids:
        lid = str(lid).strip()
        if lid and lid not in seen:
            seen.append(lid)

    branches = []
    for lid in seen:
        filters = [{"filterType": "IN_LIST", "listId": lid, "operator": "IN_LIST"}]
        if suppression_list_id:
            filters.append({"filterType": "IN_LIST", "listId": str(suppression_list_id), "operator": "NOT_IN_LIST"})
        branches.append({"filterBranchType": "AND", "filterBranches": [], "filters": filters})

    return {"filterBranchType": "OR", "filterBranches": branches, "filters": []}


def _create_with_retry(resolved_name: str, filter_branch: dict) -> tuple[dict, str]:
    """hubspot_create_list, appending a timestamp to the name and retrying once
    if a list with that exact name already exists (mirrors RULE 10's
    reuse-by-exact-name convention, applied here as a non-colliding rebuild
    rather than an update-in-place, consistent with this file's existing
    master-list behavior)."""
    try:
        return audience_tools.hubspot_create_list(resolved_name, filter_branch), resolved_name
    except RuntimeError as exc:
        if "already exist" not in str(exc).lower():
            raise
        resolved_name = f"{resolved_name} ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M')})"
        return audience_tools.hubspot_create_list(resolved_name, filter_branch), resolved_name


def compose_master_list_from_ids(list_ids: list[str], name: str = "", event_url: str = "",
                                  brand_short: str = "", event_name: str = "",
                                  event_dates: list[str] | None = None,
                                  exclude_list_ids: list[str] | None = None) -> dict:
    """Build the master list from a set of already-discovered/selected HubSpot
    list IDs. If a list with the resolved name already exists, create a new
    list with a timestamp appended to the name rather than overwriting
    whichever list currently holds that name.

    If exclude_list_ids is given, first builds a single "Combined Suppression"
    list (OR of IN_LIST over those IDs — same shape as an inclusion branch),
    then applies that one combined list as a NOT_IN_LIST exclusion inside every
    inclusion AND-branch of the master list, per audience_tools.py's
    BUILDING_PROMPT STEP 5B/6 convention (one shared exclusion, never the
    individual suppression lists repeated in each branch)."""
    if not list_ids:
        raise ValueError("list_ids must not be empty")

    exclude_list_ids = [str(x).strip() for x in (exclude_list_ids or []) if str(x).strip()]

    suppression_info = None
    suppression_list_id = ""
    if exclude_list_ids:
        supp_name = name and f"{name.strip()} - Combined Suppression" or build_master_list_name(
            event_url=event_url, brand_short=brand_short, event_name=event_name,
            event_dates=event_dates, suffix="Combined Suppression",
        )
        supp_result, supp_name = _create_with_retry(supp_name, build_in_list_or_branch(exclude_list_ids))
        suppression_list_id = str(supp_result.get("listId") or "")
        suppression_info = {
            "suppression_list_id": suppression_list_id,
            "suppression_name": supp_result.get("name", supp_name),
            "suppression_hubspot_url": supp_result.get("hubspot_url", ""),
            "suppression_size": supp_result.get("size", "unknown"),
        }

    resolved_name = name.strip() if name else build_master_list_name(
        event_url=event_url, brand_short=brand_short, event_name=event_name, event_dates=event_dates
    )
    filter_branch = build_master_filter_branch(list_ids, suppression_list_id)

    result, resolved_name = _create_with_retry(resolved_name, filter_branch)

    response = {
        "list_id": result.get("listId"),
        "name": result.get("name", resolved_name),
        "hubspot_url": result.get("hubspot_url", ""),
        "size": result.get("size", "unknown"),
        "source_list_ids": list_ids,
    }
    if suppression_info:
        response.update(suppression_info)
    return response
