#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Build the Combined Suppression List and Master List for PyTorch Conference NA 2026.
Also search for missing inclusion lists and newer suppression lists.
Run: python build_suppression_and_master.py
"""
import json
import sys
import io
from datetime import datetime

# Ensure stdout can handle Unicode
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from audience_tools import (
    hubspot_create_list,
    hubspot_search_lists,
    hubspot_get_list,
)

# Inclusion Lists to Find (1-3)
INCLUSION_SEARCHES = [
    {
        "list_num": 1,
        "name": "26Q3 - LF Events - PyTorch Conf NA 2026 - Past Registrants 2025",
        "expected_id": "29446",
    },
    {
        "list_num": 2,
        "name": "26Q3 - LF Events - PyTorch Conf NA 2026 - 2025 Full Send Snapshot",
        "expected_id": "29447",
    },
    {
        "list_num": 3,
        "name": "26Q3 - LF Events - PyTorch Conf NA 2026 - Web Visitors",
        "expected_id": "29448",
    },
]

# Newer suppression lists to search for
NEWER_SUPPRESSION_SEARCHES = [
    {
        "search_key": "26Q1 LF Events GDPR",
        "notes": "Newer than 24Q1 (ID 13340)",
    },
    {
        "search_key": "25Q4 LF Events GDPR",
        "notes": "Newer than 24Q1 (ID 13340)",
    },
    {
        "search_key": "25Q3 LF Events GDPR",
        "notes": "Newer than 24Q1 (ID 13340)",
    },
    {
        "search_key": "26Q1 LF Events Suppression",
        "notes": "Newer than 23Q3 (ID 9501)",
    },
    {
        "search_key": "25Q4 LF Events Suppression",
        "notes": "Newer than 23Q3 (ID 9501)",
    },
    {
        "search_key": "25Q3 LF Events Suppression",
        "notes": "Newer than 23Q3 (ID 9501)",
    },
    {
        "search_key": "26Q2 LF events global opt out",
        "notes": "Verify list 13337 exists",
    },
]

def search_inclusion_lists():
    """Search for missing inclusion lists 1-3."""
    print("\n" + "=" * 80)
    print("SEARCHING FOR MISSING INCLUSION LISTS (1-3)")
    print("=" * 80)

    results = []
    for item in INCLUSION_SEARCHES:
        list_num = item["list_num"]
        name = item["name"]
        expected_id = item["expected_id"]

        print(f"\n[List {list_num}] {name}")
        print(f"  Expected ID: {expected_id}")

        try:
            # Try to get by expected ID first
            try:
                detail = hubspot_get_list(expected_id)
                list_id = detail.get("listId", expected_id)
                found_name = detail.get("name", "")
                size = detail.get("size", "unknown")

                print(f"  [FOUND by ID]")
                print(f"     Name: {found_name}")
                print(f"     ID: {list_id}")
                print(f"     Size: {size}")

                results.append({
                    "list_num": list_num,
                    "expected_id": expected_id,
                    "name": found_name,
                    "listId": list_id,
                    "size": size,
                    "status": "FOUND_BY_ID",
                })
            except:
                # If not found by ID, search by name
                response = hubspot_search_lists(name)
                found_lists = response.get("results", [])

                if found_lists:
                    best = found_lists[0]
                    list_id = best.get("listId")
                    found_name = best.get("name")
                    size = best.get("size", "unknown")

                    print(f"  [FOUND by name search]")
                    print(f"     Name: {found_name}")
                    print(f"     ID: {list_id}")
                    print(f"     Size: {size}")

                    results.append({
                        "list_num": list_num,
                        "expected_id": expected_id,
                        "name": found_name,
                        "listId": list_id,
                        "size": size,
                        "status": "FOUND_BY_SEARCH",
                    })
                else:
                    print(f"  [NOT FOUND]")
                    results.append({
                        "list_num": list_num,
                        "expected_id": expected_id,
                        "name": name,
                        "status": "NOT_FOUND",
                    })
        except Exception as e:
            print(f"  [ERROR]: {e}")
            results.append({
                "list_num": list_num,
                "expected_id": expected_id,
                "name": name,
                "status": "ERROR",
                "error": str(e),
            })

    return results

def search_newer_suppression_lists():
    """Search for newer suppression lists."""
    print("\n" + "=" * 80)
    print("SEARCHING FOR NEWER SUPPRESSION LISTS")
    print("=" * 80)

    results = []
    for item in NEWER_SUPPRESSION_SEARCHES:
        search_key = item["search_key"]
        notes = item["notes"]

        print(f"\nSearching: '{search_key}' ({notes})")

        try:
            response = hubspot_search_lists(search_key)
            found_lists = response.get("results", [])

            if found_lists:
                # Take the first (most relevant) result
                best_match = found_lists[0]
                list_id = best_match.get("listId")
                name = best_match.get("name")
                size = best_match.get("size", "unknown")

                print(f"  [FOUND]")
                print(f"     Name: {name}")
                print(f"     ID: {list_id}")
                print(f"     Size: {size}")

                # Show other matches if any
                if len(found_lists) > 1:
                    print(f"  (Also found {len(found_lists) - 1} other match(es))")
                    for alt in found_lists[1:3]:  # Show up to 3 alternatives
                        print(f"     - {alt.get('name')} (ID: {alt.get('listId')})")

                results.append({
                    "search_key": search_key,
                    "notes": notes,
                    "status": "FOUND",
                    "listId": list_id,
                    "name": name,
                    "size": size,
                    "alternatives": [
                        {
                            "name": alt.get("name"),
                            "listId": alt.get("listId"),
                            "size": alt.get("size"),
                        }
                        for alt in found_lists[1:3]
                    ] if len(found_lists) > 1 else [],
                })
            else:
                print(f"  [NOT FOUND] (no matches)")
                results.append({
                    "search_key": search_key,
                    "notes": notes,
                    "status": "NOT_FOUND",
                })
        except Exception as e:
            print(f"  [ERROR]: {e}")
            results.append({
                "search_key": search_key,
                "notes": notes,
                "status": "ERROR",
                "error": str(e),
            })

    return results

def build_combined_suppression_list(suppression_ids: list) -> dict:
    """Build the combined suppression list with all suppression lists."""
    print("\n" + "=" * 80)
    print("BUILDING COMBINED SUPPRESSION LIST")
    print("=" * 80)

    name = "26Q3 - LF Events - PyTorch Conf NA 2026 - Combined Suppression"

    # Build the filterBranch with OR logic and one AND branch per suppression list
    filter_branches = []
    for list_id in suppression_ids:
        filter_branches.append({
            "filterBranchType": "AND",
            "filterBranches": [],
            "filters": [{
                "filterType": "IN_LIST",
                "listId": list_id,
                "operator": "IN_LIST"
            }]
        })

    filter_branch = {
        "filterBranchType": "OR",
        "filterBranches": filter_branches,
        "filters": []
    }

    print(f"\nCreating: {name}")
    print(f"Suppression list IDs: {suppression_ids}")

    try:
        response = hubspot_create_list(name, filter_branch)
        created_id = response.get("listId")
        hubspot_url = response.get("hubspot_url")
        size = response.get("size", "unknown")

        print(f"  [SUCCESS]")
        print(f"  ID: {created_id}")
        print(f"  Size: {size}")
        print(f"  URL: {hubspot_url}")

        return {
            "name": name,
            "listId": created_id,
            "size": size,
            "hubspot_url": hubspot_url,
            "status": "SUCCESS",
            "suppression_ids": suppression_ids,
        }
    except Exception as e:
        print(f"  [ERROR]: {e}")
        return {
            "name": name,
            "status": "FAILED",
            "error": str(e),
            "suppression_ids": suppression_ids,
        }

def build_master_list(inclusion_ids: dict, combined_suppression_id: str) -> dict:
    """
    Build the master segmentation list.
    inclusion_ids format: {
        "29446": {"gated": True},
        "29447": {"gated": True},
        "29448": {"gated": False},
        ...
    }
    """
    print("\n" + "=" * 80)
    print("BUILDING MASTER LIST")
    print("=" * 80)

    name = "Q3 2026 - LF Events – PyTorch Conference North America 2026 Master (With Opt-In and Filters)"

    # Build AND branches - one per inclusion list
    filter_branches = []
    opt_in_id = "26793"

    for list_id, config in inclusion_ids.items():
        filters = [
            {
                "filterType": "IN_LIST",
                "listId": list_id,
                "operator": "IN_LIST"
            }
        ]

        # Add opt-in gate if gated
        if config.get("gated", False):
            filters.append({
                "filterType": "IN_LIST",
                "listId": opt_in_id,
                "operator": "IN_LIST"
            })

        # Add combined suppression exclusion (always, for all lists)
        filters.append({
            "filterType": "IN_LIST",
            "listId": combined_suppression_id,
            "operator": "NOT_IN_LIST"
        })

        filter_branches.append({
            "filterBranchType": "AND",
            "filterBranches": [],
            "filters": filters
        })

    filter_branch = {
        "filterBranchType": "OR",
        "filterBranches": filter_branches,
        "filters": []
    }

    print(f"\nCreating: {name}")
    print(f"Inclusion lists: {list(inclusion_ids.keys())}")
    print(f"Combined suppression ID: {combined_suppression_id}")
    print(f"Opt-in gate ID: {opt_in_id}")

    try:
        response = hubspot_create_list(name, filter_branch)
        created_id = response.get("listId")
        hubspot_url = response.get("hubspot_url")
        size = response.get("size", "unknown")

        print(f"  [SUCCESS]")
        print(f"  ID: {created_id}")
        print(f"  Size: {size}")
        print(f"  URL: {hubspot_url}")

        return {
            "name": name,
            "listId": created_id,
            "size": size,
            "hubspot_url": hubspot_url,
            "status": "SUCCESS",
            "inclusion_ids": list(inclusion_ids.keys()),
            "combined_suppression_id": combined_suppression_id,
            "opt_in_id": opt_in_id,
        }
    except Exception as e:
        print(f"  [ERROR]: {e}")
        return {
            "name": name,
            "status": "FAILED",
            "error": str(e),
            "inclusion_ids": list(inclusion_ids.keys()),
            "combined_suppression_id": combined_suppression_id,
        }

def main():
    """Main entry point."""
    print("\n" + "=" * 80)
    print("PyTorch Conference NA 2026 - Suppression & Master List Builder")
    print("=" * 80)

    # Search for missing inclusion lists
    inclusion_search_results = search_inclusion_lists()

    # Search for newer suppression lists
    suppression_search_results = search_newer_suppression_lists()

    # Prepare final suppression list IDs (use newer if found, otherwise default)
    suppression_ids = [
        "888",      # LF Global Opt-Outs
        "21558",    # LF Europe Global Opt-Outs
        "13340",    # 24Q1 - LF Events - GDPR Suppression (or newer)
        "20420",    # 25Q2 - LF Europe - GDPR Suppression
        "3732",     # 23Q1 - LF - Master Exclusion List
        "9501",     # 23Q3 - LF Events - Suppression List (or newer)
        "13404",    # PyTorch Global Opt Out Static List
        "13337",    # 26Q2 LF events global opt out
    ]

    # Check for newer versions in suppression search results
    newer_gdpr_ids = []
    newer_suppression_ids = []

    for result in suppression_search_results:
        if result.get("status") == "FOUND":
            search_key = result.get("search_key", "")
            list_id = result.get("listId")

            if "26Q1 LF Events GDPR" in search_key:
                newer_gdpr_ids.append((26, list_id))
            elif "25Q4 LF Events GDPR" in search_key:
                newer_gdpr_ids.append((25, list_id))
            elif "25Q3 LF Events GDPR" in search_key:
                newer_gdpr_ids.append((23, list_id))
            elif "26Q1 LF Events Suppression" in search_key:
                newer_suppression_ids.append((26, list_id))
            elif "25Q4 LF Events Suppression" in search_key:
                newer_suppression_ids.append((25, list_id))
            elif "25Q3 LF Events Suppression" in search_key:
                newer_suppression_ids.append((23, list_id))

    # Use the newest found (highest quarter number)
    if newer_gdpr_ids:
        newer_gdpr_ids.sort(reverse=True)
        newest_gdpr_id = newer_gdpr_ids[0][1]
        suppression_ids = [newest_gdpr_id if id == "13340" else id for id in suppression_ids]

    if newer_suppression_ids:
        newer_suppression_ids.sort(reverse=True)
        newest_supp_id = newer_suppression_ids[0][1]
        suppression_ids = [newest_supp_id if id == "9501" else id for id in suppression_ids]

    # Build combined suppression list
    combined_result = build_combined_suppression_list(suppression_ids)
    combined_suppression_id = combined_result.get("listId")

    # Prepare inclusion list configuration (all 7)
    inclusion_config = {
        "29446": {"gated": True},   # Past Registrants 2025
        "29447": {"gated": True},   # 2025 Full Send Snapshot
        "29448": {"gated": False},  # Web Visitors (NO opt-in)
        "29449": {"gated": True},   # Newsletter 22Q4
        "29450": {"gated": True},   # Newsletter 25Q1 Updated BU
        "29451": {"gated": True},   # Newsletter 25Q1 OSS AI Week
        "29452": {"gated": True},   # Livestream 2024
    }

    # Build master list (only if combined suppression was successful)
    master_result = None
    if combined_suppression_id:
        master_result = build_master_list(inclusion_config, combined_suppression_id)

    # Compile all results
    all_results = {
        "timestamp": datetime.now().isoformat(),
        "inclusion_search": inclusion_search_results,
        "suppression_search": suppression_search_results,
        "combined_suppression": combined_result,
        "master_list": master_result,
        "suppression_ids_used": suppression_ids,
        "summary": {
            "combined_suppression_status": combined_result.get("status"),
            "master_list_status": master_result.get("status") if master_result else "SKIPPED",
        }
    }

    # Export results
    output_file = "suppression_and_master_results.json"
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n[DONE] Results saved to {output_file}")

    # Print summary
    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)

    if combined_suppression_id:
        print(f"\nCombined Suppression List: {combined_result.get('listId')}")
        print(f"  {combined_result.get('hubspot_url')}")
    else:
        print(f"\nCombined Suppression List FAILED")

    if master_result and master_result.get("status") == "SUCCESS":
        print(f"\nMaster List: {master_result.get('listId')}")
        print(f"  {master_result.get('hubspot_url')}")
    else:
        print(f"\nMaster List FAILED or SKIPPED")

    return 0 if (combined_suppression_id and master_result and master_result.get("status") == "SUCCESS") else 1

if __name__ == "__main__":
    sys.exit(main())
