"""
MCP tools for HubSpot form management:
  - list_hubspot_forms
  - get_hubspot_form
  - create_hubspot_form
  - delete_hubspot_forms
  - update_hubspot_form_notifications
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..lib.form_builder import build_field_groups
from ..lib.hubspot_client import hs_delete, hs_get, hs_patch, hs_post

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:

    # ------------------------------------------------------------------
    # READ-ONLY TOOLS
    # ------------------------------------------------------------------

    @mcp.tool()
    async def list_hubspot_forms(query: str = "", limit: int = 20) -> list[dict]:
        """
        Search HubSpot forms by name fragment.
        Returns a list of matches with id, name, createdAt, updatedAt.
        Use this to find reference forms or locate forms before deleting/updating them.
        """
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if query:
            params["name__contains"] = query

        data = await hs_get("/marketing/v3/forms/", params=params)
        results = data.get("results", []) if isinstance(data, dict) else []

        # Filter client-side if server-side search isn't supported by this endpoint version
        if query and results:
            q_lower = query.lower()
            results = [f for f in results if q_lower in f.get("name", "").lower()]

        return [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "formType": f.get("formType"),
                "createdAt": f.get("createdAt"),
                "updatedAt": f.get("updatedAt"),
            }
            for f in results
        ]

    @mcp.tool()
    async def get_hubspot_form(form_id: str) -> dict:
        """
        Get the full details of a HubSpot form including fields, thank-you message,
        notification settings, and subscription/legal consent options.
        Use this to inspect a reference form before creating a new one from it.
        """
        data = await hs_get(f"/marketing/v3/forms/{form_id}")
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "formType": data.get("formType"),
            "fieldGroups": data.get("fieldGroups", []),
            "configuration": data.get("configuration", {}),
            "displayOptions": data.get("displayOptions", {}),
            "legalConsentOptions": data.get("legalConsentOptions", {}),
            "notificationEmails": data.get("notificationEmails", []),
            "createdAt": data.get("createdAt"),
            "updatedAt": data.get("updatedAt"),
        }

    # ------------------------------------------------------------------
    # WRITE TOOLS
    # ------------------------------------------------------------------

    @mcp.tool()
    async def create_hubspot_form(
        name: str,
        brand: str,
        fields: list[dict],
        submit_button_text: str = "Submit",
        thank_you_message: str = "Thank you for your submission.",
        notification_emails: list[str] | None = None,
        subscription_type_id: str = "",
        ctx: Context = None,
    ) -> dict:
        """
        Create a new HubSpot form with the given fields and settings.

        IMPORTANT — brand is REQUIRED. Never call this without an explicit brand/business
        unit confirmed by the user (e.g. 'LF Events', 'AAIF', 'OpenSSF').

        IMPORTANT — subscription_type_id must be confirmed by the user.
        Use list_hubspot_subscription_types to get valid IDs and present them to the user
        before calling this tool.

        Returns the new form's id, name, and a link to view it in HubSpot.
        """
        if not brand:
            return {
                "action_required": "confirm_brand",
                "message": (
                    "Which brand or business unit should this form be associated with in HubSpot? "
                    "(e.g. LF Events, AAIF, OpenSSF, CNCF). "
                    "Please confirm, then call create_hubspot_form again with the brand parameter."
                ),
            }

        if not subscription_type_id:
            return {
                "action_required": "confirm_subscription_type",
                "message": (
                    "Which subscription type should form submitters be opted into? "
                    "Use list_hubspot_subscription_types to show the user the available options, "
                    "then call create_hubspot_form again with subscription_type_id confirmed."
                ),
            }

        notification_emails = notification_emails or []
        field_groups = build_field_groups(fields or [])

        payload: dict[str, Any] = {
            "name": name,
            "formType": "hubspot",
            "fieldGroups": field_groups,
            "configuration": {
                "submitButtonText": submit_button_text,
                "thankYouType": "thankYouText",
                "thankYouMessageJson": {"richText": thank_you_message},
            },
            "notificationEmails": notification_emails,
        }

        if subscription_type_id:
            payload["legalConsentOptions"] = {
                "type": "none",  # The subscription opt-in is handled via workflow enrollment
            }

        # Elicit confirmation from the user before creating
        if ctx:
            try:
                result = await ctx.elicit(
                    message=(
                        f"Create HubSpot form?\n\n"
                        f"Name: {name}\n"
                        f"Brand: {brand}\n"
                        f"Fields: {len(fields or [])} field(s)\n"
                        f"Subscription type ID: {subscription_type_id}\n"
                        f"Notifications: {', '.join(notification_emails) if notification_emails else 'none'}"
                    ),
                    schema={
                        "type": "object",
                        "properties": {
                            "proceed": {"type": "boolean", "title": "Confirm form creation"},
                        },
                        "required": ["proceed"],
                    },
                )
                if result.action != "accept" or not result.data.get("proceed"):
                    return {"status": "cancelled", "message": "Form creation cancelled by user."}
            except Exception:
                # Host doesn't support elicitation — return a text prompt
                return {
                    "action_required": "confirm_create",
                    "message": (
                        f"Please confirm: create HubSpot form '{name}' (brand: {brand}, "
                        f"{len(fields or [])} fields, subscription ID: {subscription_type_id})? "
                        "Reply 'yes' and call create_hubspot_form again — or 'no' to cancel."
                    ),
                }

        data = await hs_post("/marketing/v3/forms/", json=payload)
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")

        return {
            "status": "created",
            "form_id": data.get("id"),
            "name": data.get("name"),
            "hubspot_url": f"https://app.hubspot.com/forms/{portal_id}/editor/{data.get('id')}",
            "brand": brand,
        }

    @mcp.tool()
    async def delete_hubspot_forms(
        form_ids: list[str],
        confirmed_names: list[str],
        ctx: Context = None,
    ) -> list[dict]:
        """
        Permanently delete one or more HubSpot forms by their IDs.

        This action CANNOT be undone. Always presents a confirmation dialog before proceeding.
        Use list_hubspot_forms to resolve form names to IDs before calling this tool.

        confirmed_names should match form_ids in order — used for the confirmation display.
        """
        if not form_ids:
            return [{"status": "error", "message": "No form IDs provided."}]

        display = ", ".join(confirmed_names) if confirmed_names else ", ".join(form_ids)

        # Always confirm before any deletion
        if ctx:
            try:
                result = await ctx.elicit(
                    message=(
                        f"Permanently delete {len(form_ids)} form(s)?\n\n"
                        f"{display}\n\n"
                        "This CANNOT be undone."
                    ),
                    schema={
                        "type": "object",
                        "properties": {
                            "proceed": {
                                "type": "boolean",
                                "title": "I understand this is permanent — delete these forms",
                            }
                        },
                        "required": ["proceed"],
                    },
                )
                if result.action != "accept" or not result.data.get("proceed"):
                    return [{"status": "cancelled", "message": "Deletion cancelled by user."}]
            except Exception:
                return [
                    {
                        "action_required": "confirm_deletion",
                        "message": (
                            f"Confirmation required before deleting: {display}. "
                            "These deletions are PERMANENT and cannot be undone. "
                            "Ask the user to explicitly confirm, then call delete_hubspot_forms again."
                        ),
                    }
                ]

        results = []
        names = confirmed_names if len(confirmed_names) == len(form_ids) else [""] * len(form_ids)

        for form_id, name in zip(form_ids, names):
            try:
                await hs_delete(f"/marketing/v3/forms/{form_id}")
                results.append({"form_id": form_id, "name": name, "status": "deleted"})
                logger.info("Deleted HubSpot form %s (%s)", form_id, name)
            except Exception as e:
                status = "not_found" if "404" in str(e) else "error"
                results.append({"form_id": form_id, "name": name, "status": status, "error": str(e)})
                logger.warning("Failed to delete form %s: %s", form_id, e)

        return results

    @mcp.tool()
    async def update_hubspot_form_notifications(
        form_id: str,
        notification_emails: list[str],
    ) -> dict:
        """
        Update the email notification recipients for a HubSpot form.
        Pass an empty list to disable all notifications.

        Returns the updated notification_emails list.
        """
        data = await hs_patch(
            f"/marketing/v3/forms/{form_id}",
            json={"notificationEmails": notification_emails},
        )
        return {
            "form_id": form_id,
            "notification_emails": data.get("notificationEmails", notification_emails),
            "status": "updated",
        }
