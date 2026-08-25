#!/usr/bin/env python3
"""Execute the Seoul audience lookup workflow sequentially."""
import sys
import json
import os

# Add current dir to path
sys.path.insert(0, os.path.dirname(__file__))

import audience_tools

def main():
    results = {}

    # Step 1: Read brand master lists
    print("Step 1: Reading brand-master-lists.md...")
    brand_master = audience_tools.read_reference_file("brand-master-lists.md")
    results["brand_master"] = brand_master
    print(f"  [OK] Read {len(brand_master.get('content', ''))} chars")

    # Step 2: Search for Seoul mailable lists
    print("\nStep 2: Searching for 'Seoul mailable' lists...")
    search_results = audience_tools.hubspot_search_lists("Seoul mailable")
    results["all_lists_found"] = search_results.get("results", [])
    print(f"  [OK] Found {len(results['all_lists_found'])} lists")

    # Identify the most relevant list
    most_relevant = None
    if search_results.get("results"):
        # Prefer the exact match or closest match
        all_results = search_results["results"]
        for r in all_results:
            name = r.get("name", "").lower()
            if "seoul" in name and ("26q3" in name or "mailable" in name):
                most_relevant = r
                break
        if not most_relevant and all_results:
            most_relevant = all_results[0]

    results["most_relevant_list"] = most_relevant

    # Step 3: Get the most relevant list details
    if most_relevant:
        list_id = most_relevant.get("listId")
        print(f"\nStep 3: Getting list details for {list_id}...")
        try:
            list_details = audience_tools.hubspot_get_list(list_id)
            results["reference_list"] = list_details
            results["reference_list_id"] = list_id
            results["reference_list_name"] = list_details.get("name")
            results["reference_filter_branch"] = list_details.get("filterBranch", {})
            results["reference_list_size"] = list_details.get("size")
            list_name = list_details.get("name") or "[Unknown]"
            list_size = list_details.get("size") or "unknown"
            print(f"  [OK] Retrieved list: {list_name} (size: {list_size})")
        except Exception as e:
            print(f"  [ERROR] Failed to get list details: {e}")
            results["reference_list"] = None
            results["reference_list_id"] = list_id

    # Step 4: Get event types (specifically for 6-58204655)
    print("\nStep 4: Getting event type definitions...")
    try:
        event_types_response = audience_tools.hubspot_get_event_types()
        results["event_types_response"] = event_types_response
    except Exception as e:
        print(f"  [ERROR] Failed to get event types: {e}")
        event_types_response = {}
        results["event_types_response"] = {}

    # Find the Education Enrolled event type
    education_event_type = None
    education_topic_property = None

    if event_types_response.get("results"):
        for evt in event_types_response["results"]:
            # Match by fullyQualifiedName containing "Education Enrolled" or by ID pattern
            name = evt.get("fullyQualifiedName") or ""
            label = evt.get("label") or ""
            if "education" in (name or "").lower() or "education" in (label or "").lower():
                education_event_type = evt
                # Look for topic/course/subject property
                props = evt.get("properties", []) or []
                for prop in props:
                    prop_name = (prop.get("name") or "").lower()
                    prop_label = (prop.get("label") or "").lower()
                    if any(x in prop_name or x in prop_label for x in ["course", "topic", "subject", "program"]):
                        education_topic_property = prop.get("name")
                        break
                break

    results["education_event_type"] = education_event_type
    results["education_topic_property"] = education_topic_property

    print(f"  [OK] Retrieved {len(event_types_response.get('results', []))} event type definitions")
    if education_event_type:
        print(f"    - Education event type: {education_event_type.get('label')}")
        if education_topic_property:
            print(f"    - Topic property: {education_topic_property}")

    # Build final JSON response
    final_response = {
        "brand_key": "TBD",  # To be extracted from brand-master-lists.md
        "master_list_id": "TBD",  # To be extracted from brand-master-lists.md
        "reference_list_name": results.get("reference_list_name"),
        "reference_list_id": results.get("reference_list_id"),
        "reference_filter_branch": results.get("reference_filter_branch", {}),
        "reference_list_size": results.get("reference_list_size"),
        "education_event_type": results.get("education_event_type"),
        "education_topic_property": results.get("education_topic_property"),
        "all_lists_found": results.get("all_lists_found", []),
    }

    print("\n" + "="*60)
    print("FINAL RESULT")
    print("="*60)
    try:
        result_json = json.dumps(final_response, indent=2, default=str)
        print(result_json)
    except Exception as json_err:
        print(f"JSON encoding error: {json_err}")
        # Fallback: print as string representation
        print(str(final_response))

    return final_response

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
