"""
/api/hubspot/* REST routes — called by the web UI.
These reuse the same underlying logic as the MCP tools.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from ..lib.email_builder import build_email_payload, validate_draft_spec
from ..lib.hubspot_client import hs_delete, hs_get, hs_patch, hs_post
from ..lib.qa_runner import run_qa
from ..lib.utm_tagger import UtmSpec, audit_all_links, build_utm_url
from ..models.email import (
    ApiResponse,
    ApplyUtmRequest,
    CreateDraftRequest,
    DeleteDraftRequest,
    QaRequest,
    ScheduleRequest,
    UpdateDraftRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/hubspot")


# ── ACCOUNT ──────────────────────────────────────────────────────────────────

@router.get("/portal")
async def get_portal() -> ApiResponse:
    try:
        data = await hs_get("/account-info/v3/details")
        return ApiResponse(
            success=True,
            data={
                "portal_id": data.get("portalId"),
                "company_name": data.get("companyName", ""),
            },
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/subscription-types")
async def get_subscription_types() -> ApiResponse:
    try:
        data = await hs_get("/communication-preferences/v3/definitions")
        definitions = (
            data.get("subscriptionDefinitions", []) if isinstance(data, dict) else []
        )
        return ApiResponse(
            success=True,
            data=[
                {
                    "id": d.get("id"),
                    "name": d.get("name"),
                    "description": d.get("description", ""),
                }
                for d in definitions
                if d.get("isActive", True)
            ],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── LISTS ────────────────────────────────────────────────────────────────────

@router.get("/lists/search")
async def search_lists(q: str = Query(""), limit: int = 20) -> ApiResponse:
    try:
        data = await hs_get(
            "/contacts/v1/lists/", params={"count": min(limit, 100), "offset": 0}
        )
        lists = data.get("lists", []) if isinstance(data, dict) else []
        if q:
            q_lower = q.lower()
            lists = [lst for lst in lists if q_lower in lst.get("name", "").lower()]
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")
        return ApiResponse(
            success=True,
            data=[
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
            ],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/lists/{list_id}/validate")
async def validate_list(list_id: str) -> ApiResponse:
    try:
        data = await hs_get(f"/contacts/v1/lists/{list_id}")
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")
        size = data.get("metaData", {}).get("size", -1)
        list_type = data.get("listType", "UNKNOWN")
        issues = []
        severity = "ok"
        if size == 0:
            issues.append("List is empty — do not send to this list.")
            severity = "critical"
        elif 0 < size < 10:
            issues.append(f"Very small list ({size} contacts) — verify this is correct.")
            severity = "warn"
        if list_type == "STATIC":
            issues.append("Static list — verify recent update and current consent.")
            if severity == "ok":
                severity = "warn"
        return ApiResponse(
            success=True,
            data={
                "list_id": list_id,
                "name": data.get("name"),
                "list_type": list_type,
                "size": size,
                "issues": issues,
                "severity": severity,
                "list_url": (
                    f"https://app.hubspot.com/contacts/{portal_id}/objectLists/{list_id}"
                    if portal_id
                    else None
                ),
            },
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── EMAIL DRAFTS ──────────────────────────────────────────────────────────────

@router.get("/emails")
async def list_drafts(q: str = Query(""), limit: int = 20) -> ApiResponse:
    try:
        params = {"limit": min(limit, 100), "state": "DRAFT"}
        data = await hs_get("/marketing/v3/emails/", params=params)
        results = data.get("results", []) if isinstance(data, dict) else []
        if q:
            q_lower = q.lower()
            results = [r for r in results if q_lower in r.get("name", "").lower()]
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")
        return ApiResponse(
            success=True,
            data=[
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "subject": r.get("subject"),
                    "status": r.get("state"),
                    "updated_at": r.get("updatedAt"),
                    "hubspot_url": (
                        f"https://app.hubspot.com/email/{portal_id}/edit/{r.get('id')}/settings"
                        if portal_id
                        else None
                    ),
                }
                for r in results
            ],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/emails/{draft_id}")
async def get_draft(draft_id: str) -> ApiResponse:
    try:
        data = await hs_get(f"/marketing/v3/emails/{draft_id}")
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")
        return ApiResponse(
            success=True,
            data={
                "id": data.get("id"),
                "name": data.get("name"),
                "subject": data.get("subject"),
                "preheader": data.get("previewText", ""),
                "from_name": data.get("fromName", ""),
                "from_email": data.get("fromEmail", ""),
                "reply_to": data.get("replyTo", ""),
                "status": data.get("state"),
                "subscription_id": data.get("subscriptionId"),
                "updated_at": data.get("updatedAt"),
                "hubspot_url": (
                    f"https://app.hubspot.com/email/{portal_id}/edit/{draft_id}/settings"
                    if portal_id
                    else None
                ),
            },
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/emails/qa")
async def run_qa_check(req: QaRequest) -> ApiResponse:
    """
    Run the full 5-section QA suite against a draft spec.
    Does NOT create a draft — for pre-flight validation only.
    """
    try:
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = str(portal_data.get("portalId", ""))

        audience_lists = []
        for list_id in req.audience_list_ids:
            try:
                lst = await hs_get(f"/contacts/v1/lists/{list_id}")
                audience_lists.append(
                    {
                        "id": list_id,
                        "name": lst.get("name", list_id),
                        "listType": lst.get("listType", "UNKNOWN"),
                        "size": lst.get("metaData", {}).get("size", -1),
                    }
                )
            except Exception:
                audience_lists.append(
                    {"id": list_id, "name": list_id, "listType": "UNKNOWN", "size": -1}
                )

        draft = {
            **req.draft,
            "audience_list_ids": req.audience_list_ids,
            "suppression_list_ids": req.suppression_list_ids,
        }
        report = run_qa(draft=draft, portal_id=portal_id, audience_lists=audience_lists)
        return ApiResponse(success=True, data=report.to_dict())
    except Exception as e:
        logger.exception("QA check error")
        return ApiResponse(success=False, error=str(e))


@router.post("/emails")
async def create_draft(req: CreateDraftRequest) -> ApiResponse:
    """
    Create a HubSpot email draft. Always saved as DRAFT — never auto-sends.
    Validates the spec and returns any warnings along with the draft details.
    """
    spec = req.model_dump()
    if req.utm_spec:
        spec["utm_spec"] = req.utm_spec.model_dump()

    issues = validate_draft_spec(spec)
    critical = [i for i in issues if i["severity"] == "critical"]
    if critical:
        return ApiResponse(
            success=False,
            error="Critical issues must be resolved before creating this draft.",
            data={"issues": critical},
        )

    try:
        payload = build_email_payload(spec)
        data = await hs_post("/marketing/v3/emails/", json=payload)
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")
        draft_id = data.get("id")

        warnings = [i for i in issues if i["severity"] in ("high", "medium")]
        return ApiResponse(
            success=True,
            data={
                "draft_id": draft_id,
                "name": data.get("name"),
                "subject": data.get("subject"),
                "hubspot_url": (
                    f"https://app.hubspot.com/email/{portal_id}/edit/{draft_id}/settings"
                    if portal_id
                    else None
                ),
                "warnings": warnings,
            },
        )
    except Exception as e:
        logger.exception("Error creating email draft")
        return ApiResponse(success=False, error=str(e))


@router.patch("/emails/{draft_id}")
async def update_draft(draft_id: str, req: UpdateDraftRequest) -> ApiResponse:
    try:
        current = await hs_get(f"/marketing/v3/emails/{draft_id}")
        state = current.get("state", "")
        if state not in ("DRAFT", "SCHEDULED"):
            return ApiResponse(
                success=False,
                error=f"Email is in state '{state}' — only DRAFT or SCHEDULED emails can be updated.",
            )
        patch = req.to_hubspot_patch()
        if not patch:
            return ApiResponse(success=False, error="No fields to update provided.")
        data = await hs_patch(f"/marketing/v3/emails/{draft_id}", json=patch)
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")
        return ApiResponse(
            success=True,
            data={
                "draft_id": draft_id,
                "name": data.get("name"),
                "hubspot_url": (
                    f"https://app.hubspot.com/email/{portal_id}/edit/{draft_id}/settings"
                    if portal_id
                    else None
                ),
            },
        )
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.delete("/emails/{draft_id}")
async def delete_draft(draft_id: str, confirmed_name: str = Query("")) -> ApiResponse:
    """
    Delete a draft. Web UI is responsible for showing the confirmation dialog first.
    """
    try:
        current = await hs_get(f"/marketing/v3/emails/{draft_id}")
        state = current.get("state", "")
        if state != "DRAFT":
            return ApiResponse(
                success=False,
                error=f"Email is in state '{state}' — only DRAFT emails can be deleted.",
            )
        await hs_delete(f"/marketing/v3/emails/{draft_id}")
        return ApiResponse(
            success=True,
            data={"draft_id": draft_id, "name": confirmed_name, "status": "deleted"},
        )
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.post("/emails/{draft_id}/schedule")
async def schedule_draft(draft_id: str, req: ScheduleRequest) -> ApiResponse:
    try:
        data = await hs_get(f"/marketing/v3/emails/{draft_id}")
        state = data.get("state", "")
        if state != "DRAFT":
            return ApiResponse(
                success=False,
                error=f"Email is in state '{state}' — only DRAFT emails can be scheduled.",
            )
        # Pre-schedule blockers
        subscription_id = data.get("subscriptionId")
        body = data.get("content", {}).get("body", "")
        has_unsub = any(
            kw in body.lower() for kw in ["unsubscribe", "opt-out", "subscription preferences"]
        )
        blockers = []
        if not subscription_id:
            blockers.append("No subscription type assigned.")
        if not has_unsub:
            blockers.append("No unsubscribe link in email body.")
        if blockers:
            return ApiResponse(
                success=False,
                error="Pre-schedule QA failed.",
                data={"blockers": blockers},
            )
        updated = await hs_patch(
            f"/marketing/v3/emails/{draft_id}",
            json={"scheduledAt": req.scheduled_at_iso},
        )
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")
        return ApiResponse(
            success=True,
            data={
                "draft_id": draft_id,
                "scheduled_at": req.scheduled_at_iso,
                "hubspot_url": (
                    f"https://app.hubspot.com/email/{portal_id}/edit/{draft_id}/settings"
                    if portal_id
                    else None
                ),
            },
        )
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.post("/emails/{draft_id}/utm")
async def apply_utm(draft_id: str, req: ApplyUtmRequest) -> ApiResponse:
    try:
        data = await hs_get(f"/marketing/v3/emails/{draft_id}")
        body_html: str = data.get("content", {}).get("body", "")
        if not body_html:
            return ApiResponse(
                success=False, error="No HTML body found on this draft."
            )
        utm_spec = UtmSpec(campaign=req.utm_campaign)
        audits = audit_all_links(body_html, utm_spec)
        to_fix = [a for a in audits if not a["has_utm"] and a.get("corrected_url")]

        if not to_fix:
            return ApiResponse(
                success=True, data={"message": "All links already have UTM parameters.", "fixed": 0}
            )

        updated_html = body_html
        for a in to_fix:
            original = a["url"]
            corrected = a["corrected_url"]
            if req.utm_content_map and original in req.utm_content_map:
                spec_override = UtmSpec(
                    campaign=req.utm_campaign, content=req.utm_content_map[original]
                )
                corrected = build_utm_url(original, spec_override)
            updated_html = updated_html.replace(f'href="{original}"', f'href="{corrected}"')
            updated_html = updated_html.replace(f"href='{original}'", f"href='{corrected}'")

        await hs_patch(
            f"/marketing/v3/emails/{draft_id}", json={"content": {"body": updated_html}}
        )
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")
        return ApiResponse(
            success=True,
            data={
                "links_fixed": len(to_fix),
                "hubspot_url": (
                    f"https://app.hubspot.com/email/{portal_id}/edit/{draft_id}/settings"
                    if portal_id
                    else None
                ),
            },
        )
    except Exception as e:
        return ApiResponse(success=False, error=str(e))
