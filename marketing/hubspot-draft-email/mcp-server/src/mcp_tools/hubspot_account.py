"""
MCP tools for HubSpot account / subscription metadata:
  - get_hubspot_portal
  - list_hubspot_subscription_types
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from ..lib.hubspot_client import hs_get

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_hubspot_portal() -> dict:
        """
        Return the HubSpot portal ID and company name for the connected account.
        Use the portal_id to build deep links into HubSpot (e.g. email editor URLs).
        """
        data = await hs_get("/account-info/v3/details")
        return {
            "portal_id": data.get("portalId"),
            "company_name": data.get("companyName", ""),
            "hub_domain": data.get("companyDomain", ""),
        }

    @mcp.tool()
    async def list_hubspot_subscription_types() -> list[dict]:
        """
        List all active HubSpot subscription/communication-preference types.

        IMPORTANT: Always present these to the user and ask them to select the
        correct one before creating any email draft. Never assume or inherit a
        subscription type from a previous email.

        Returns id, name, and description for each active type.
        """
        data = await hs_get("/communication-preferences/v3/definitions")
        definitions = (
            data.get("subscriptionDefinitions", []) if isinstance(data, dict) else []
        )
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
