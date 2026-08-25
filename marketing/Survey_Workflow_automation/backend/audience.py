"""
Custom-audience list builder — ported from emailcreationskill/backend's
`audience_tools.py` CUSTOM_PLANNING_PROMPT_TEMPLATE / CUSTOM_BUILDING_PROMPT flow,
but reworked so the LLM emits a structured AudiencePlan (see models.py) instead of
free-form markdown prose, and the filterBranch JSON is assembled deterministically
in Python from that plan rather than composed ad hoc by the model.

HubSpot filter mechanics enforced here (per the source project's hard-won rules):
- Root filterBranch must be filterBranchType "OR" of "AND" sub-branches (HubSpot
  rejects an AND root or nested OR).
- List-membership filters use filterType "IN_LIST" / "NOT_IN_LIST" (never the
  legacy "LIST_MEMBERSHIP", which HubSpot rejects).
- Location filters use filterType "PROPERTY" on `city` with a MULTISTRING operator.
"""
from integrations import hubspot

_DEFAULT_SUPPRESSION_TERMS = ["opt-out", "suppression", "master exclusion", "gdpr"]


def _location_and_branch(city: str, country: str, suppression_list_id: str = "") -> dict:
    filters = [{
        "filterType": "PROPERTY",
        "property": "city",
        "operation": {
            "operationType": "MULTISTRING",
            "operator": "CONTAINS_TOKEN",
            "values": [city],
        },
    }]
    if country:
        filters.append({
            "filterType": "PROPERTY",
            "property": "country_dropdown",
            "operation": {
                "operationType": "MULTISTRING",
                "operator": "CONTAINS_TOKEN",
                "values": [country],
            },
        })
    if suppression_list_id:
        filters.append({
            "filterType": "NOT_IN_LIST",
            "listId": str(suppression_list_id),
        })
    return {"filterBranchType": "AND", "filters": filters, "filterBranches": []}


def build_inclusion_filter_branch(locations: list, suppression_list_id: str = "") -> dict:
    and_branches = [
        _location_and_branch(loc.city, loc.country or "", suppression_list_id)
        for loc in locations
    ]
    return {"filterBranchType": "OR", "filters": [], "filterBranches": and_branches}


def build_suppression_filter_branch(suppression_list_ids: list) -> dict:
    and_branches = [
        {"filterBranchType": "AND", "filters": [{"filterType": "IN_LIST", "listId": str(lid)}], "filterBranches": []}
        for lid in suppression_list_ids
    ]
    return {"filterBranchType": "OR", "filters": [], "filterBranches": and_branches}


def find_suppression_list_ids(search_terms: list) -> list:
    """Search HubSpot for existing hygiene-suppression lists by name. Dedupes by
    list_id since different search terms commonly surface the same list twice."""
    terms = search_terms or _DEFAULT_SUPPRESSION_TERMS
    seen = {}
    for term in terms:
        for lst in hubspot.search_lists(term):
            list_id = str(lst.get("listId") or lst.get("id") or "")
            if list_id and list_id not in seen:
                seen[list_id] = lst.get("name", term)
    return [{"list_id": lid, "name": name} for lid, name in seen.items()]


def build_audience(plan) -> dict:
    """Build the master (inclusion) list, and — if requested — a combined
    suppression list gating it, from a confirmed AudiencePlan. Returns
    {"master_list": {...}, "suppression_list": {...} | None}."""
    if not plan.locations:
        raise ValueError("Plan has no locations to build a segment from.")

    suppression_result = None
    suppression_list_id = ""

    if plan.apply_suppression:
        found = find_suppression_list_ids(plan.suppression_search_terms)
        if found:
            combined_name = f"{plan.list_name or 'Custom Audience'} - Combined Suppression"
            branch = build_suppression_filter_branch([f["list_id"] for f in found])
            created = hubspot.create_list(combined_name, branch)
            suppression_list_id = created["list_id"]
            suppression_result = {
                "list_id": suppression_list_id,
                "name": created["name"],
                "url": hubspot.list_url(suppression_list_id),
                "size": hubspot.get_list_size(suppression_list_id),
            }

    master_name = plan.list_name or "Custom Audience - Mailable Contacts"
    inclusion_branch = build_inclusion_filter_branch(plan.locations, suppression_list_id)
    master = hubspot.create_list(master_name, inclusion_branch)
    master_result = {
        "list_id": master["list_id"],
        "name": master["name"],
        "url": hubspot.list_url(master["list_id"]),
        "size": hubspot.get_list_size(master["list_id"]),
    }

    return {"master_list": master_result, "suppression_list": suppression_result}
