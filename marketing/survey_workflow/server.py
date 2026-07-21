"""
FastAPI backend for the Survey Workflow UI.

Two endpoints:
  POST /api/brief  - read-only stage report for an Asana task
  POST /api/build   - gated draft build (only runs once Content + Provide List are complete)
"""
import os
import json
import asyncio
import logging
import traceback

from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from asana_workflow import SurveyWorkflow

log = logging.getLogger("survey-workflow.server")
log.setLevel(logging.INFO)

app = FastAPI(title="Survey Workflow", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AsanaUrlRequest(BaseModel):
    asana_url: str
    # Optional {stage_name: bool} map to force a stage's completed status for
    # local testing, without touching the real Asana task. Stage names must
    # match stage_brief.STAGE_ORDER, e.g. {"Staging": false}.
    overrides: Optional[dict] = None
    # Optional HubSpot workflow URL to clone + wire up with the built draft
    # emails once Build completes. Takes priority over any workflow link the
    # AI finds on its own in the Asana task's comments.
    hubspot_workflow_url: Optional[str] = None


@app.post("/api/brief")
async def get_brief(req: AsanaUrlRequest):
    """Read-only: fetch the task and report which stage it's at. Takes no action."""
    try:
        workflow = SurveyWorkflow(req.asana_url, overrides=req.overrides)
        brief = await workflow.get_brief()
        return {"success": True, "brief": brief}
    except Exception as e:
        log.error(f"[BRIEF] failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


class _QueueLogHandler(logging.Handler):
    """Pushes formatted log records onto an asyncio.Queue for SSE streaming.

    summarize_brief() runs in a worker thread (via run_in_executor), so the
    queue put must be scheduled back onto the event loop thread-safely.
    """

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.queue = queue
        self.loop = loop

    def emit(self, record):
        msg = self.format(record)
        self.loop.call_soon_threadsafe(self.queue.put_nowait, msg)


@app.post("/api/brief-stream")
async def get_brief_stream(req: AsanaUrlRequest):
    """
    Same as /api/brief, but streams backend processing log lines (fetching
    task, reading comments, AI summarization) as Server-Sent Events while the
    work happens, then emits a final {"type": "result", "brief": {...}} event.
    """
    async def event_gen():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        handler = _QueueLogHandler(queue, loop)
        handler.setFormatter(logging.Formatter("%(message)s"))

        target_logger = logging.getLogger("survey-workflow")
        target_logger.addHandler(handler)
        try:
            workflow = SurveyWorkflow(req.asana_url, overrides=req.overrides)
            task = asyncio.create_task(workflow.get_brief())

            while not task.done():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=0.2)
                    yield f"data: {json.dumps({'type': 'log', 'message': msg})}\n\n"
                except asyncio.TimeoutError:
                    continue

            while not queue.empty():
                msg = queue.get_nowait()
                yield f"data: {json.dumps({'type': 'log', 'message': msg})}\n\n"

            try:
                brief = task.result()
                yield f"data: {json.dumps({'type': 'result', 'brief': brief})}\n\n"
            except Exception as e:
                log.error(f"[BRIEF-STREAM] failed: {e}\n{traceback.format_exc()}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            target_logger.removeHandler(handler)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/api/staging-preview")
async def staging_preview(req: AsanaUrlRequest):
    """
    Read-only preview for the Staging tab: existing email links if Staging
    is already complete, otherwise a preview of the 1-or-N drafts that WOULD
    be built from the content doc.
    """
    try:
        workflow = SurveyWorkflow(req.asana_url, overrides=req.overrides)
        result = await workflow.get_staging_preview()
        return result
    except Exception as e:
        log.error(f"[STAGING-PREVIEW] failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/staging-preview-stream")
async def staging_preview_stream(req: AsanaUrlRequest):
    """
    Same as /api/staging-preview, but streams the AI draft-split reasoning
    (ai_split_drafts's confidence-retry log lines) live as SSE, then emits a
    final {"type": "result", ...} event with the same shape as /api/staging-preview.
    """
    async def event_gen():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        handler = _QueueLogHandler(queue, loop)
        handler.setFormatter(logging.Formatter("%(message)s"))

        target_logger = logging.getLogger("survey-workflow")
        target_logger.addHandler(handler)
        try:
            workflow = SurveyWorkflow(req.asana_url, overrides=req.overrides)
            task = asyncio.create_task(workflow.get_staging_preview())

            while not task.done():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=0.2)
                    yield f"data: {json.dumps({'type': 'log', 'message': msg})}\n\n"
                except asyncio.TimeoutError:
                    continue

            while not queue.empty():
                msg = queue.get_nowait()
                yield f"data: {json.dumps({'type': 'log', 'message': msg})}\n\n"

            try:
                result = task.result()
                yield f"data: {json.dumps({'type': 'result', **result})}\n\n"
            except Exception as e:
                log.error(f"[STAGING-PREVIEW-STREAM] failed: {e}\n{traceback.format_exc()}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            target_logger.removeHandler(handler)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/api/build")
async def build_drafts(req: AsanaUrlRequest):
    """
    Gated build step. Returns {gated: true} without building anything if
    Content / Provide List aren't both complete yet.
    """
    try:
        workflow = SurveyWorkflow(req.asana_url, overrides=req.overrides, hubspot_workflow_url=req.hubspot_workflow_url)
        await workflow.get_brief()
        result = await workflow.build_drafts()
        return result
    except Exception as e:
        log.error(f"[BUILD] failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


class NoCacheStaticFiles(StaticFiles):
    """Dev convenience: prevents the browser from silently reusing a stale
    cached app.js/index.html across edits (StaticFiles sends no anti-cache
    headers by default)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
app.mount("/", NoCacheStaticFiles(directory=_frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8010, reload=True)
