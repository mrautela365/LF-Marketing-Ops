"""
/api/asana/* REST routes — called by the web UI for optional pre-fill.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..lib.asana_client import asana_get, asana_post, extract_task_gid
from ..lib.credentials import is_asana_configured
from ..models.hubspot import ApiResponse, AsanaTaskUrlRequest, PostCommentRequest
from ..mcp_tools.asana import _classify_request_type, _extract_hint

router = APIRouter(prefix="/api/asana")


@router.post("/task")
async def get_task_prefill(req: AsanaTaskUrlRequest) -> ApiResponse:
    """
    Fetch an Asana task and return structured pre-fill hints for the web form.
    All hints are marked hint_only=true — user must confirm before form creation.
    """
    if not is_asana_configured():
        return ApiResponse(
            success=False,
            error=(
                "Asana is not configured. "
                "Open /setup to add your ASANA_PAT, or fill the form manually."
            ),
        )

    try:
        gid = extract_task_gid(req.url)
        data = await asana_get(
            f"/tasks/{gid}",
            params={"opt_fields": "gid,name,notes,assignee.name,completed,permalink_url"},
        )
        task = data.get("data", {})
        notes = task.get("notes", "")

        prefill = {
            "request_types": _classify_request_type(notes),
            "form_name_hint": _extract_hint(notes, r"form name[:\s]+([^\n]+)"),
            "from_address_hint": _extract_hint(notes, r"from[:\s]+([\w.+-]+@[\w.-]+\.[a-z]{2,})"),
            "workflow_hint": _extract_hint(notes, r"workflow[:\s]+([^\n]+)"),
            "brand_hint": _extract_hint(notes, r"brand[:\s]+([^\n]+)|business unit[:\s]+([^\n]+)"),
            "subscription_hint": _extract_hint(notes, r"subscription[:\s]+([^\n]+)|opt.?in[:\s]+([^\n]+)"),
            "hint_only": True,
        }

        return ApiResponse(success=True, data={
            "gid": task.get("gid"),
            "name": task.get("name"),
            "notes": notes,
            "permalink_url": task.get("permalink_url"),
            "prefill": prefill,
        })
    except ValueError as e:
        return ApiResponse(success=False, error=str(e))
    except Exception as e:
        return ApiResponse(success=False, error=f"Asana API error: {e}")


@router.post("/comment")
async def post_comment(req: PostCommentRequest) -> ApiResponse:
    """Post a completion update as a comment on an Asana task."""
    if not is_asana_configured():
        return ApiResponse(
            success=False,
            error="Asana is not configured. Open /setup to add your ASANA_PAT.",
        )

    try:
        gid = extract_task_gid(req.task_id)
        data = await asana_post(
            f"/tasks/{gid}/stories",
            json={"data": {"text": req.text}},
        )
        story = data.get("data", {})
        return ApiResponse(success=True, data={
            "story_gid": story.get("gid"),
            "created_at": story.get("created_at"),
        })
    except ValueError as e:
        return ApiResponse(success=False, error=str(e))
    except Exception as e:
        return ApiResponse(success=False, error=f"Asana API error: {e}")
