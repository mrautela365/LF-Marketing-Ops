"""
Flask Blueprint — all routes for the HubSpot Event List Builder.
"""

import json

from flask import Blueprint, Response, render_template, request

from .claude import get_queue, remove_job, start_job

bp = Blueprint("main", __name__)

# Temporary store: url -> segment plan text (consumed on /build)
_plans: dict[str, str] = {}


@bp.get("/")
def index():
    return render_template("index.html")


@bp.post("/receive-plan")
def receive_plan():
    """Accept a segment plan POSTed from the event-segment-planner (port 8081)."""
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    plan = (data.get("plan") or "").strip()
    if url and plan:
        _plans[url] = plan
    return {"ok": True}


@bp.get("/get-plan")
def get_plan():
    """Return (and consume) the stored segment plan for a given URL."""
    url = request.args.get("url", "").strip()
    plan = _plans.pop(url, None)
    return {"plan": plan}


@bp.post("/build")
def build():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return {"error": "url required"}, 400
    plan = (data.get("plan") or "").strip()
    if not plan:
        plan = _plans.pop(url, "")
    job_id = start_job(url, plan)
    return {"job_id": job_id}


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
