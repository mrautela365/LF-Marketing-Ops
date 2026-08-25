"""
FastAPI routes for the Implementation tab.

Two paths, gated by which email plan the user chose in Planning:
 - single email: attach the selected audience list to the approved draft.
   Never calls any HubSpot schedule/publish endpoint — the draft stays a
   draft; the user schedules/sends it themselves in HubSpot for the
   date/time they picked here.
 - 3-email sequence: clone the fixed base sequence workflow (which sends all
   3 emails itself) with the new email ids, dates, and audience list as its
   enrollment criteria. The clone is always created disabled — the user
   must open it in HubSpot and turn it on themselves when ready.
"""
from fastapi import APIRouter, HTTPException

import config
from integrations import hubspot
from models import (
    ImplementationSingleRequest, ImplementationSingleResponse,
    ImplementationSequenceRequest, ImplementationSequenceResponse,
)

router = APIRouter(prefix="/api/implementation", tags=["implementation"])


def _parse_time(value: str) -> dict:
    hour, minute = value.split(":")
    return {"hour": int(hour), "minute": int(minute)}


@router.post("/single", response_model=ImplementationSingleResponse)
def implementation_single(req: ImplementationSingleRequest):
    if not config.HUBSPOT_ACCESS_TOKEN:
        raise HTTPException(status_code=400, detail="HUBSPOT_ACCESS_TOKEN is not configured in .env")

    try:
        hubspot.set_email_send_list(req.email_id, req.list_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HubSpot API error while attaching the send list: {exc}")

    return ImplementationSingleResponse(
        email_id=req.email_id,
        list_id=req.list_id,
        draft_url=hubspot.email_edit_url(req.email_id),
        send_date=req.send_date,
        send_time=req.send_time,
    )


@router.post("/sequence", response_model=ImplementationSequenceResponse)
def implementation_sequence(req: ImplementationSequenceRequest):
    if not config.HUBSPOT_ACCESS_TOKEN:
        raise HTTPException(status_code=400, detail="HUBSPOT_ACCESS_TOKEN is not configured in .env")

    try:
        flow = hubspot.clone_sequence_workflow(
            name=req.workflow_name or "Survey Promo Sequence (AI Draft)",
            list_id=req.list_id,
            invite_email_id=req.invite_email_id,
            invite_date=req.invite.date,
            invite_time=_parse_time(req.invite.time),
            reminder_email_id=req.reminder_email_id,
            reminder_date=req.reminder.date,
            reminder_time=_parse_time(req.reminder.time),
            deadline_email_id=req.deadline_email_id,
            deadline_date=req.deadline.date,
            deadline_time=_parse_time(req.deadline.time),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"HubSpot API error while cloning the sequence workflow: {exc}",
        )

    return ImplementationSequenceResponse(
        invite_email_id=req.invite_email_id,
        invite_draft_url=hubspot.email_edit_url(req.invite_email_id),
        workflow_id=flow["flow_id"],
        workflow_url=flow["url"],
        workflow_enabled=flow["is_enabled"],
    )
