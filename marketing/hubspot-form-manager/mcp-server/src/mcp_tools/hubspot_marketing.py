"""
MCP tools for HubSpot marketing operations:
  - list_hubspot_subscription_types
  - find_hubspot_form_submission_list
  - create_hubspot_email
  - enroll_form_in_workflow
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..lib.hubspot_client import hs_get, hs_patch, hs_post

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def list_hubspot_subscription_types() -> list[dict]:
        """
        List all active HubSpot subscription types.

        Use this BEFORE creating a form to show the user the real subscription type names
        and IDs. The user must explicitly select the correct one — never assume or copy
        from a reference form without confirmation.
        """
        data = await hs_get("/communication-preferences/v3/definitions")
        definitions = data.get("subscriptionDefinitions", []) if isinstance(data, dict) else []
        return [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "description": d.get("description", ""),
                "isActive": d.get("isActive", True),
            }
            for d in definitions
            if d.get("isActive", True)
        ]

    @mcp.tool()
    async def find_hubspot_form_submission_list(form_name: str) -> dict:
        """
        Find the auto-created HubSpot contacts list for a form's submissions.
        HubSpot automatically creates a list named "[Form name] (HubSpot form submissions)"
        when a form is published.

        Returns the list's ID and a direct URL to view it in HubSpot.
        """
        # Search by name — the list is named "[form name] (HubSpot form submissions)"
        search_name = f"{form_name} (HubSpot form submissions)"
        data = await hs_get(
            "/contacts/v1/lists/",
            params={"count": 20, "offset": 0},
        )
        lists = data.get("lists", []) if isinstance(data, dict) else []

        # Match by partial name (case-insensitive)
        form_name_lower = form_name.lower()
        for lst in lists:
            list_name: str = lst.get("name", "")
            if form_name_lower in list_name.lower():
                portal_data = await hs_get("/account-info/v3/details")
                portal_id = portal_data.get("portalId", "")
                list_id = lst.get("listId")
                return {
                    "list_id": list_id,
                    "name": list_name,
                    "list_url": f"https://app.hubspot.com/contacts/{portal_id}/lists/{list_id}",
                }

        return {
            "list_id": None,
            "name": search_name,
            "list_url": None,
            "note": (
                "List not found. It may take a few minutes after form creation "
                "for HubSpot to auto-create the submission list. Try again shortly."
            ),
        }

    @mcp.tool()
    async def create_hubspot_email(
        name: str,
        subject: str,
        from_name: str,
        from_email: str,
        body_html: str,
        is_transactional: bool = True,
    ) -> dict:
        """
        Create a HubSpot automated email (autoresponder).

        Set is_transactional=True for confirmation/livestream emails — this bypasses
        subscription status so all form submitters receive it regardless of opt-in.

        Returns email_id, name, and a preview_url for testing before going live.

        NOTE: If the from_email address is not set up as a verified sender in HubSpot,
        the API will return an error. Use the fallback address specified in the task
        and flag this clearly in the delivery summary.
        """
        payload: dict[str, Any] = {
            "name": name,
            "subject": subject,
            "fromName": from_name,
            "replyTo": from_email,
            "emailBody": body_html,
            "emailType": "AUTOMATED_EMAIL",
            "isTransactional": is_transactional,
        }

        data = await hs_post("/marketing/v3/emails/", json=payload)
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")
        email_id = data.get("id")

        return {
            "email_id": email_id,
            "name": data.get("name"),
            "subject": data.get("subject"),
            "from_email": from_email,
            "is_transactional": is_transactional,
            "preview_url": f"https://app.hubspot.com/email/{portal_id}/edit/{email_id}/settings",
            "status": "created",
        }

    @mcp.tool()
    async def enroll_form_in_workflow(
        workflow_name_query: str,
        form_id: str,
        ctx: Context = None,
    ) -> dict:
        """
        Search for a HubSpot workflow by name and add a 'Contact submitted form' trigger.

        If multiple workflows match the query, uses elicit() to ask the user to choose one.
        Never enrolls in a workflow without explicit user confirmation.

        workflow_name_query: partial name to search for, e.g. 'AAIF' or 'Subscription'
        form_id: the HubSpot form ID to use as the trigger condition
        """
        if not workflow_name_query:
            return {
                "action_required": "confirm_workflow",
                "message": (
                    "Which HubSpot workflow (if any) should form submitters be enrolled in? "
                    "Please provide the exact workflow name or a search term."
                ),
            }

        # Search workflows
        data = await hs_get("/automation/v4/flows/", params={"limit": 50})
        flows = data.get("results", []) if isinstance(data, dict) else []

        query_lower = workflow_name_query.lower()
        matches = [f for f in flows if query_lower in f.get("name", "").lower()]

        if not matches:
            return {
                "status": "not_found",
                "message": (
                    f"No workflows found matching '{workflow_name_query}'. "
                    "Check the workflow name in HubSpot Automation → Workflows and retry."
                ),
            }

        # Multiple matches — ask user to choose
        if len(matches) > 1 and ctx:
            try:
                options = {str(i + 1): m.get("name", "") for i, m in enumerate(matches[:5])}
                options_text = "\n".join(f"{k}. {v}" for k, v in options.items())
                result = await ctx.elicit(
                    message=f"Multiple workflows match '{workflow_name_query}':\n\n{options_text}\n\nWhich one should submitters be enrolled in?",
                    schema={
                        "type": "object",
                        "properties": {
                            "choice": {
                                "type": "integer",
                                "title": "Enter the number of the workflow to use",
                                "minimum": 1,
                                "maximum": len(matches[:5]),
                            }
                        },
                        "required": ["choice"],
                    },
                )
                if result.action == "accept":
                    choice_idx = int(result.data.get("choice", 1)) - 1
                    matches = [matches[choice_idx]]
                else:
                    return {"status": "cancelled", "message": "Workflow enrollment cancelled."}
            except Exception:
                names_list = ", ".join(m.get("name", "") for m in matches[:5])
                return {
                    "action_required": "choose_workflow",
                    "message": (
                        f"Multiple workflows match: {names_list}. "
                        "Please specify the exact workflow name and call enroll_form_in_workflow again."
                    ),
                }

        workflow = matches[0]
        workflow_id = workflow.get("id")

        # Add FORM_SUBMISSION trigger to the workflow
        trigger_payload = {
            "type": "FORM_SUBMISSION",
            "formId": form_id,
        }

        try:
            await hs_patch(
                f"/automation/v4/flows/{workflow_id}/enrollmentCriteria",
                json={"triggers": [trigger_payload]},
            )
        except Exception as e:
            logger.warning("Could not patch workflow triggers via API: %s. Manual enrollment may be required.", e)
            portal_data = await hs_get("/account-info/v3/details")
            portal_id = portal_data.get("portalId", "")
            return {
                "workflow_id": workflow_id,
                "workflow_name": workflow.get("name"),
                "form_id": form_id,
                "status": "manual_action_required",
                "message": (
                    f"Could not automatically add the form trigger. Please open "
                    f"https://app.hubspot.com/workflows/{portal_id}/{workflow_id}/edit "
                    "and manually add 'Contact submitted form' → select the new form as a trigger."
                ),
            }

        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow.get("name"),
            "form_id": form_id,
            "status": "trigger_added",
        }
