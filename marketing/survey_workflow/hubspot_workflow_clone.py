"""
Survey-workflow-only HubSpot Workflow (Automation v4 Flows) cloning.

The v4 Flows API has no clone endpoint (verified against the live portal -
POST /automation/v4/flows/clone and /automation/v4/flows/{id}/clone both
404/405), so this reads the full flow definition via GET, swaps each
SEND_EMAIL action's email (actionTypeId "0-4") for the newly built draft
emails in flow order, optionally overwrites each "wait until date" action's
(actionTypeId "0-35") target date with a date pulled from the content doc,
then POSTs the modified definition as a brand-new flow.

Kept separate from emailcreationskill/backend so this behavior only affects
survey_workflow.

Safety: the cloned flow is always created with isEnabled=False, so it can
never send anything until a human reviews it in HubSpot and turns it on.
"""
import os
import re
import sys
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emailcreationskill', 'backend'))

from hubspot_tools import _get, _post
from config import HUBSPOT_PORTAL_ID, tag_asset_name

log = logging.getLogger("survey-workflow.hubspot-workflow-clone")

_SEND_EMAIL_ACTION_TYPE_ID = "0-4"
_WAIT_UNTIL_DATE_ACTION_TYPE_ID = "0-35"


def extract_flow_id(url: str) -> str:
    m = re.search(r"/flow/(\d+)", url or "")
    return m.group(1) if m else ""


def _ordered_actions_by_type(flow: dict, action_type_id: str) -> list:
    """Actions of a given actionTypeId, in flow order (ascending numeric actionId)."""
    actions = [a for a in flow.get("actions", []) if a.get("actionTypeId") == action_type_id]
    return sorted(actions, key=lambda a: int(a["actionId"]))


def date_to_epoch_millis(iso_date: str) -> str:
    """'YYYY-MM-DD' -> epoch-millis string at 00:00:00 UTC (matches HubSpot's staticValue format)."""
    dt = datetime.strptime(iso_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return str(int(dt.timestamp() * 1000))


def clone_and_replace_workflow_emails(
    flow_id: str,
    clone_name: str,
    email_ids_in_order: list,
    send_dates: list = None,
) -> dict:
    """
    Read-then-recreate clone of a HubSpot workflow. Replaces each SEND_EMAIL
    action's content_id with the next id in `email_ids_in_order`, in flow
    order (both must be the same length as the number of SEND_EMAIL actions
    already in the source flow - this only swaps emails in place, it does not
    add/remove send steps). If `send_dates` (a list of 'YYYY-MM-DD' strings,
    same length as the number of "wait until date" actions) is given, each of
    those actions' target date is overwritten, keeping the original
    time_of_day untouched.

    The new flow is always created with isEnabled=False.

    Guardrail: `flow_id` (the source) is only ever READ via GET below. All
    edits happen on an in-memory dict that is then POSTed to the collection
    endpoint to CREATE a brand-new flow - nothing is ever PATCHed/PUT back
    onto `flow_id` itself.
    """
    flow = _get(f"/automation/v4/flows/{flow_id}")

    send_actions = _ordered_actions_by_type(flow, _SEND_EMAIL_ACTION_TYPE_ID)
    if len(send_actions) != len(email_ids_in_order):
        raise ValueError(
            f"Source workflow {flow_id} has {len(send_actions)} send-email step(s) but "
            f"{len(email_ids_in_order)} draft email(s) were built - counts must match."
        )
    for action, email_id in zip(send_actions, email_ids_in_order):
        action["fields"]["content_id"] = str(email_id)
    log.info(f"[WORKFLOW CLONE] mapped {len(send_actions)} send-email step(s) to the new draft email(s), in order")

    date_actions = _ordered_actions_by_type(flow, _WAIT_UNTIL_DATE_ACTION_TYPE_ID)
    if send_dates:
        if len(date_actions) != len(send_dates):
            raise ValueError(
                f"Source workflow {flow_id} has {len(date_actions)} delay-until-date step(s) but "
                f"{len(send_dates)} date(s) were found in the doc - counts must match."
            )
        for action, iso_date in zip(date_actions, send_dates):
            action["fields"]["date"]["staticValue"] = date_to_epoch_millis(iso_date)
        log.info(f"[WORKFLOW CLONE] updated {len(date_actions)} delay-until-date step(s) from the doc: {send_dates}")
    else:
        log.info("[WORKFLOW CLONE] no send dates found in doc - leaving delay-until-date steps as cloned")

    new_flow = {
        "name": tag_asset_name(clone_name),
        "flowType": flow.get("flowType", "WORKFLOW"),
        "isEnabled": False,
        "startActionId": flow.get("startActionId"),
        "nextAvailableActionId": flow.get("nextAvailableActionId"),
        "actions": flow.get("actions", []),
        "enrollmentCriteria": flow.get("enrollmentCriteria"),
        "timeWindows": flow.get("timeWindows", []),
        "blockedDates": flow.get("blockedDates", []),
        "customProperties": flow.get("customProperties", {}),
        "dataSources": flow.get("dataSources", []),
        "suppressionListIds": flow.get("suppressionListIds", []),
        "goalFilterBranch": flow.get("goalFilterBranch"),
        "canEnrollFromSalesforce": flow.get("canEnrollFromSalesforce", False),
        "type": flow.get("type"),
        "objectTypeId": flow.get("objectTypeId"),
    }
    new_flow = {k: v for k, v in new_flow.items() if v is not None}

    created = _post("/automation/v4/flows", new_flow)
    new_flow_id = created.get("id")
    if not new_flow_id:
        raise ValueError(f"Workflow create API did not return an id. Response: {created}")

    log.info(f"[WORKFLOW CLONE] cloned workflow {flow_id} -> new {new_flow_id} (disabled - review in HubSpot before enabling)")

    return {
        "flow_id": new_flow_id,
        "flow_name": created.get("name", new_flow["name"]),
        "edit_url": f"https://app.hubspot.com/workflows/{HUBSPOT_PORTAL_ID}/platform/flow/{new_flow_id}/edit",
        "source_flow_id": flow_id,
        "source_flow_name": flow.get("name", ""),
        "is_enabled": False,
        "send_email_count": len(send_actions),
        "delay_date_count": len(date_actions) if send_dates else 0,
    }
