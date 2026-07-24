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


def find_standard_suppression_lists() -> list[dict]:
    """Deterministically resolves the standard hygiene suppression lists by
    name search, picking the most recently updated (highest quarter-code)
    match per category. Returns one entry per category that resolved to a
    match; categories with no match are simply omitted."""
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
        })
    return found


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
