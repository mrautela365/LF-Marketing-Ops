"""
FastAPI routes for the Audience Builder "Reuse or Discover Existing Audience"
feature. Ported/adapted from
emailcreationskill/backend/audience_builder/routes.py — `import audience_tools`
references replaced with `audience_builder.tools`.
"""
import json
import queue

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from audience_builder import discovery_agent, last_sent, master_list
from audience_builder import tools as abt
from audience_builder.models import (
    ComposeMasterListRequest, ComposeMasterListResponse,
    DiscoverListsRequest, PreviewCountRequest, PreviewCountResponse,
)

router = APIRouter(prefix="/api/audience-builder", tags=["audience-builder"])


@router.post("/discover")
def discover_lists(req: DiscoverListsRequest):
    if not req.event_url:
        raise HTTPException(400, "event_url is required")
    try:
        job_id = discovery_agent.start_discovery_job(req.event_url, req.qa)
        return {"job_id": job_id}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, str(exc))


@router.get("/discover-stream/{job_id}")
def discover_stream(job_id: str):
    q = discovery_agent.get_job_queue(job_id)
    if q is None:
        raise HTTPException(404, "Unknown or already-completed job_id")

    def _gen():
        while True:
            try:
                item = q.get(timeout=5)
            except queue.Empty:
                yield "event: heartbeat\ndata: {}\n\n"
                continue
            yield f"data: {json.dumps(item)}\n\n"
            if item.get("done"):
                discovery_agent.remove_job(job_id)
                break
            if item.get("type") == "done":
                discovery_agent.remove_job(job_id)
                break

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/lists/search")
def search_lists(q: str):
    try:
        return abt.hubspot_search_lists(q)
    except Exception as exc:
        raise HTTPException(502, str(exc))


@router.get("/suppression-lists")
def suppression_lists(brand_short: str = "", event_name: str = ""):
    try:
        return {"suppression_lists": master_list.find_standard_suppression_lists(brand_short, event_name)}
    except Exception as exc:
        raise HTTPException(502, str(exc))


@router.get("/last-sent")
def last_sent_route(event_name: str, brand_short: str = ""):
    if not event_name:
        raise HTTPException(400, "event_name is required")
    try:
        return {"emails": last_sent.find_last_sent_emails(event_name, brand_short)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, str(exc))


@router.get("/existing-master-lists")
def existing_master_lists(event_name: str = "", brand_short: str = ""):
    try:
        return {"master_lists": master_list.find_existing_master_lists(brand_short, event_name)}
    except Exception as exc:
        raise HTTPException(502, str(exc))


@router.post("/preview-count", response_model=PreviewCountResponse)
def preview_count(req: PreviewCountRequest):
    if not req.list_ids:
        raise HTTPException(400, "list_ids is required")
    try:
        return master_list.union_size(req.list_ids)
    except Exception as exc:
        raise HTTPException(502, str(exc))


@router.post("/compose-master", response_model=ComposeMasterListResponse)
def compose_master(req: ComposeMasterListRequest):
    if not req.list_ids:
        raise HTTPException(400, "list_ids is required")
    try:
        return master_list.compose_master_list_from_ids(
            req.list_ids, req.name, req.event_url, req.brand_short,
            req.event_name, exclude_list_ids=req.exclude_list_ids,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, str(exc))
