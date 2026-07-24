#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Build inclusion lists 4-7 for PyTorch Conference NA 2026 and search for suppression lists.
Run: python pytorch_list_builder.py
"""
import json
import sys
import io

# Ensure stdout can handle Unicode
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from audience_tools import (
    hubspot_create_list,
    hubspot_search_lists,
    hubspot_get_list,
)

# ─────────────────────────────────────────────────────────────────────────────
# Inclusion Lists to Create (4-7)
# ─────────────────────────────────────────────────────────────────────────────

INCLUSION_LISTS = [
    {
        "list_number": 4,
        "name": "26Q3 - LF Events - PyTorch Conf NA 2026 - Newsletter (22Q4)",
        "list_id": "19159",
    },
    {
        "list_number": 5,
        "name": "26Q3 - LF Events - PyTorch Conf NA 2026 - Newsletter (25Q1 Updated BU)",
        "list_id": "19734",
    },
    {
        "list_number": 6,
        "name": "26Q3 - LF Events - PyTorch Conf NA 2026 - Newsletter (25Q1 OSS AI Week)",
        "list_id": "19854",
    },
    {
        "list_number": 7,
        "name": "26Q3 - LF Events - PyTorch Conf NA 2026 - Livestream 2024",
        "list_id": "17305",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Suppression Lists to Search (8 total)
# ─────────────────────────────────────────────────────────────────────────────

SUPPRESSION_SEARCHES = [
    {
        "search_key": "LF Global Opt-Outs",
        "notes": "Global opt-out list",
    },
    {
        "search_key": "LF Europe Global Opt-Outs",
        "notes": "Europe opt-out list",
    },
    {
        "search_key": "LF Events GDPR Suppression",
        "notes": "Most recent quarterly (e.g., 25Q2)",
    },
    {
        "search_key": "LF Europe GDPR Suppression",
        "notes": "Most recent",
    },
    {
        "search_key": "23Q1 LF Master Exclusion",
        "notes": "Known ID: 3732, verify",
    },
    {
        "search_key": "LF Events Suppression List",
        "notes": "Most recent",
    },
    {
        "search_key": "PyTorch Global Opt Out",
        "notes": "Known ID: 13404, verify",
    },
    {
        "search_key": "PyTorch Foundation Opt Out",
        "notes": "Event-specific opt-out",
    },
]


def build_in_list_filter(list_id: str) -> dict:
    """Build a filterBranch for IN_LIST membership filter."""
    return {
        "filterBranchType": "OR",
        "filterBranches": [
            {
                "filterBranchType": "AND",
                "filterBranches": [],
                "filters": [
                    {
                        "filterType": "IN_LIST",
                        "listId": list_id,
                        "operator": "IN_LIST",
                    }
                ],
            }
        ],
        "filters": [],
    }


def create_inclusion_lists():
    """Create all 4 inclusion lists. If they already exist, find them instead."""
    print("\n" + "=" * 80)
    print("CREATING/VERIFYING INCLUSION LISTS 4-7")
    print("=" * 80)

    results = []
    for item in INCLUSION_LISTS:
        list_num = item["list_number"]
        name = item["name"]
        source_list_id = item["list_id"]

        print(f"\n[List {list_num}] {name}")
        print(f"  Source list ID (filter): {source_list_id}")

        filter_branch = build_in_list_filter(source_list_id)

        try:
            response = hubspot_create_list(name, filter_branch)
            created_id = response.get("listId")
            hubspot_url = response.get("hubspot_url")
            size = response.get("size", "unknown")

            print(f"  [OK] (created)")
            print(f"     ID: {created_id}")
            print(f"     Size: {size}")

            results.append({
                "list_number": list_num,
                "name": name,
                "listId": created_id,
                "size": size,
                "hubspot_url": hubspot_url,
                "status": "SUCCESS",
            })
        except Exception as e:
            error_str = str(e)
            if "already exist" in error_str:
                # List already exists — try to find it by searching
                print(f"  Already exists, looking it up...")
                try:
                    search_resp = hubspot_search_lists(name.replace(" [psh-test]", ""))
                    found_lists = search_resp.get("results", [])
                    if found_lists:
                        best = found_lists[0]
                        list_id = best.get("listId")
                        found_name = best.get("name")
                        size = best.get("size", "unknown")
                        hs_url = f"https://app.hubspot.com/contacts/8112310/objectLists/{list_id}/filters"

                        print(f"  [FOUND]: {found_name}")
                        print(f"     ID: {list_id}")
                        print(f"     Size: {size}")

                        results.append({
                            "list_number": list_num,
                            "name": found_name,
                            "listId": list_id,
                            "size": size,
                            "hubspot_url": hs_url,
                            "status": "EXISTS",
                        })
                    else:
                        raise Exception("List exists but search returned no results")
                except Exception as search_error:
                    print(f"  [LOOKUP_FAILED]: {search_error}")
                    results.append({
                        "list_number": list_num,
                        "name": name,
                        "status": "FAILED",
                        "error": error_str,
                    })
            else:
                print(f"  [ERROR]: {error_str[:100]}")
                results.append({
                    "list_number": list_num,
                    "name": name,
                    "status": "FAILED",
                    "error": error_str,
                })

    return results


def search_suppression_lists():
    """Search for all 8 suppression lists."""
    print("\n" + "=" * 80)
    print("SEARCHING FOR SUPPRESSION LISTS")
    print("=" * 80)

    results = []
    for item in SUPPRESSION_SEARCHES:
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


def main():
    """Main entry point."""
    print("\n" + "=" * 80)
    print("PyTorch Conference NA 2026 - HubSpot List Builder")
    print("=" * 80)

    # Create inclusion lists
    inclusion_results = create_inclusion_lists()

    # Search for suppression lists
    suppression_results = search_suppression_lists()

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print("\n--- INCLUSION LISTS (4-7) ---")
    successful = 0
    for res in inclusion_results:
        status_icon = "[OK]" if res["status"] in ("SUCCESS", "EXISTS") else "[ERR]"
        print(f"{status_icon} List {res['list_number']}: {res['name']}")
        if res["status"] in ("SUCCESS", "EXISTS"):
            print(f"   ID: {res['listId']} | Size: {res['size']} | {res['hubspot_url']}")
            successful += 1
        else:
            print(f"   Error: {res['error']}")

    print(f"\nVerified: {successful}/{len(INCLUSION_LISTS)} inclusion lists")

    print("\n--- SUPPRESSION LISTS ---")
    found_count = 0
    for res in suppression_results:
        status_icon = {
            "FOUND": "[OK]",
            "NOT_FOUND": "[X]",
            "ERROR": "[ERR]",
        }.get(res["status"], "?")

        print(f"{status_icon} {res['search_key']}")
        if res["status"] == "FOUND":
            print(f"   {res['name']} (ID: {res['listId']}, Size: {res['size']})")
            found_count += 1
        elif res["status"] == "NOT_FOUND":
            print(f"   Not found")
        else:
            print(f"   Error: {res['error']}")

    print(f"\nFound: {found_count}/{len(SUPPRESSION_SEARCHES)} suppression lists")

    # Export results as JSON
    all_results = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "inclusion_lists": inclusion_results,
        "suppression_lists": suppression_results,
        "summary": {
            "inclusion_success": successful,
            "inclusion_total": len(INCLUSION_LISTS),
            "suppression_found": found_count,
            "suppression_total": len(SUPPRESSION_SEARCHES),
        },
    }

    output_file = "pytorch_list_builder_results.json"
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n[DONE] Results saved to {output_file}")

    return 0 if successful == len(INCLUSION_LISTS) else 1


if __name__ == "__main__":
    sys.exit(main())
