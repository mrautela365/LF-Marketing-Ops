"""
Flask Blueprint — routes for the LF Event Audience Studio.
"""

import json
from pathlib import Path

from flask import Blueprint, Response, render_template, request

from .claude import get_queue, remove_job, start_job
from .prompts import BUILDING_PROMPT, PLANNING_PROMPT

# Each phase runs from the sibling app that owns the skill + references/
_MARKETING = Path(__file__).parent.parent.parent
PLANNER_CWD  = str(_MARKETING / "event-segment-planner")
BUILDER_CWD  = str(_MARKETING / "hubspot-event-list-builder")

# Read SKILL.md files at startup so they're embedded directly in the prompt
# (claude -p does not invoke slash commands the same way as interactive mode)
def _read_skill(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

PLANNER_SKILL = _read_skill(_MARKETING / "event-segment-planner" / "SKILL.md")
BUILDER_SKILL = _read_skill(_MARKETING / "hubspot-event-list-builder" / "SKILL.md")

bp = Blueprint("main", __name__)


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
    prompt = PLANNING_PROMPT.format(url=url, skill=PLANNER_SKILL)
    return {"job_id": start_job(prompt, cwd=PLANNER_CWD)}


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

    prompt = BUILDING_PROMPT.format(url=url, plan=plan, qa_section=qa_section, skill=BUILDER_SKILL)
    return {"job_id": start_job(prompt, cwd=BUILDER_CWD)}


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
