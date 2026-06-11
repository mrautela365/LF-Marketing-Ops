"""
FastAPI backend — 3 structured endpoints + free-chat.
Works in Direct Mode (no Anthropic key) or Claude Mode (key in .env).
"""
import os
import asyncio
import logging
import traceback
from fastapi import FastAPI, HTTPException
import hubspot_tools
import content_tools
from event_brands import lookup_event_brand, get_brand_events
from stage_detector import detect_stage

log = logging.getLogger("email-staging")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    log.addHandler(_h)
    log.propagate = False
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from models import PlanRequest, CloneRequest, ContentRequest, ChatRequest, GenerateContentRequest
import session_store
import agent
from config import ANTHROPIC_API_KEY, HUBSPOT_PORTAL_ID

app = FastAPI(title="Email Staging Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODE = "Claude AI (Anthropic API)" if ANTHROPIC_API_KEY else "Claude AI (Claude Code)"


@app.get("/api/status")
async def status():
    return {"mode": MODE, "hubspot_configured": bool(HUBSPOT_PORTAL_ID)}


# ── Step 1 — Generate plan ───────────────────────────────────────────────────

@app.post("/api/plan")
async def create_plan(req: PlanRequest):
    """
    Accepts brand, event_name, email_type.
    Direct mode: calls HubSpot directly and returns a formatted plan.
    Claude mode: Claude looks up history and generates the plan.
    """
    import re as _re
    session = session_store.create()
    log.info(f"[PLAN] url={req.url!r} session={session.session_id[:8]}")

    # ── Step A: Full event scrape (event + registration page + images) ─────────
    try:
        url_data = content_tools.scrape_event_full(req.url)
        session.meta["url_data"] = url_data
        log.info(
            f"[PLAN] scrape: event={url_data.get('event_name')!r} "
            f"brand={url_data.get('brand_name')!r} location={url_data.get('location')!r} "
            f"hero={bool(url_data.get('hero_image_url'))} speakers={len(url_data.get('speakers', []))}"
        )
    except Exception as e:
        log.warning(f"[PLAN] scrape_event_full failed: {e}")
        url_data = {}

    raw_event = url_data.get("event_name", "")
    location  = url_data.get("location", "")

    known = lookup_event_brand(raw_event)
    if known:
        brand_name       = known["brand_name"]
        short_brand_name = known["short_brand_name"]
        event_short_name = known["event_short_name"]
        event_name       = known["event_name"]
        log.info(f"[PLAN] event lookup: {raw_event!r} → brand={brand_name!r} short={short_brand_name!r} event_short={event_short_name!r}")
        session.meta["short_brand_name"] = short_brand_name
        session.meta["event_short_name"] = event_short_name
    else:
        brand_name       = url_data.get("brand_name", "")
        short_brand_name = ""
        event_short_name = ""
        event_name       = raw_event
        log.info(f"[PLAN] no lookup match for {raw_event!r}, using scraped brand={brand_name!r}")

    email_type = (req.email_type or "").strip()

    # ── AI-driven source email selection ──────────────────────────────────────
    # 1. Collect all event short names for this brand from the mapping so we can
    #    run multiple HubSpot searches and get 30-40 candidate emails.
    # 2. Pre-filter candidates by location keywords before handing to Claude.
    # 3. Let Claude pick with up to 5 retries. Keyword fallback if Claude fails.
    if brand_name or short_brand_name:
        try:
            import re as _re
            # Get all event short names for this brand
            brand_event_list   = get_brand_events(short_brand_name) if short_brand_name else []
            event_short_names  = list({e["event_short_name"] for e in brand_event_list})
            log.info(f"[PLAN] brand events for {short_brand_name!r}: {event_short_names}")

            candidates = hubspot_tools.get_brand_emails(
                short_brand_name, brand_name,
                event_short_names=event_short_names,
            )

            if candidates:
                # Location-based pre-filter: prefer emails mentioning the city/region
                loc_words  = {w.lower() for w in _re.findall(r'\w+', location)  if len(w) > 3}
                evt_words  = {w.lower() for w in _re.findall(r'\w+', event_name) if len(w) > 3} \
                             - {"summit", "conference", "open", "source", "linux", "foundation",
                                "cloud", "native", "north", "south", "east", "west"}

                def _relevant(e):
                    name = (e.get("name") or "").lower()
                    return any(w in name for w in loc_words) or any(w in name for w in evt_words)

                filtered   = [e for e in candidates if _relevant(e)]
                ai_pool    = filtered if len(filtered) >= 3 else candidates
                log.info(f"[PLAN] AI select: {len(candidates)} total, {len(filtered)} location-filtered → pool={len(ai_pool)}")

                selected = agent.ai_select_source_email(
                    event_name, event_short_name, location,
                    ai_pool, url=req.url,
                )
                if selected:
                    frm    = selected.get("from") or {}
                    to_obj = selected.get("to") or {}
                    ils    = to_obj.get("contactIlsLists") or {}
                    cls    = to_obj.get("contactLists") or {}
                    session.meta["brand_history"] = {
                        "found":              True,
                        "matched_email_id":   selected.get("id"),
                        "matched_email_name": selected.get("name"),
                        "from_name":          frm.get("fromName"),
                        "from_address":       frm.get("replyTo"),
                        "email_type":         selected.get("type") or "BATCH_EMAIL",
                        "suppression_list_ids": list({*ils.get("exclude", []), *cls.get("exclude", [])}),
                        "included_list_ids":    list({*ils.get("include", []), *cls.get("include", [])}),
                    }
                    log.info(f"[PLAN] AI selected: {selected.get('name')!r}")
                else:
                    log.warning("[PLAN] AI selection exhausted — falling back to keyword search")
        except Exception as e:
            log.warning(f"[PLAN] AI selection failed: {e}")

    # Keyword-scoring fallback (used when AI selection finds no confident match)
    if not session.meta.get("brand_history") and brand_name and event_name:
        try:
            brand_data = hubspot_tools.search_emails_for_event(
                brand_name, event_name, location,
                short_brand_name=short_brand_name,
                event_short_name=event_short_name,
                email_type=email_type,
            )
            if brand_data.get("found"):
                session.meta["brand_history"] = brand_data
                log.info(f"[PLAN] keyword fallback: {brand_data.get('matched_email_name')!r}")
            else:
                log.warning(f"[PLAN] no HubSpot match for brand={brand_name!r}")
        except Exception as e:
            log.warning(f"[PLAN] search_emails_for_event failed: {e}")

    # ── Step B: Stage detection ───────────────────────────────────────────────
    stage_info = detect_stage(url_data.get("event_dates", []))
    session.meta["stage_info"] = stage_info
    log.info(f"[PLAN] Stage: {stage_info['name']!r} ({stage_info['funnel']}, days={stage_info['days_to_event']})")
    # Content generation happens separately via /api/generate-content
    # (keeps /api/plan fast; frontend calls it automatically after plan loads)

    # Build brand hint for Claude so it uses the right short code in the email name
    brand_hint = None
    if short_brand_name:
        suffix_line = f"  Email suffix (from user selection): {email_type}\n" if email_type else ""
        brand_hint = (
            f"IMPORTANT — use these exact values in the Email Staging Plan:\n"
            f"  Brand name: {brand_name}\n"
            f"  Short brand code for email name: {short_brand_name}\n"
            f"  Canonical event name: {event_name}\n"
            f"{suffix_line}"
            f"  Email name format: `<YY>Q<N> - {short_brand_name} - {event_name} - <Suffix>`"
        )

    # ── Step B: Call Claude to generate the plan text ──
    combined_context = "\n\n".join(filter(None, [req.extra_context, brand_hint]))
    try:
        text, messages = agent.plan_turn(session, req.url, combined_context or None)
    except Exception as exc:
        log.error(f"[PLAN] failed: {exc}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc))

    session.messages = messages
    session.phase = "planning"
    session.plan = {"url": req.url}

    # Parse email name from Claude's plan text (backtick-formatted: `26Q2 - Brand - Event - Suffix`)
    name_match = _re.search(r"`(2\dQ\d[^`]+)`", text)
    if name_match:
        session.meta["email_name"] = name_match.group(1).strip()
        log.info(f"[PLAN] email_name parsed: {session.meta['email_name']!r}")

    session_store.update(session)

    # Surface the source/reference email so the frontend can show it before the user approves
    source_email = None
    if session.meta.get("brand_history"):
        bh = session.meta["brand_history"]
        eid  = bh.get("matched_email_id") or bh.get("last_email_id")
        ename = bh.get("matched_email_name") or bh.get("last_email_name", "")
        if eid:
            source_email = {"id": eid, "name": ename}

    return {
        "session_id":   session.session_id,
        "message":      text,
        "phase":        session.phase,
        "mode":         MODE,
        "source_email": source_email,
        "stage":        stage_info,
    }


# ── Step 1b — Generate email content ─────────────────────────────────────────

@app.post("/api/generate-content")
async def generate_content(req: GenerateContentRequest):
    """
    Called automatically by the frontend after the plan loads.
    Generates subject, preview text, and full HTML email body via Claude.
    Stores results in session and returns them.
    """
    session_id = req.session_id
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    log.info(f"[GEN-CONTENT] session={session_id[:8]}")
    try:
        url_data      = session.meta.get("url_data", {})
        stage_info    = session.meta.get("stage_info", {})
        brand_history = session.meta.get("brand_history")

        change_request = req.change_request or ""
        loop = asyncio.get_running_loop()
        generated = await loop.run_in_executor(
            None,
            lambda: agent.generate_email_content(url_data, stage_info, brand_history,
                                                  change_request=change_request)
        )

        session.meta["generated_subject"] = generated["subject"]
        session.meta["generated_preview"]  = generated["preview_text"]
        session.meta["generated_html"]     = generated["html"]
        session_store.update(session)

        log.info(f"[GEN-CONTENT] done: subject={generated['subject']!r} html_len={len(generated['html'])}")
        return {
            "session_id":        session_id,
            "generated_subject": generated["subject"],
            "generated_preview": generated["preview_text"],
            "generated_html":    generated["html"],
        }
    except Exception as exc:
        log.error(f"[GEN-CONTENT] failed: {exc}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Step 2 — Clone email ─────────────────────────────────────────────────────

@app.post("/api/clone")
async def clone_email(req: CloneRequest):
    """
    User approves the plan (with optional subject/preview text).
    Clones the email and applies all settings. Returns draft URL.
    """
    session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.phase != "planning":
        raise HTTPException(status_code=400, detail=f"Expected phase 'planning', got '{session.phase}'")
    if not req.approved:
        return {"session_id": req.session_id, "message": "Plan not approved.", "phase": "planning"}

    log.info(f"[CLONE] session={req.session_id[:8]} subject={req.subject!r}")
    try:
        text, messages = agent.clone_turn(
            session,
            subject=req.subject,
            preview_text=req.preview_text,
            send_list_id=req.send_list_id,
        )
    except Exception as exc:
        log.error(f"[CLONE] failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    session.messages = messages

    # Verify a real clone happened — use only the ID set during THIS turn
    # agent._session_email_id is reset to None at the start of clone_turn, so
    # any value here was set by the clone_email tool call in this request.
    real_email_id = agent._session_email_id
    if not real_email_id:
        log.error("[CLONE] No email_id found — Claude may have hallucinated the response without calling clone_email")
        raise HTTPException(
            status_code=500,
            detail="Email was not created in HubSpot — Claude did not call the clone tool. Please try again."
        )

    content_applied = session.meta.get("content_applied", False)
    session.phase = "complete" if content_applied else "cloned"
    session.email_id = real_email_id
    session.draft_url = f"https://app.hubspot.com/email/{HUBSPOT_PORTAL_ID}/edit/{real_email_id}/settings"
    session_store.update(session)
    log.info(f"[CLONE] verified email_id={real_email_id} content_applied={content_applied}")

    return {
        "session_id":      req.session_id,
        "message":         text,
        "phase":           session.phase,
        "email_id":        session.email_id,
        "draft_url":       session.draft_url,
        "content_applied": content_applied,
    }


# ── Step 3 — Update content ──────────────────────────────────────────────────

@app.post("/api/content")
async def update_content(req: ContentRequest):
    """
    User provides content (Google Doc URL, HTML, or plain text).
    Processes it, updates the email body, runs QA, returns final summary.
    """
    session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.phase != "cloned":
        raise HTTPException(status_code=400, detail=f"Expected phase 'cloned', got '{session.phase}'")

    log.info(f"[CONTENT] session={req.session_id[:8]} content_len={len(req.content)}")
    try:
        text, messages = agent.content_turn(session, req.content)
    except Exception as exc:
        log.error(f"[CONTENT] failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    session.messages = messages
    session.phase = "complete"
    session_store.update(session)

    return {
        "session_id": req.session_id,
        "message": text,
        "phase": session.phase,
        "draft_url": session.draft_url,
    }


# ── Free-form chat ───────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Follow-up questions or corrections at any step."""
    session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        text, messages = agent.chat_turn(session, req.message)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    session.messages = messages
    session_store.update(session)

    return {"session_id": req.session_id, "message": text, "phase": session.phase, "draft_url": session.draft_url}


# ── Session info ─────────────────────────────────────────────────────────────

@app.get("/api/lists/search")
async def search_lists(q: str = ""):
    """Searchable list picker — returns matching HubSpot lists by name."""
    if not q or len(q) < 2:
        return {"lists": []}
    return hubspot_tools.search_lists(q, limit=10)


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "phase": session.phase, "plan": session.plan,
            "email_id": session.email_id, "draft_url": session.draft_url}


# ── Serve frontend ───────────────────────────────────────────────────────────
# Mount static assets at /static (not root) to avoid shadowing API routes.
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

from fastapi.responses import FileResponse

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # Serve index.html for any non-API path (SPA catch-all)
    file_path = os.path.join(FRONTEND_DIR, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
