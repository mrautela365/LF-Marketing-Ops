#!/usr/bin/env python3
"""
CLI runner for the Survey Workflow.

Usage:
    python cli.py <asana_task_url> [--build] [--verbose]

By default this only prints the stage brief (read-only). Pass --build to
also run the gated draft-build step once Content + Provide List are done.
"""
import asyncio
import sys
import logging
import argparse
from asana_workflow import SurveyWorkflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


def _print_brief(brief: dict):
    print(f"\nTask: {brief['task_name']}")
    print(f"Current stage: {brief['current_stage']}")
    print(f"Ready to build: {brief['ready_to_build']}")
    if brief.get("overall_summary"):
        print(f"\nOverall: {brief['overall_summary']}")
    print(f"\n{'Stage':<18}{'Assignee':<22}{'Completed':<12}{'Due':<12}Note")
    print("-" * 80)
    for s in brief["stages"]:
        note = "no action needed (upstream)" if s["no_action_required"] else ""
        print(f"{s['name']:<18}{s['assignee']:<22}{str(s['completed']):<12}{s['due_on'] or '-':<12}{note}")
        if s.get("summary"):
            print(f"    -> {s['summary']}")
    if brief.get("content_doc_url"):
        print(f"\nContent doc: {brief['content_doc_url']}")
    if brief.get("hubspot_list_url"):
        print(f"Send list:   {brief['hubspot_list_url']}")


async def main():
    parser = argparse.ArgumentParser(description="Run the Survey Workflow automation")
    parser.add_argument("asana_url", help="The parent Asana task URL to process")
    parser.add_argument("--build", action="store_true", help="Also build drafts once ready (not just brief)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print(f"\nFetching brief for: {args.asana_url}")
    workflow = SurveyWorkflow(args.asana_url)
    brief = await workflow.get_brief()
    _print_brief(brief)

    if not args.build:
        return 0

    if not brief["ready_to_build"]:
        print("\nNot ready to build - Content and/or Provide List are not yet complete.")
        return 1

    print("\nBuilding draft(s)...")
    result = await workflow.build_drafts()

    print("\n" + "=" * 80)
    print("BUILD RESULT")
    print("=" * 80)
    for d in result.get("drafts", []):
        if d.get("success"):
            print(f"[OK] Draft {d['draft_index']}: {d['email_name']} -> {d['draft_url']}")
        else:
            print(f"[FAILED] Draft {d['draft_index']}: {d.get('error')}")

    if result.get("warnings"):
        print("\nWarnings:")
        for w in result["warnings"]:
            print(f"  - {w}")

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
