"""
Flask Blueprint — all routes for the HubSpot Event List Builder.
"""

import json

from flask import Blueprint, Response, render_template, request

from .claude import get_queue, remove_job, start_job

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    return render_template("index.html")


@bp.post("/build")
def build():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return {"error": "url required"}, 400
    job_id = start_job(url)
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
