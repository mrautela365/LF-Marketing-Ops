#!/usr/bin/env python3
"""
Manual smoke test for the Audience Builder discovery agent — hits live HubSpot
(and, if configured, Snowflake + a real LLM backend). Not run in CI; invoke
directly like the sibling test_tools.py / pytorch_list_builder.py scripts:

    python audience_builder/smoke_test_discovery.py [event_url]

Section 2 (compose_master_list_from_ids) is guarded behind an env var since it
writes a real HubSpot list — set RUN_COMPOSE=1 and pass real test list IDs via
TEST_LIST_IDS (comma-separated) to exercise it. Relies on ASSET_TAG tagging
(see config.py) for safe cleanup, same convention as other scripts here.
"""
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audience_builder.discovery_agent import start_discovery_job, get_job_queue, remove_job
from audience_builder.master_list import compose_master_list_from_ids

DEFAULT_EVENT_URL = "https://events.linuxfoundation.org/kubecon-cloudnativecon-north-america/"


def run_discovery(event_url: str):
    print("=" * 80)
    print(f"DISCOVERY: {event_url}")
    print("=" * 80)

    job_id = start_discovery_job(event_url)
    q = get_job_queue(job_id)

    result = {"lists": [], "uncertain": []}
    deadline = time.time() + 600  # 10 min ceiling for a manual run
    while time.time() < deadline:
        try:
            item = q.get(timeout=5)
        except Exception:
            print("  ...(waiting)")
            continue

        if item.get("type") == "output":
            print(("  [delta] " if item.get("delta") else "  ") + item.get("text", ""))
        elif item.get("type") == "discovered":
            print(f"\n  >>> discovered: {len(item.get('lists', []))} lists, "
                  f"{len(item.get('uncertain', []))} uncertain\n")
        elif item.get("done"):
            result["lists"] = item.get("lists", [])
            result["uncertain"] = item.get("uncertain", [])
            print(f"\n  DONE — success={item.get('success')}")
            break

    remove_job(job_id)

    print("\n" + "-" * 80)
    print("present_discovered_lists payload:")
    print(json.dumps(result, indent=2, default=str))
    print("-" * 80)
    return result


def run_compose(list_ids):
    print("\n" + "=" * 80)
    print(f"COMPOSE MASTER LIST from: {list_ids}")
    print("=" * 80)
    result = compose_master_list_from_ids(list_ids)
    print(json.dumps(result, indent=2, default=str))
    print(f"\nInspect/clean up manually at: {result.get('hubspot_url')}")
    return result


if __name__ == "__main__":
    try:
        event_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EVENT_URL
        run_discovery(event_url)

        if os.getenv("RUN_COMPOSE") == "1":
            raw_ids = os.getenv("TEST_LIST_IDS", "")
            ids = [x.strip() for x in raw_ids.split(",") if x.strip()]
            if not ids:
                print("\nRUN_COMPOSE=1 but TEST_LIST_IDS is empty — skipping compose step.")
            else:
                run_compose(ids)
        else:
            print("\n(Set RUN_COMPOSE=1 and TEST_LIST_IDS=<id1,id2,...> to also exercise compose_master_list_from_ids.)")
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
