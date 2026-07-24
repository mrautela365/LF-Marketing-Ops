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
                            event_dates: list[str] | None = None) -> str:
    """`<YYQN> - <Brand> - <Event> - Master`, matching the convention already
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
    return f"{yyq} - {body} - Master"


def compose_master_list_from_ids(list_ids: list[str], name: str = "", event_url: str = "",
                                  brand_short: str = "", event_name: str = "",
                                  event_dates: list[str] | None = None) -> dict:
    """Build the master list from a set of already-discovered/selected HubSpot
    list IDs. If a list with the resolved name already exists, update its
    filters in place instead of erroring (mirrors audience_tools' own RULE 10
    reuse-don't-duplicate behavior)."""
    if not list_ids:
        raise ValueError("list_ids must not be empty")

    resolved_name = name.strip() if name else build_master_list_name(
        event_url=event_url, brand_short=brand_short, event_name=event_name, event_dates=event_dates
    )
    filter_branch = build_in_list_or_branch(list_ids)

    try:
        result = audience_tools.hubspot_create_list(resolved_name, filter_branch)
    except RuntimeError as exc:
        if "already exist" not in str(exc).lower():
            raise
        search_resp = audience_tools.hubspot_search_lists(resolved_name)
        match = next(
            (r for r in search_resp.get("results", []) if r.get("name") == resolved_name),
            None,
        )
        if not match:
            raise
        result = audience_tools.hubspot_update_list_filters(match["listId"], filter_branch)
        result.setdefault("name", resolved_name)
        result.setdefault("size", match.get("size", "unknown"))

    return {
        "list_id": result.get("listId"),
        "name": result.get("name", resolved_name),
        "hubspot_url": result.get("hubspot_url", ""),
        "size": result.get("size", "unknown"),
        "source_list_ids": list_ids,
    }
