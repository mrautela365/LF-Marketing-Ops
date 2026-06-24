"""
Flask Blueprint — routes for the LF Event Audience Studio.
"""

import json

from flask import Blueprint, Response, render_template, request

from .agent import get_queue, remove_job, start_job
from .prompts import BUILDING_PROMPT, PLANNING_PROMPT

bp = Blueprint("main", __name__)


@bp.get("/health")
def health():
    """Config status — shows which credentials are present."""
    import os
    return {
        "status": "ok",
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "hubspot": bool(os.environ.get("HUBSPOT_API_KEY")),
        "snowflake": bool(
            os.environ.get("SNOWFLAKE_ACCOUNT")
            and os.environ.get("SNOWFLAKE_USER")
            and os.environ.get("SNOWFLAKE_PASSWORD")
        ),
    }


@bp.get("/")
def index():
    return render_template("index.html")


@bp.post("/plan")
def plan():
    """Phase 1 — start segment planning job."""
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return {"error": "url required"}, 400
    prompt = PLANNING_PROMPT.format(url=url)
    return {"job_id": start_job(prompt)}


@bp.post("/build")
def build():
    """Phase 2 — start list building job (no re-scraping)."""
    data = request.get_json(force=True)
    url  = (data.get("url")  or "").strip()
    plan = (data.get("plan") or "").strip()
    qa   = (data.get("qa")   or "").strip()
    if not url:
        return {"error": "url required"}, 400

    qa_section = ""
    if qa:
        qa_section = f"\nUser answers to clarifying questions:\n{qa}\n"

    prompt = BUILDING_PROMPT.format(url=url, plan=plan, qa_section=qa_section)
    return {"job_id": start_job(prompt)}


@bp.get("/stream/<job_id>")
def stream(job_id: str):
    q = get_queue(job_id)
    if q is None:
        def err():
            yield f"data: {json.dumps({'error': 'not found', 'done': True})}\n\n"
        return Response(err(), mimetype="text/event-stream")

    def generate():
        while True:
            try:
                item = q.get(timeout=3)
            except Exception:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                continue
            yield f"data: {json.dumps(item)}\n\n"
            if item.get("done"):
                remove_job(job_id)
                break

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
