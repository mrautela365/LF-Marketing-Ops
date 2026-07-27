"""
API routes for the Audience Builder tab — existing-list discovery + master
list composition. Mounted in main.py via app.include_router(audience_builder_router),
registered BEFORE the static-files mount / SPA catch-all so it isn't shadowed.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import audience_tools
from audience_builder import discovery_agent
from audience_builder.last_sent import find_last_sent_emails
from audience_builder.master_list import compose_master_list_from_ids, find_standard_suppression_lists, union_size
from audience_builder.models import ComposeMasterListRequest, DiscoverListsRequest, PreviewCountRequest

log = logging.getLogger("email-staging")

router = APIRouter(prefix="/api/audience-builder", tags=["audience-builder"])


@router.post("/discover")
async def discover_lists(req: DiscoverListsRequest):
    """Start a discovery job — finds existing HubSpot lists for the given event
    URL and classifies them into the 5 signals. Returns job_id for SSE polling."""
    event_url = req.event_url.strip()
    if not event_url:
        raise HTTPException(status_code=400, detail="event_url is required")

    job_id = discovery_agent.start_discovery_job(event_url, qa=req.qa)
    log.info(f"[AUDIENCE-BUILDER] discover job {job_id[:8]} url={event_url!r}")
    return {"job_id": job_id, "event_url": event_url}


@router.get("/discover-stream/{job_id}")
async def stream_discovery(job_id: str):
    """SSE stream of discovery agent output. Each event is JSON:
    {type:'output'|'discovered'|'done', ...}."""
    q = discovery_agent.get_job_queue(job_id)
    if q is None:
        async def not_found():
            yield f"data: {json.dumps({'type': 'error', 'text': 'Job not found', 'done': True})}\n\n"
        return StreamingResponse(not_found(), media_type="text/event-stream")

    async def generate():
        loop = asyncio.get_running_loop()
        while True:
            try:
                item = await loop.run_in_executor(None, lambda: q.get(timeout=5))
            except Exception:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                continue

            yield f"data: {json.dumps(item)}\n\n"

            if item.get("done"):
                discovery_agent.remove_job(job_id)
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/lists/search")
async def search_lists(q: str = ""):
    """Search-and-add support — thin pass-through to audience_tools.hubspot_search_lists
    (NOT /api/lists/search, which hard-restricts to MANUAL/SNAPSHOT lists and would miss
    the DYNAMIC lists that make up most of the 5 discovery signals)."""
    query = q.strip()
    if not query:
        return {"query": "", "results": []}
    try:
        return audience_tools.hubspot_search_lists(query)
    except Exception as exc:
        log.error(f"[AUDIENCE-BUILDER] lists/search failed: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/suppression-lists")
async def suppression_lists(brand_short: str = "", event_name: str = ""):
    """Deterministic (non-LLM) lookup of the standard hygiene suppression
    lists (GDPR/opt-out/master-exclusion), by name search — most recently
    updated match per category. Used to pre-populate the Suppression &
    Exclusions section, pre-selected by default. When brand_short/event_name
    are given, also looks for a brand-scoped Global Opt-Out list and an
    existing per-event suppression list (see master_list.py for why those are
    separate from the 6 generic portfolio-wide terms)."""
    try:
        return {"results": find_standard_suppression_lists(brand_short=brand_short, event_name=event_name)}
    except Exception as exc:
        log.error(f"[AUDIENCE-BUILDER] suppression-lists failed: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/last-sent")
async def last_sent(event_name: str = "", brand_short: str = ""):
    """Deterministic (non-LLM) lookup of the most recently sent marketing
    email(s) for this event, and which HubSpot lists they used — surfaced at
    the top of the discovery results so a user can see what was sent last
    time before picking lists for a new send."""
    try:
        return {"results": find_last_sent_emails(event_name=event_name, brand_short=brand_short)}
    except Exception as exc:
        log.error(f"[AUDIENCE-BUILDER] last-sent failed: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/preview-count")
async def preview_count(req: PreviewCountRequest):
    """Cumulative contact count across the currently-selected lists. Exact
    (de-duplicated via membership pagination) when the combined estimated
    size is under union_size()'s cap, otherwise a naive sum-of-sizes estimate
    that may double-count contacts belonging to more than one selected list."""
    if not req.list_ids:
        raise HTTPException(status_code=400, detail="list_ids must not be empty")
    try:
        return union_size(req.list_ids)
    except Exception as exc:
        log.error(f"[AUDIENCE-BUILDER] preview-count failed: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/compose-master")
async def compose_master(req: ComposeMasterListRequest):
    """Build the master list from the selected/added list IDs, as an
    OR-of-IN_LIST filterBranch. If exclude_list_ids is given, first builds a
    single Combined Suppression list and applies it as a NOT_IN_LIST exclusion
    in every inclusion branch. If a list with the resolved name already
    exists, a new list is created with a timestamp appended to the name."""
    if not req.list_ids:
        raise HTTPException(status_code=400, detail="list_ids must not be empty")

    try:
        result = compose_master_list_from_ids(
            req.list_ids,
            name=req.name,
            event_url=req.event_url,
            brand_short=req.brand_short,
            event_name=req.event_name,
            exclude_list_ids=req.exclude_list_ids,
        )
        log.info(f"[AUDIENCE-BUILDER] master list composed: {result['list_id']} ({result['name']})")
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error(f"[AUDIENCE-BUILDER] compose-master failed: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))
