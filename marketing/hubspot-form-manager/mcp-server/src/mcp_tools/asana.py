"""
MCP tools for Asana integration:
  - get_asana_task  (used for optional pre-fill of the web form)
  - post_asana_comment
"""

from __future__ import annotations

import re

from mcp.server.fastmcp import FastMCP

from ..lib.asana_client import asana_get, asana_post, extract_task_gid
from ..lib.credentials import is_asana_configured


def _classify_request_type(notes: str) -> list[str]:
    """
    Heuristically classify an Asana task's notes into one or more request types.
    Returns a list of: FORM_CREATION, FORMS_TO_DELETE, NOTIFICATIONS_TO_DISABLE, OTHER
    """
    notes_lower = notes.lower()
    types = []
    creation_signals = ["new form", "creating a new form", "set up a form", "signup form",
                        "livestream signup", "we need a form", "build this form"]
    delete_signals = ["delete", "remove", "unused", "clean up"]
    notification_signals = ["turn off notification", "disable notification", "notifications to disable"]

    if any(s in notes_lower for s in creation_signals):
        types.append("FORM_CREATION")
    if any(s in notes_lower for s in delete_signals):
        types.append("FORMS_TO_DELETE")
    if any(s in notes_lower for s in notification_signals):
        types.append("NOTIFICATIONS_TO_DISABLE")
    if not types:
        types.append("OTHER")
    return types


def _extract_hint(notes: str, pattern: str) -> str | None:
    """
    Extract first regex match from notes, or None.
    Handles alternation patterns (e.g. group1|group2) by returning
    the first non-None capture group so .strip() never sees None.
    """
    m = re.search(pattern, notes, re.IGNORECASE)
    if not m:
        return None
    matched = next((g for g in m.groups() if g is not None), None)
    return matched.strip() if matched else None


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_asana_task(task_id: str) -> dict:
        """
        Fetch an Asana task by its GID or full URL.

        Returns the task name, notes (description), and a pre-fill suggestion dict
        that the web UI or Claude can use to populate form fields.

        Note: brand and subscription_type from pre-fill are HINTS only — the user
        must always confirm these before a form is created. Never auto-submit them.

        Requires ASANA_PAT to be configured.
        """
        if not is_asana_configured():
            return {
                "error": (
                    "Asana is not configured. "
                    "Open http://localhost:8000/setup to add your ASANA_PAT, "
                    "or fill the form manually without Asana pre-fill."
                )
            }

        gid = extract_task_gid(task_id)
        data = await asana_get(
            f"/tasks/{gid}",
            params={
                "opt_fields": "gid,name,notes,assignee.name,completed,permalink_url"
            },
        )
        task = data.get("data", {})
        notes = task.get("notes", "")

        request_types = _classify_request_type(notes)

        # Extract common hints from notes — all marked hint_only: true
        prefill: dict = {
            "request_types": request_types,
            "form_name_hint": _extract_hint(notes, r"form name[:\s]+([^\n]+)"),
            "from_address_hint": _extract_hint(notes, r"from[:\s]+([\w.+-]+@[\w.-]+\.[a-z]{2,})"),
            "workflow_hint": _extract_hint(notes, r"workflow[:\s]+([^\n]+)"),
            "brand_hint": _extract_hint(
                notes, r"brand[:\s]+([^\n]+)|business unit[:\s]+([^\n]+)"
            ),
            "subscription_hint": _extract_hint(
                notes, r"subscription[:\s]+([^\n]+)|opt.?in[:\s]+([^\n]+)"
            ),
            "hint_only": True,
            "note": (
                "These are extracted hints — brand and subscription_type MUST be "
                "explicitly confirmed by the user before creating any form."
            ),
        }

        return {
            "gid": task.get("gid"),
            "name": task.get("name"),
            "notes": notes,
            "assignee": task.get("assignee", {}).get("name") if task.get("assignee") else None,
            "completed": task.get("completed", False),
            "permalink_url": task.get("permalink_url"),
            "prefill": prefill,
        }

    @mcp.tool()
    async def post_asana_comment(task_id: str, text: str) -> dict:
        """
        Post a completion update as a comment on an Asana task.

        Use this after all HubSpot actions are complete to deliver a shareable summary
        directly to the Asana task (e.g. form URL, signup list URL, autoresponder URL).

        task_id: Asana task GID or full Asana task URL.
        text: Plain text comment body.
        """
        if not is_asana_configured():
            return {
                "error": (
                    "Asana is not configured. "
                    "Open http://localhost:8000/setup to add your ASANA_PAT."
                )
            }

        gid = extract_task_gid(task_id)
        data = await asana_post(
            f"/tasks/{gid}/stories",
            json={"data": {"text": text}},
        )
        story = data.get("data", {})
        return {
            "story_gid": story.get("gid"),
            "created_at": story.get("created_at"),
            "text_preview": text[:200] + ("..." if len(text) > 200 else ""),
            "status": "posted",
        }
