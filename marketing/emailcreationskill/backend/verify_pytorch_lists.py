#!/usr/bin/env python3
"""
Verify HubSpot audience lists for PyTorch Conference North America 2026.
"""
import sys
import json
from hubspot_tools import search_lists

def main():
    print("=" * 80)
    print("SEARCHING FOR PYTORCH CONFERENCE LISTS")
    print("=" * 80)

    queries = [
        ("26Q3 PyTorch Conf NA 2026 Newsletter 22Q4", "Exact name with full details"),
        ("26Q3 PyTorch Conf NA 2026", "Shorter query with quarter and event"),
        ("PyTorch Conf NA 2026", "Without quarter prefix"),
        ("PyTorch Conference", "Generic PyTorch Conference"),
        ("26Q3", "Just the quarter"),
        ("PyTorch", "Just PyTorch"),
    ]

    all_results = {}

    for query, description in queries:
        print(f"\nSearch: {query!r}")
        print(f"Description: {description}")
        print("-" * 80)
        result = search_lists(query, limit=30)
        lists = result.get("lists", [])
        all_results[query] = lists

        if not lists:
            print("No lists found.")
        else:
            print(f"Found {len(lists)} list(s):")
            for i, lst in enumerate(lists, 1):
                print(f"  {i}. {lst['name']}")
                print(f"     ID: {lst['id']} | Size: {lst['size']:,} contacts")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    # Collect all unique lists
    unique_lists = {}
    for query, lists in all_results.items():
        for lst in lists:
            unique_lists[lst['id']] = lst

    print(f"\nTotal searches: {len(all_results)}")
    print(f"Total unique lists found across all searches: {len(unique_lists)}")

    if unique_lists:
        print("\nAll unique lists found:")
        for list_id, lst in sorted(unique_lists.items(), key=lambda x: x[1]['name']):
            print(f"  - {lst['name']}")
            print(f"    ID: {list_id} | Size: {lst['size']:,} contacts\n")

        # Look specifically for PyTorch-related lists
        pytorch_lists = [lst for lst in unique_lists.values() if 'pytorch' in lst['name'].lower()]
        if pytorch_lists:
            print(f"\nPyTorch-specific lists found: {len(pytorch_lists)}")
            for lst in pytorch_lists:
                print(f"  - {lst['name']}")
                print(f"    ID: {lst['id']} | Size: {lst['size']:,} contacts")
    else:
        print("\nNo lists found in any search.")

    return 0 if unique_lists else 1

if __name__ == "__main__":
    sys.exit(main())
