"""MCP tool: get_hubspot_portal_id"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..lib.hubspot_client import hs_get


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_hubspot_portal_id() -> dict:
        """
        Return the HubSpot portal ID and company name for the connected account.
        Use this to build direct HubSpot deep-links (e.g. https://app.hubspot.com/forms/{portalId}).
        """
        data = await hs_get("/account-info/v3/details")
        return {
            "portal_id": data.get("portalId"),
            "company_name": data.get("companyName", ""),
            "hub_domain": data.get("uiDomain", ""),
        }
