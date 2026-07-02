"""
MCP tools for HubSpot audience list management:
  - validate_audience_lists
  - search_hubspot_lists
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from ..lib.hubspot_client import hs_get

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def validate_audience_lists(list_ids: list[str]) -> list[dict]:
        """
        Fetch health metadata for one or more HubSpot contact list IDs.

        Checks:
          - List exists (404 → flag immediately)
          - List type: Active vs Static (Static + stale = warn)
          - Membership size (0 = critical block; <10 = warn)
          - Last updated date

        Use this BEFORE drafting any email to confirm the audience is valid.
        Never draft for an empty list.

        Returns one result dict per list_id.
        """
        results = []
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")

        for list_id in list_ids:
            try:
                data = await hs_get(
                    f"/contacts/v1/lists/{list_id}",
                    params={"count": 1},
                )
                size = data.get("metaData", {}).get("size", -1)
                list_type = data.get("listType", "UNKNOWN")
                name = data.get("name", f"List {list_id}")
                updated_at = data.get("updatedAt")

                issues = []
                severity = "ok"

                if size == 0:
                    issues.append("List is empty (0 contacts). Do NOT send to this list.")
                    severity = "critical"
                elif 0 < size < 10:
                    issues.append(f"Very small list ({size} contacts) — verify this is correct.")
                    severity = "warn"

                if list_type == "STATIC":
                    issues.append(
                        "Static list — verify it was recently updated and reflects current consent."
                    )
                    if severity == "ok":
                        severity = "warn"

                results.append(
                    {
                        "list_id": list_id,
                        "name": name,
                        "list_type": list_type,
                        "size": size,
                        "updated_at": updated_at,
                        "issues": issues,
                        "severity": severity,
                        "list_url": (
                            f"https://app.hubspot.com/contacts/{portal_id}/objectLists/{list_id}"
                            if portal_id
                            else None
                        ),
                    }
                )

            except Exception as e:
                status_code = "404" if "404" in str(e) else "error"
                results.append(
                    {
                        "list_id": list_id,
                        "name": None,
                        "list_type": None,
                        "size": None,
                        "issues": [
                            "List not found — verify the list ID is correct."
                            if status_code == "404"
                            else f"Error fetching list: {e}"
                        ],
                        "severity": "critical",
                        "list_url": None,
                    }
                )
                logger.warning("Failed to fetch list %s: %s", list_id, e)

        return results

    @mcp.tool()
    async def search_hubspot_lists(query: str, limit: int = 20) -> list[dict]:
        """
        Search HubSpot contact lists by name fragment.

        Use this to help the user find audience or suppression list IDs before
        creating a draft. Returns id, name, type, and size.
        """
        data = await hs_get(
            "/contacts/v1/lists/",
            params={"count": min(limit, 100), "offset": 0},
        )
        lists = data.get("lists", []) if isinstance(data, dict) else []

        if query:
            q_lower = query.lower()
            lists = [lst for lst in lists if q_lower in lst.get("name", "").lower()]

        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")

        return [
            {
                "list_id": lst.get("listId"),
                "name": lst.get("name"),
                "list_type": lst.get("listType"),
                "size": lst.get("metaData", {}).get("size", -1),
                "list_url": (
                    f"https://app.hubspot.com/contacts/{portal_id}/objectLists/{lst.get('listId')}"
                    if portal_id
                    else None
                ),
            }
            for lst in lists[:limit]
        ]
