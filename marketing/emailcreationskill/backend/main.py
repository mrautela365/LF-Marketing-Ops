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
from models import PlanRequest, CloneRequest, ContentRequest, ChatRequest, GenerateContentRequest, StagingBriefRequest, AsanaPlanRequest, BuildAudienceRequest
import session_store
import agent
import audience_tools
from config import ANTHROPIC_API_KEY, HUBSPOT_PORTAL_ID, INTERNAL_API_TOKEN, ASANA_ACCESS_TOKEN, LITELLM_BASE_URL, LITELLM_API_KEY
import asana_tools
import json

app = FastAPI(title="Email Staging Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if LITELLM_BASE_URL and LITELLM_API_KEY:
    MODE = f"Claude AI (LiteLLM — {LITELLM_BASE_URL})"
elif ANTHROPIC_API_KEY:
    MODE = "Claude AI (Anthropic API)"
else:
    MODE = "Claude AI (Claude Code)"

log.info(f"[STARTUP] AI mode: {MODE} | model: {__import__('config').CLAUDE_MODEL}")


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
        session.meta["generated_html"]     = generated["html"]       # full preview HTML (UI)
        session.meta["body_html"]          = generated.get("body_html", generated["html"])
        session.meta["banner_url"]         = generated.get("banner_url", "")
        session_store.update(session)

        log.info(f"[GEN-CONTENT] done: subject={generated['subject']!r} "
                 f"html_len={len(generated['html'])} banner={'yes' if generated.get('banner_url') else 'no'}")
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


# ── Skill integration — stateless brief staging ─────────────────────────────

@app.post("/api/stage-from-brief")
async def stage_from_brief(req: StagingBriefRequest):
    """
    Called by the email-staging-v3 skill after it has:
      • Parsed the Asana task and confirmed the Email Brief with the user
      • Built the audience list (Phase 3 of the skill)
      • Fetched the Google Doc HTML (Phase 2) — passed as raw_html

    Does NOT use sessions. Clones + applies settings + injects content in one call.
    Content priority: raw_html (doc HTML) → event_url (AI generation) → none.
    """
    # Auth — if token is configured enforce it; if not, warn and allow (local dev)
    if INTERNAL_API_TOKEN and req.internal_token != INTERNAL_API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid internal_token. Set INTERNAL_API_TOKEN in .env.")
    if not INTERNAL_API_TOKEN:
        log.warning("[BRIEF] INTERNAL_API_TOKEN not set — accepting unauthenticated call. "
                    "Set it in .env for production use.")

    log.info(f"[BRIEF] email_name={req.email_name!r} clone_base={req.clone_base_id!r} "
             f"has_doc_html={bool(req.raw_html)} has_event_url={bool(req.event_url)}")

    try:
        # ── Step 1: Clone ────────────────────────────────────────────────────
        clone_result = hubspot_tools.clone_email(req.clone_base_id, req.email_name)
        new_email_id = clone_result["email_id"]
        draft_url    = clone_result["draft_url"]
        agent._session_email_id = new_email_id   # register safety lock
        log.info(f"[BRIEF] cloned → {new_email_id}")

        # ── Step 2: Apply settings ───────────────────────────────────────────
        settings_kw: dict = {"email_id": new_email_id}
        if req.from_name:            settings_kw["from_name"]            = req.from_name
        if req.from_address:         settings_kw["from_address"]         = req.from_address
        if req.subject:              settings_kw["subject"]               = req.subject
        if req.preview_text:         settings_kw["preview_text"]          = req.preview_text
        if req.email_type:           settings_kw["email_type"]            = req.email_type
        if req.send_list_id:         settings_kw["send_list_id"]          = req.send_list_id
        if req.suppression_list_ids: settings_kw["suppression_list_ids"]  = req.suppression_list_ids
        hubspot_tools.update_email_settings(**settings_kw)
        log.info(f"[BRIEF] settings applied: {[k for k in settings_kw if k != 'email_id']}")

        # ── Step 3: Content ──────────────────────────────────────────────────
        content_applied = False
        content_source  = "none"
        final_subject   = req.subject
        final_preview   = req.preview_text

        if req.raw_html:
            # Doc HTML provided — inject directly (no AI generation)
            hubspot_tools.update_email_content(new_email_id, req.raw_html)
            content_applied = True
            content_source  = "doc"
            log.info(f"[BRIEF] content: doc HTML injected ({len(req.raw_html):,} chars)")

        elif req.event_url:
            # No doc — scrape event page for images, then AI-generate body
            loop     = asyncio.get_running_loop()
            url_data = await loop.run_in_executor(
                None,
                lambda: content_tools.scrape_event_full(req.event_url)
            )
            # Merge in fields from request (override scraped values if user supplied them)
            url_data["event_name"]  = req.event_name  or url_data.get("event_name",  "")
            url_data["event_dates"] = req.event_dates or url_data.get("event_dates", [])
            url_data["location"]    = req.location    or url_data.get("location",    "")
            url_data["description"] = req.description or url_data.get("description", "")
            url_data["url"]         = req.event_url

            stage_info = detect_stage(url_data["event_dates"])
            generated  = await loop.run_in_executor(
                None,
                lambda: agent.generate_email_content(url_data, stage_info, None)
            )
            hubspot_tools.update_email_content(
                new_email_id,
                generated.get("body_html", generated["html"]),
                banner_url=generated.get("banner_url", ""),
                event_url=req.event_url,
            )
            content_applied = True
            content_source  = "ai"
            final_subject   = generated["subject"]      or req.subject
            final_preview   = generated["preview_text"] or req.preview_text
            log.info(
                f"[BRIEF] content: AI-generated from {req.event_url!r} "
                f"banner={'yes' if generated.get('banner_url') else 'no'}"
            )

        else:
            log.info("[BRIEF] no content provided — clone + settings only")

        return {
            "email_id":        new_email_id,
            "draft_url":       draft_url,
            "email_name":      req.email_name,
            "content_applied": content_applied,
            "content_source":  content_source,   # "doc" | "ai" | "none"
            "subject":         final_subject,
            "preview_text":    final_preview,
        }

    except Exception as exc:
        log.error(f"[BRIEF] failed: {exc}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc))


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


# ── Asana tab — pre-fill brief from Asana task ──────────────────────────────

@app.post("/api/plan-from-asana")
async def plan_from_asana(req: AsanaPlanRequest):
    """
    Called by the 'From Asana Task' tab in the web UI.
    Reads the Asana task + subtasks + comments, fetches the linked Google Doc HTML,
    searches HubSpot for brand settings, and returns a pre-filled brief for the user
    to review + edit before calling /api/stage-from-brief.
    """
    log.info(f"[ASANA] task_url={req.asana_url!r} has_token={bool(ASANA_ACCESS_TOKEN)}")
    warnings: list[str] = []

    try:
        # ── 1. Fetch Asana task (REST API if token set, MCP fallback otherwise) ──
        loop = asyncio.get_running_loop()

        if ASANA_ACCESS_TOKEN:
            gid      = asana_tools.parse_task_gid(req.asana_url)
            task     = asana_tools.get_task(gid)
            subtasks = asana_tools.get_subtasks(gid)
            all_gids = [gid] + [st["gid"] for st in subtasks if st.get("gid")]
            stories_list = await asyncio.gather(*[
                loop.run_in_executor(None, asana_tools.get_stories, g) for g in all_gids
            ])
            all_stories = {g: s for g, s in zip(all_gids, stories_list)}
            brief = asana_tools.extract_brief(task, subtasks, all_stories)
            log.info(f"[ASANA] REST API fetch: task={brief['task_name']!r}")
        else:
            log.info("[ASANA] No ASANA_ACCESS_TOKEN — using Asana MCP via Claude subprocess")
            warnings.append("ASANA_ACCESS_TOKEN not configured — task data fetched via MCP connector (may be slower).")
            try:
                brief = await loop.run_in_executor(
                    None, lambda: agent.fetch_asana_task_via_mcp(req.asana_url)
                )
            except Exception as mcp_err:
                raise HTTPException(status_code=503, detail=(
                    f"ASANA_ACCESS_TOKEN is not configured and MCP fallback failed: {mcp_err}. "
                    "Add ASANA_ACCESS_TOKEN to your .env file, or authenticate the Asana MCP connector."
                ))
            log.info(f"[ASANA] MCP fetch: task={brief.get('task_name')!r}")

        log.info(
            f"[ASANA] task={brief['task_name']!r} brand={brief['brand_name']!r} "
            f"event_url={brief['event_url']!r} doc={brief['content_doc_url']!r}"
        )

        # ── 2. HubSpot brand lookup ───────────────────────────────────────────
        clone_base_id   = ""
        clone_base_name = ""
        from_name       = ""
        from_address    = ""
        email_type      = "BATCH_EMAIL"
        suppression_ids: list[str] = []
        send_list_id    = ""

        brand_name  = brief["brand_name"]
        event_url   = brief["event_url"]
        event_name  = ""
        location    = ""

        if brand_name or event_url:
            try:
                if event_url:
                    try:
                        url_data   = content_tools.scrape_event_full(event_url)
                        event_name = url_data.get("event_name", "")
                        location   = url_data.get("location", "")
                        if not brand_name:
                            brand_name = url_data.get("brand_name", "")
                    except Exception as e:
                        warnings.append(f"Could not scrape event URL: {e}")

                known = lookup_event_brand(event_name or brand_name) if (event_name or brand_name) else None
                short_brand_name = known["short_brand_name"] if known else ""
                event_short_name = known["event_short_name"] if known else ""

                brand_event_list  = get_brand_events(short_brand_name) if short_brand_name else []
                event_short_names = list({e["event_short_name"] for e in brand_event_list})

                candidates = hubspot_tools.get_brand_emails(
                    short_brand_name, brand_name,
                    event_short_names=event_short_names,
                )

                if candidates:
                    selected = agent.ai_select_source_email(
                        event_name or brand_name,
                        event_short_name,
                        location,
                        candidates,
                        url=event_url or "",
                    )
                    if selected:
                        frm    = selected.get("from") or {}
                        to_obj = selected.get("to") or {}
                        ils    = to_obj.get("contactIlsLists") or {}
                        cls    = to_obj.get("contactLists") or {}
                        from_name    = frm.get("fromName", "")
                        from_address = frm.get("replyTo", "")
                        email_type   = selected.get("type") or "BATCH_EMAIL"
                        clone_base_id   = str(selected.get("id", ""))
                        clone_base_name = selected.get("name", "")
                        all_excl = list({*ils.get("exclude", []), *cls.get("exclude", [])})
                        suppression_ids = [str(x) for x in all_excl]
                        all_incl = list({*ils.get("include", []), *cls.get("include", [])})
                        if all_incl:
                            send_list_id = str(all_incl[0])
                        log.info(f"[ASANA] HubSpot selected: {clone_base_name!r} id={clone_base_id}")
                    else:
                        warnings.append("Could not confidently select a clone base email from HubSpot.")
                else:
                    warnings.append(f"No sent emails found in HubSpot for brand '{brand_name}'.")
            except Exception as e:
                warnings.append(f"HubSpot brand search failed: {e}")
                log.warning(f"[ASANA] HubSpot search failed: {e}")
        else:
            warnings.append("Could not determine brand name from task. Fill in From Name/Address manually.")

        # ── 3. Fetch Google Doc HTML ─────────────────────────────────────────
        doc_html = ""
        if brief["content_doc_url"]:
            try:
                doc_html = content_tools.prepare_content(brief["content_doc_url"])
                log.info(f"[ASANA] doc HTML: {len(doc_html):,} chars")
            except Exception as e:
                warnings.append(f"Could not fetch Google Doc content: {e}")
                log.warning(f"[ASANA] doc fetch failed: {e}")

        return {
            # Email brief — all editable by the user before staging
            "email_name":            brief["email_name"],
            "from_name":             from_name,
            "from_address":          from_address,
            "subject":               "",
            "preview_text":          "",
            "email_type":            email_type,
            "clone_base_id":         clone_base_id,
            "clone_base_name":       clone_base_name,
            "suppression_list_ids":  suppression_ids,
            "send_list_id":          send_list_id,
            # Content
            "doc_html":              doc_html,
            "doc_url":               brief["content_doc_url"],
            "event_url":             brief["event_url"],
            # Task meta (read-only display)
            "audience_instructions": brief["audience_instructions"],
            "warnings":              warnings,
            "task_name":             brief["task_name"],
            "due_on":                brief["due_on"],
            "subtask_names":         brief["subtask_names"],
        }

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        log.error(f"[ASANA] failed: {exc}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Audience list builder ─────────────────────────────────────────────────────

@app.post("/api/build-audience")
async def start_build_audience(req: BuildAudienceRequest):
    """
    Start a Claude subprocess that builds HubSpot audience lists for the event.
    Uses the hubspot-event-list-builder skill (SKILL.md + Snowflake + HubSpot MCP).
    Returns job_id — poll /api/audience-stream/{job_id} for SSE output.
    """
    session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    event_url = (req.event_url or "").strip()
    if not event_url:
        event_url = (session.meta.get("url_data") or {}).get("url", "")
    if not event_url:
        raise HTTPException(status_code=400, detail="No event URL — provide event_url or run plan first")

    job_id = audience_tools.start_build_job(event_url)
    log.info(f"[AUDIENCE] job started: {job_id[:8]} url={event_url!r}")
    return {"job_id": job_id, "event_url": event_url}


@app.get("/api/audience-stream/{job_id}")
async def stream_audience_build(job_id: str, session_id: str = ""):
    """
    SSE stream of the audience build Claude subprocess.
    Each event is JSON: {type, text} or {type:'complete', done:True, master_list_id:'...'}.
    When complete, stores master_list_id in session.meta so clone uses it as send_list_id.
    """
    from fastapi.responses import StreamingResponse

    q = audience_tools.get_job_queue(job_id)
    if q is None:
        async def not_found():
            yield f"data: {json.dumps({'type':'error','text':'Job not found','done':True})}\n\n"
        return StreamingResponse(not_found(), media_type="text/event-stream")

    accumulated: list[str] = []

    async def generate():
        loop = asyncio.get_event_loop()
        while True:
            try:
                item = await loop.run_in_executor(None, lambda: q.get(timeout=5))
            except Exception:
                yield f"data: {json.dumps({'type':'heartbeat'})}\n\n"
                continue

            if item.get("type") == "output" and item.get("text"):
                accumulated.append(item["text"])

            yield f"data: {json.dumps(item)}\n\n"

            if item.get("done"):
                all_text   = "\n".join(accumulated)
                master_id  = audience_tools.extract_master_list_id(all_text)

                if session_id and master_id:
                    session = session_store.get(session_id)
                    if session:
                        session.meta["audience_list_id"] = master_id
                        session_store.update(session)
                        log.info(f"[AUDIENCE] master list {master_id} stored in session {session_id[:8]}")

                yield f"data: {json.dumps({'type':'complete','done':True,'master_list_id':master_id,'success':item.get('success',False)})}\n\n"
                audience_tools.remove_job(job_id)
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
