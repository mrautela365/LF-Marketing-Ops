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
from event_brands import lookup_event_brand, get_brand_events, expand_location_words, location_fallback_chain, extract_location_from_name, build_location_chain, filter_candidates_by_locale
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
from models import PlanRequest, CloneRequest, ContentRequest, ChatRequest, GenerateContentRequest, StagingBriefRequest, AsanaPlanRequest, AudiencePlanRequest, AudienceRunRequest, BuildAudienceRequest, SetSendListRequest, UpdateSectionsRequest
import session_store
import agent
import audience_tools
from config import ANTHROPIC_API_KEY, HUBSPOT_PORTAL_ID, INTERNAL_API_TOKEN, ASANA_ACCESS_TOKEN, LITELLM_BASE_URL, LITELLM_API_KEY
import asana_tools
import json
import queue as _queue
import threading as _threading

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


# ── Live "brief" progress channel ────────────────────────────────────────────
# A tiny in-memory pub/sub keyed by a client-generated token. Backend steps push
# short human-readable lines; the frontend streams them over SSE so the user sees
# what the AI is doing in real time while the tab has already advanced.
_progress: dict[str, _queue.Queue] = {}

def _progress_channel(token: str) -> _queue.Queue:
    q = _progress.get(token)
    if q is None:
        q = _queue.Queue()
        _progress[token] = q
    return q

def progress_emit(token: str, text: str, **extra) -> None:
    """Push one brief line to a channel. No-op when token is falsy/unknown."""
    if not token:
        return
    try:
        _progress_channel(token).put({"type": "brief", "text": text, **extra})
    except Exception:
        pass


@app.get("/api/status")
async def status():
    return {"mode": MODE, "hubspot_configured": bool(HUBSPOT_PORTAL_ID)}


@app.get("/api/debug-email")
async def debug_email(email_id: str):
    """
    Dump the raw HubSpot widget + flexArea structure of any email by ID.
    Use this to inspect how a real sent email's footer/social icons are structured.
    """
    raw = hubspot_tools._get(f"/marketing/v3/emails/{email_id}")
    content = raw.get("content") or {}
    widgets = content.get("widgets") or {}
    flex    = content.get("flexAreas") or {}

    # Summarise section order with widget paths
    section_summary = []
    for area_name, area in flex.items():
        for sec in (area.get("sections") or []):
            for col in (sec.get("columns") or []):
                for wid_id in (col.get("widgets") or []):
                    w = widgets.get(wid_id) or {}
                    body = w.get("body") or {}
                    section_summary.append({
                        "widget_id":   wid_id,
                        "path":        body.get("path", ""),
                        "has_html":    bool(body.get("html")),
                        "has_social":  bool(body.get("social")),
                        "has_img":     bool(body.get("img")),
                        "line_type":   body.get("line_type", ""),
                        "social_data": body.get("social"),
                    })

    return {
        "email_id":        email_id,
        "name":            raw.get("name"),
        "type":            raw.get("type"),
        "state":           raw.get("state"),
        "template_path":   content.get("templatePath"),
        "flex_area_names": list(flex.keys()),
        "section_order":   section_summary,
        "raw_widgets":     widgets,
    }


@app.get("/api/debug-lookup")
async def debug_lookup(url: str):
    """
    Debug endpoint: paste an event URL and see exactly what the system scrapes,
    which brand it maps to, and which HubSpot emails it finds as candidates.
    """
    import re as _re

    result = {}

    # 1. Scrape
    try:
        url_data = content_tools.scrape_event_full(url)
    except Exception as e:
        url_data = {}
        result["scrape_error"] = str(e)

    raw_event = url_data.get("event_name", "")
    location  = url_data.get("location", "")
    result["scraped"] = {
        "event_name": raw_event,
        "brand_name": url_data.get("brand_name"),
        "location":   location,
        "hero_image": url_data.get("hero_image_url"),
    }

    # 2. Brand map lookup
    known = lookup_event_brand(raw_event)
    if known:
        result["brand_lookup"] = known
        brand_name       = known["brand_name"]
        short_brand_name = known["short_brand_name"]
        event_name       = known["event_name"]
    else:
        result["brand_lookup"] = None
        brand_name       = url_data.get("brand_name", "")
        short_brand_name = ""
        event_name       = raw_event

    # 3. HubSpot candidate fetch
    brand_event_list  = get_brand_events(short_brand_name) if short_brand_name else []
    event_short_names = list({e["event_short_name"] for e in brand_event_list})
    result["brand_events"] = event_short_names

    candidates = []
    if brand_name or short_brand_name:
        try:
            candidates = hubspot_tools.get_brand_emails(
                short_brand_name, brand_name,
                event_short_names=event_short_names,
                event_url=url,
            )
        except Exception as e:
            result["hubspot_error"] = str(e)

    # 4. Strict locale filter: event name location first, then scraped city/country/region.
    # e.g. "LF Energy Summit Europe" + "Berlin, Germany" → tries "europe/eu" before "berlin".
    # A locale mismatch (no hits at any level) means "no history for this location" —
    # it never falls back to an unfiltered, cross-country candidate pool.
    ai_pool, filter_level = filter_candidates_by_locale(candidates, event_name, location)
    filtered = ai_pool

    # 5. Keyword score — uses expanded location words so "NA" and "North America" both score
    _SCORE_STOP = {"the", "a", "an", "and", "or", "of", "in", "at", "for", "on", "to", "is",
                   "lf", "linux", "foundation", "events", "open", "source",
                   "conference", "summit", "day", "edition", "annual"}
    name_loc = extract_location_from_name(event_name)
    query_score_kw = (
        {w.lower() for w in _re.findall(r'\w+', event_name) if len(w) > 2 and w.lower() not in _SCORE_STOP}
        | expand_location_words(name_loc or location)
    )

    def _score(e):
        name_kw = {w.lower() for w in _re.findall(r'\w+', e.get("name") or "")}
        return len(query_score_kw & name_kw)

    scored = sorted(
        candidates,
        key=lambda e: (_score(e), e.get("publishDate") or ""),
        reverse=True,
    )

    result["score_keywords"]      = sorted(query_score_kw)
    result["filter_level_used"]   = filter_level
    result["candidates_total"]    = len(candidates)
    result["candidates_filtered"] = len(filtered)
    result["pool_size"]           = len(ai_pool)
    ai_pool_ids = {e.get("id") for e in ai_pool}
    result["candidates"] = [
        {
            "id":          e.get("id"),
            "name":        e.get("name"),
            "state":       e.get("state"),
            "publishDate": e.get("publishDate"),
            "score":       _score(e),
            "in_filtered_pool": e.get("id") in ai_pool_ids,
        }
        for e in scored
    ]

    # 5. Keyword fallback pick (what happens when AI selection fails)
    try:
        fallback = hubspot_tools.search_emails_for_event(
            short_brand_name or brand_name, event_name, location
        )
        result["keyword_fallback"] = json.loads(fallback) if isinstance(fallback, str) else fallback
    except Exception as e:
        result["keyword_fallback_error"] = str(e)

    return result


# ── Step 1 — Generate plan ───────────────────────────────────────────────────

def _create_plan_impl(req: PlanRequest, emit=lambda *a, **k: None):
    """
    Synchronous plan orchestration. `emit(text)` streams a live "brief" line so the
    UI can narrate backend AI activity in real time. Wrapped by POST /api/plan
    (blocking) and POST /api/plan-start (streamed via /api/progress/{token}).
    """
    import re as _re
    session = session_store.create()
    log.info(f"[PLAN] url={req.url!r} session={session.session_id[:8]}")

    # ── Step A: Full event scrape (event + registration page + images) ─────────
    emit("🔎 Reading the event page…")
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
    if raw_event:
        emit(f"📄 Event detected: {raw_event}" + (f" · {location}" if location else ""))

    emit("🏷️ Identifying brand…")
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
    candidates: list = []   # all fetched HubSpot email candidates — reused for content reference

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

            emit(f"📚 Searching HubSpot for past {brand_name or short_brand_name} campaigns…")
            candidates = hubspot_tools.get_brand_emails(
                short_brand_name, brand_name,
                event_short_names=event_short_names,
                event_url=req.url,
            )
            emit(f"📬 Found {len(candidates)} past campaign email(s) to learn from.")

            if candidates:
                # Strict locale filter: city → country → region, single most-specific
                # level with a hit wins. A mismatch (no hits anywhere) yields an empty
                # pool rather than falling back to other countries' editions — see
                # filter_candidates_by_locale() for the rationale.
                ai_pool, filter_level = filter_candidates_by_locale(candidates, event_name, location)

                log.info(f"[PLAN] AI select: {len(candidates)} total → location filter={filter_level!r} pool={len(ai_pool)}")

                emit(f"🤖 AI reviewing {len(ai_pool)} candidate(s) to pick the best source email…")
                selected = agent.ai_select_source_email(
                    event_name, event_short_name, location,
                    ai_pool, url=req.url,
                )
                if selected:
                    emit(f"✅ Source email selected: {selected.get('name','(unnamed)')}")
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
    emit("📅 Detecting campaign stage from the event timeline…")
    stage_info = detect_stage(url_data.get("event_dates", []))
    session.meta["stage_info"] = stage_info
    log.info(f"[PLAN] Stage: {stage_info['name']!r} ({stage_info['funnel']}, days={stage_info['days_to_event']})")
    emit(f"🎯 Stage: {stage_info.get('name','?')} ({stage_info.get('funnel','')})")

    # ── Deterministic email name (do NOT rely on Claude's prose + regex) ───────
    # Format: "<YY>Q<N> - <ShortBrand> - <EventName> - <Suffix>"
    def _build_email_name() -> str:
        yyq = ""
        for _ds in (url_data.get("event_dates") or []):
            _m = _re.match(r"(\d{4})-(\d{2})-(\d{2})", str(_ds))
            if _m:
                yyq = f"{int(_m.group(1)) % 100:02d}Q{(int(_m.group(2)) - 1) // 3 + 1}"
                break
        _code   = short_brand_name or brand_name or ""
        _suffix = email_type or stage_info.get("email_type", "") or "Invite"
        _parts  = [p for p in (_code, event_name, _suffix) if p]
        _body   = " - ".join(_parts)
        return f"{yyq} - {_body}" if (yyq and _body) else _body

    _det_name = _build_email_name()
    if _det_name:
        session.meta["email_name"] = _det_name
        log.info(f"[PLAN] email_name (deterministic): {_det_name!r}")

    # ── UTM campaign resolution — follow the matched source email to its
    # HubSpot Campaign and read its configured UTM value; fall back to a slug
    # of the deterministic email name when no campaign/UTM is found. ─────────
    emit("🔗 Resolving UTM campaign…")
    _source_email_id = (session.meta.get("brand_history") or {}).get("matched_email_id") \
        or (session.meta.get("brand_history") or {}).get("last_email_id")
    try:
        utm_params = hubspot_tools.resolve_utm_campaign(
            _source_email_id, session.meta.get("email_name", "")
        )
    except Exception as e:
        log.warning(f"[PLAN] resolve_utm_campaign failed: {e}")
        utm_params = {}
    session.meta["utm_params"] = utm_params
    log.info(f"[PLAN] UTM: {utm_params}")

    # ── Step B2: Find stage-specific content reference email ──────────────────
    # Look for the most recent sent email whose name contains the stage keyword
    # (e.g. "Last Chance" for a Last Chance stage). This email's actual HTML will
    # be used as the reference for AI content generation — NOT the generic template.
    #
    # Keyword map covers all 13 marketing-journey stage names from stage_detector.py.
    # Multiple keywords per stage so we match the varied naming in HubSpot
    # (e.g. "CFP Closes 14 July" matches "cfp"; "Registration Live" matches "registration").
    _STAGE_KW_MAP: dict = {
        "Event Announcement":               ["announcement", "invite", "announcing"],
        "CFP Launch":                       ["cfp", "call for proposals", "call for speakers", "speak"],
        "Registration Launch":              ["registration", "register", "cfp open", "registration live"],
        "Co-Located Events + CFP Reminder": ["cfp", "co-located", "colocated", "reminder"],
        "DEI & Travel Fund":                ["dei", "travel fund", "scholarship", "diversity"],
        "Schedule Announcement":            ["schedule", "keynote", "sessions", "agenda"],
        "Main Registration Push":           ["register", "reminder", "registration", "push"],
        "Final Countdown":                  ["last chance", "last call", "final", "countdown",
                                             "closing", "closes", "deadline"],
        "Event Week":                       ["reminder", "event week", "logistics", "venue", "join us"],
        "Thank You + Survey":               ["thank you", "thanks", "survey", "feedback", "post-event"],
        "Content & Recordings Release":     ["recording", "content", "recap", "slides", "session"],
        "Next Event CFP Teaser":            ["cfp", "upcoming", "next event", "teaser", "save the date"],
        "Community Nurture":                ["community", "newsletter", "update", "nurture"],
        # Legacy/alias names that might come through
        "Invite":                           ["invite"],
        "Last Chance":                      ["last chance", "last call", "closes", "deadline"],
        "Reminder":                         ["reminder"],
        "Save the Date":                    ["save the date", "save-the-date"],
    }
    _stage_keywords = _STAGE_KW_MAP.get(stage_info.get("name", ""), [])

    # Re-use `candidates` already fetched for AI selection — it now includes URL-slug results.
    _ref_candidates = candidates

    # Build a RANKED top-3 reference list (best first). The content generator reads
    # each one's actual body, picks the richest as the structural template, and learns
    # the house style/tone from all of them.
    #   1) stage-keyword matches (in candidate/recency order)
    #   2) then most-recent candidates (fill remaining slots)
    #   3) then the AI-selected clone source
    _ranked_refs: list = []   # list of (id, name), de-duplicated, max 3

    def _add_ref(_id, _name):
        _id = str(_id or "")
        if _id and _id not in {r[0] for r in _ranked_refs}:
            _ranked_refs.append((_id, _name or ""))

    if _stage_keywords and _ref_candidates:
        for _cand in _ref_candidates:
            _cname = (_cand.get("name") or "").lower()
            if any(_kw in _cname for _kw in _stage_keywords):
                _add_ref(_cand.get("id"), _cand.get("name"))
            if len(_ranked_refs) >= 3:
                break

    for _cand in _ref_candidates:      # fill remaining slots with most-recent candidates
        if len(_ranked_refs) >= 3:
            break
        _add_ref(_cand.get("id"), _cand.get("name"))

    _bh = session.meta.get("brand_history") or {}   # final fallback: AI-selected clone source
    _add_ref(_bh.get("matched_email_id"), _bh.get("matched_email_name"))

    _ranked_refs = _ranked_refs[:3]
    if _ranked_refs:
        session.meta["content_reference_ids"]  = [r[0] for r in _ranked_refs]
        session.meta["content_reference_id"]   = _ranked_refs[0][0]   # primary (compat)
        session.meta["content_reference_name"] = _ranked_refs[0][1]
        log.info(f"[PLAN] top-{len(_ranked_refs)} content references: "
                 + "; ".join(f"{n!r}({i})" for i, n in _ranked_refs))

    # Content generation happens separately via /api/generate-content
    # (keeps /api/plan fast; frontend calls it automatically after plan loads)

    # ── Stage & Content context hint ─────────────────────────────────────────
    # Build the data block that Claude will use to write the Stage & Content
    # Overview section at the top of the plan.
    _speakers = url_data.get("speakers", [])
    _sponsors  = url_data.get("sponsors", [])
    _topics    = url_data.get("topics", [])
    _ref_name  = session.meta.get("content_reference_name", "")
    _days      = stage_info.get("days_to_event")
    _days_str  = f"{_days} days" if _days is not None else "unknown"

    def _fmt_list(items, label, empty_msg):
        if not items:
            return f"{label}: {empty_msg}"
        def _to_str(x):
            return x.get("name", "") if isinstance(x, dict) else str(x)
        return f"{label} ({len(items)}): " + ", ".join(_to_str(x) for x in items)


    _stage_num  = stage_info.get("stage_number")
    _stage_num_str = f"Stage {_stage_num} — " if _stage_num else ""
    _strategy   = stage_info.get("marketing_strategy", "")
    _ideas      = stage_info.get("content_ideas", [])
    _timeline   = stage_info.get("timeline", "")
    _ideas_str  = "\n".join(f"    • {idea}" for idea in _ideas) if _ideas else "    (none)"

    stage_content_hint = (
        f"STAGE & CONTENT DATA — include this verbatim in the Stage & Content Overview section:\n"
        f"\n"
        f"  ── Current Stage ──\n"
        f"  Stage           : {_stage_num_str}{stage_info['name']} ({stage_info.get('funnel','')})\n"
        f"  Timeline        : {_timeline}\n"
        f"  Days to Event   : {_days_str}\n"
        f"  Event Date      : {stage_info.get('event_date_str','')}\n"
        f"  Stage Goal      : {stage_info.get('goal','')}\n"
        f"  Email Type      : {stage_info.get('email_type','')}\n"
        f"  CTA             : {stage_info.get('cta_label','Register Now')}\n"
        f"\n"
        f"  ── Marketing Strategy ──\n"
        f"  {_strategy}\n"
        f"\n"
        f"  ── Content Ideas for This Stage ──\n"
        f"{_ideas_str}\n"
        f"\n"
        f"  ── Event Data ──\n"
        f"  {_fmt_list(_speakers, 'Speakers', 'None found on event page — will say TBA')}\n"
        f"  {_fmt_list(_sponsors, 'Sponsors', 'None found on event page')}\n"
        f"  {_fmt_list(_topics[:4], 'Topics', 'Open Source, Cloud Native, Linux')}\n"
        f"\n"
        f"  ── Content Plan ──\n"
        f"  Design & components: mirror the previously sent email ({_ref_name or 'stage template fallback'})\n"
        f"  Copy & messaging   : use the marketing strategy and content ideas above as inspiration\n"
        f"  Content sections   : intro, {stage_info.get('email_type','')} highlights, "
        f"speakers showcase, {'sponsors mention, ' if _sponsors else ''}"
        f"registration CTA, closing\n"
    )

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
    emit("📝 Drafting the campaign plan…")
    try:
        text, messages = agent.plan_turn(session, req.url)
    except Exception as exc:
        log.error(f"[PLAN] failed: {exc}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc))

    session.messages = messages
    session.phase = "planning"
    session.plan = {"url": req.url}

    # Fallback ONLY: if the deterministic name couldn't be built above, try to parse
    # a backtick-formatted name from Claude's plan text (`26Q2 - Brand - Event - Suffix`).
    if not session.meta.get("email_name"):
        name_match = _re.search(r"`(2\dQ\d[^`]+)`", text)
        if name_match:
            session.meta["email_name"] = name_match.group(1).strip()
            log.info(f"[PLAN] email_name parsed from plan text: {session.meta['email_name']!r}")

    session_store.update(session)

    # Surface the source/reference email so the frontend can show it before the user approves
    source_email = None
    if session.meta.get("brand_history"):
        bh = session.meta["brand_history"]
        eid  = bh.get("matched_email_id") or bh.get("last_email_id")
        ename = bh.get("matched_email_name") or bh.get("last_email_name", "")
        if eid:
            source_email = {"id": eid, "name": ename}

    emit("✅ Campaign plan ready.")
    return {
        "session_id":   session.session_id,
        "message":      text,
        "phase":        session.phase,
        "mode":         MODE,
        "source_email": source_email,
        "stage":        stage_info,
        "utm":          session.meta.get("utm_params", {}),
    }


# ── Plan endpoint (blocking) + streaming variant ─────────────────────────────

@app.post("/api/plan")
async def create_plan(req: PlanRequest):
    """Blocking plan — runs the orchestration in a worker thread and returns the result."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _create_plan_impl(req))


@app.post("/api/plan-start")
async def start_plan_brief(req: PlanRequest):
    """
    Non-blocking plan — runs the orchestration in a background thread, emitting a live
    brief to /api/progress/{token}. The final result arrives as a {type:'plan_done'}
    event on the same channel. Returns the token immediately.
    """
    token = req.progress_token or json.dumps(id(req))  # client normally supplies one
    _progress_channel(token)  # ensure the channel exists before work starts

    def worker():
        emit = lambda text, **ex: progress_emit(token, text, **ex)
        try:
            result = _create_plan_impl(req, emit)
            _progress_channel(token).put({"type": "plan_done", "result": result})
        except HTTPException as he:
            _progress_channel(token).put({"type": "error", "text": str(he.detail)})
        except Exception as exc:
            log.error(f"[PLAN-START] failed: {exc}\n{traceback.format_exc()}")
            _progress_channel(token).put({"type": "error", "text": str(exc)})

    _threading.Thread(target=worker, daemon=True).start()
    return {"token": token}


@app.get("/api/progress/{token}")
async def progress_stream(token: str):
    """SSE stream of brief lines for a token. Stays open across the plan and content
    phases; the client closes it when the tab's work is done."""
    from fastapi.responses import StreamingResponse

    q = _progress_channel(token)

    async def gen():
        loop = asyncio.get_running_loop()
        idle = 0
        try:
            while True:
                try:
                    item = await loop.run_in_executor(None, lambda: q.get(timeout=5))
                except Exception:
                    idle += 1
                    if idle > 120:          # ~10 min with no activity → give up
                        break
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                    continue
                idle = 0
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            _progress.pop(token, None)

    return StreamingResponse(gen(), media_type="text/event-stream")


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

    token = req.progress_token or ""
    log.info(f"[GEN-CONTENT] session={session_id[:8]}")
    try:
        url_data      = session.meta.get("url_data", {})
        stage_info    = session.meta.get("stage_info", {})
        brand_history = session.meta.get("brand_history")

        change_request  = req.change_request or ""
        source_email_id = session.meta.get("content_reference_id", "")
        reference_ids   = session.meta.get("content_reference_ids") or ([source_email_id] if source_email_id else [])

        log.info(f"[GEN-CONTENT] refs={reference_ids} "
                 f"primary_name={session.meta.get('content_reference_name', '')!r}")

        progress_emit(token, "✍️ Drafting subject, preview text & email body…"
                      if not change_request else f"✍️ Revising content: {change_request[:80]}")

        loop = asyncio.get_running_loop()
        generated = await loop.run_in_executor(
            None,
            lambda: agent.generate_email_content(
                url_data, stage_info, brand_history,
                change_request=change_request,
                source_email_id=source_email_id,
                reference_ids=reference_ids,
            )
        )

        session.meta["generated_subject"] = generated["subject"]
        session.meta["generated_preview"]  = generated["preview_text"]
        session.meta["generated_html"]     = generated["html"]       # full preview HTML (UI)
        session.meta["body_html"]          = generated.get("body_html", generated["html"])
        session.meta["banner_url"]         = generated.get("banner_url", "")
        session.meta["sections"]           = generated.get("sections", [])
        session.meta["sponsors"]           = generated.get("sponsors", [])

        # Variant A (AI Template) — generated from the same detected funnel stage,
        # previewed alongside Variant B (the existing flow, above) so the user can
        # compare before Implementation creates both as a real HubSpot A/B test.
        progress_emit(token, "🤖 Drafting AI template variant…")
        variant_a = await loop.run_in_executor(
            None,
            lambda: agent.generate_ai_template_content(
                url_data, stage_info,
                banner_url=generated.get("banner_url", ""),
                sponsors=generated.get("sponsors", []),
            )
        )
        session.meta["variant_a_subject"]      = variant_a.get("subject", "")
        session.meta["variant_a_preview"]      = variant_a.get("preview_text", "")
        session.meta["variant_a_html"]          = variant_a.get("html", "")
        session.meta["variant_a_body_html"]     = variant_a.get("body_html", "")
        session.meta["variant_a_sections"]      = variant_a.get("sections", [])
        session.meta["variant_a_banner_url"]    = variant_a.get("banner_url", "")
        session.meta["variant_a_template_key"]  = variant_a.get("template_key", "")
        session.meta["variant_a_mode"]          = variant_a.get("mode", "")
        session_store.update(session)

        log.info(f"[GEN-CONTENT] done: subject={generated['subject']!r} "
                 f"html_len={len(generated['html'])} banner={'yes' if generated.get('banner_url') else 'no'} "
                 f"variant_a_mode={variant_a.get('mode')!r}")
        sections = generated.get("sections", []) or []
        progress_emit(token, f"📧 Email drafted — {len(sections)} content section(s).", done=True)
        return {
            "session_id":        session_id,
            "generated_subject": generated["subject"],
            "generated_preview": generated["preview_text"],
            "generated_html":    generated["html"],
            "sections":          sections,
            "banner_url":        generated.get("banner_url", ""),
            "variant_a_subject":     variant_a.get("subject", ""),
            "variant_a_preview":     variant_a.get("preview_text", ""),
            "variant_a_html":        variant_a.get("html", ""),
            "variant_a_template_key": variant_a.get("template_key", ""),
            "variant_a_mode":        variant_a.get("mode", ""),
        }
    except Exception as exc:
        log.error(f"[GEN-CONTENT] failed: {exc}\n{traceback.format_exc()}")
        progress_emit(token, f"⚠️ Content drafting failed: {exc}", error=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Step 1c — Update content sections (user removed/reordered blocks) ─────────

@app.post("/api/update-sections")
async def update_sections(req: UpdateSectionsRequest):
    """
    Persist an edited (trimmed/reordered) sections array and rebuild the preview +
    body HTML so the clone uses exactly what the user kept. Returns the new preview HTML.
    """
    session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    sections = req.sections or []
    url_data = session.meta.get("url_data", {})
    sponsors = session.meta.get("sponsors", []) or []

    try:
        body_html = agent._sections_to_html(sections, sponsors=sponsors)
        preview_html = agent._build_email_preview(
            session.meta.get("banner_url", ""),
            body_html,
            url_data.get("url", ""),
            url_data.get("event_name", ""),
        )
    except Exception as exc:
        log.error(f"[UPDATE-SECTIONS] rebuild failed: {exc}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc))

    session.meta["sections"]       = sections
    session.meta["body_html"]      = body_html
    session.meta["generated_html"] = preview_html
    session_store.update(session)
    log.info(f"[UPDATE-SECTIONS] session={req.session_id[:8]} sections={len(sections)}")

    return {"session_id": req.session_id, "generated_html": preview_html, "sections_count": len(sections)}


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

    content_applied   = session.meta.get("content_applied", False)
    validation_passed = session.meta.get("validation_passed", False)
    validation_issues = session.meta.get("validation_issues", [])

    # variant_a_email_id == real_email_id (the master clone from Step 1 of clone_turn).
    # variant_b_email_id is the separate A/B variation email created inside clone_turn;
    # it's empty if create_ab_variation failed, in which case Variant B content was
    # applied to the master itself as a fallback (see agent.clone_turn).
    variant_a_email_id  = session.meta.get("variant_a_email_id", real_email_id)
    variant_a_draft_url = session.meta.get("variant_a_draft_url", "")
    variant_b_email_id  = session.meta.get("variant_b_email_id", "")
    variant_b_draft_url = session.meta.get("variant_b_draft_url", "")

    session.phase     = "complete" if validation_passed else "cloned"
    session.email_id  = real_email_id
    session.draft_url = f"https://app.hubspot.com/email/{HUBSPOT_PORTAL_ID}/edit/{real_email_id}/settings"
    session_store.update(session)
    log.info(
        f"[CLONE] verified email_id={real_email_id} "
        f"content_applied={content_applied} validation_passed={validation_passed} "
        f"issues={validation_issues} variant_a={variant_a_email_id} variant_b={variant_b_email_id}"
    )

    return {
        "session_id":        req.session_id,
        "message":           text,
        "phase":             session.phase,
        "email_id":          session.email_id,
        "draft_url":         session.draft_url,   # always returned so frontend can show it
        "content_applied":   content_applied,
        "validation_passed": validation_passed,
        "validation_issues": validation_issues,
        "variant_a_email_id":  variant_a_email_id,
        "variant_a_draft_url": variant_a_draft_url or session.draft_url,
        "variant_b_email_id":  variant_b_email_id,
        "variant_b_draft_url": variant_b_draft_url,
    }


# ── Step 2b — Apply send list (explicit, after approve) ──────────────────────

@app.post("/api/set-send-list")
async def set_send_list(req: SetSendListRequest):
    """
    Apply ONLY the send-to (and suppression) lists to an already-cloned email.

    Called explicitly by the frontend right after /clone returns, so the list
    assignment is a separate, visible, verifiable step. Resolves email_id and
    suppression from the session when not passed directly.
    Returns the actual `to` object HubSpot stored so the UI can confirm/warn.
    """
    send_list_id = (req.send_list_id or "").strip()
    if not send_list_id:
        raise HTTPException(status_code=400, detail="send_list_id is required")

    email_id    = (req.email_id or "").strip()
    suppression = list(req.suppression_list_ids or [])

    sess = session_store.get(req.session_id) if req.session_id else None
    if sess:
        email_id = email_id or (sess.email_id or "")
        if not suppression:
            suppression = (sess.meta.get("brand_history") or {}).get("suppression_list_ids", []) or []

    if not email_id:
        raise HTTPException(
            status_code=400,
            detail="No email to update. Provide email_id, or a session_id whose email has been cloned.",
        )

    log.info(f"[SET-SEND-LIST] email={email_id} list={send_list_id} suppression={suppression}")
    try:
        result = hubspot_tools.set_email_send_list(email_id, send_list_id, suppression)
    except Exception as exc:
        log.error(f"[SET-SEND-LIST] failed: {exc}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to apply send list: {exc}")

    applied = result.get("success", False)
    log.info(f"[SET-SEND-LIST] email={email_id} list={send_list_id} success={applied} type={result.get('list_type')}")

    # Persist on the session so later steps know which list is the send list
    if sess:
        sess.meta["audience_list_id"] = send_list_id
        session_store.update(sess)

    if not applied:
        # Surface the failure instead of silently leaving send-to empty
        raise HTTPException(
            status_code=502,
            detail=(
                f"HubSpot did not accept send list {send_list_id} for email {email_id}. "
                f"Applied `to`: {result.get('to')}"
            ),
        )

    return {
        "email_id":     email_id,
        "send_list_id": send_list_id,
        "list_type":    result.get("list_type"),
        "success":      applied,
        "to":           result.get("to"),
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
    # Allow content customization both right after clone ('cloned') and after the
    # AI body was auto-applied during clone ('complete') — the customize step on the
    # email-only path lets the user replace/add/remove body copy in either case.
    if session.phase not in ("cloned", "complete"):
        raise HTTPException(status_code=400, detail=f"Expected phase 'cloned' or 'complete', got '{session.phase}'")

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

        # ── UTM resolution — follow the clone source email to its HubSpot
        # Campaign; fall back to a slug of the email name. ─────────────────────
        try:
            utm_params = hubspot_tools.resolve_utm_campaign(req.clone_base_id, req.email_name)
        except Exception as e:
            log.warning(f"[BRIEF] resolve_utm_campaign failed: {e}")
            utm_params = {}
        log.info(f"[BRIEF] UTM: {utm_params}")

        # ── Step 3: Content ──────────────────────────────────────────────────
        content_applied = False
        content_source  = "none"
        final_subject   = req.subject
        final_preview   = req.preview_text

        if req.raw_html:
            # Doc HTML provided — inject directly (no AI generation)
            hubspot_tools.update_email_content(new_email_id, req.raw_html, utm_params=utm_params)
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
            _gen_sections = generated.get("sections") or []
            hubspot_tools.update_email_content(
                new_email_id,
                html_content=generated.get("body_html", "") if not _gen_sections else "",
                banner_url=generated.get("banner_url", ""),
                event_url=req.event_url,
                content_sections=_gen_sections or None,
                sponsors=generated.get("sponsors") or None,
                utm_params=utm_params,
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

@app.post("/api/audience-plan")
async def start_audience_plan(req: AudiencePlanRequest):
    """
    Phase 1 — start segment planning job.
    Scrapes event page, analyses historical HubSpot data, and produces a Segment Plan.
    Returns job_id — poll /api/audience-stream/{job_id} for SSE output.
    """
    session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    event_url = (req.event_url or "").strip()
    cached = session.meta.get("url_data") or {}
    if not event_url:
        event_url = cached.get("url", "")
    if not event_url:
        raise HTTPException(status_code=400, detail="No event URL — provide event_url or run plan first")

    # Reuse the scrape done during the Email Content stage if it's for this same URL.
    prescraped = cached if cached.get("url") == event_url else None
    job_id = audience_tools.start_plan_job(event_url, prescraped=prescraped)
    log.info(f"[AUDIENCE-PLAN] job started: {job_id[:8]} url={event_url!r} reuse_scrape={bool(prescraped)}")
    return {"job_id": job_id, "event_url": event_url}


@app.post("/api/build-audience")
async def start_build_audience(req: BuildAudienceRequest):
    """
    Phase 2 — start list building job.
    Builds HubSpot DYNAMIC lists using the Segment Plan from Phase 1.
    Returns job_id — poll /api/audience-stream/{job_id} for SSE output.
    """
    session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    event_url = (req.event_url or "").strip()
    cached = session.meta.get("url_data") or {}
    if not event_url:
        event_url = cached.get("url", "")
    if not event_url:
        raise HTTPException(status_code=400, detail="No event URL — provide event_url or run plan first")

    # Reuse the scrape done during the Email Content stage if it's for this same URL;
    # otherwise the planning phase scrapes it fresh.
    prescraped = cached if cached.get("url") == event_url else None
    job_id = audience_tools.start_build_job(event_url, plan=req.plan, qa=req.qa, prescraped=prescraped)
    log.info(f"[AUDIENCE-BUILD] job started: {job_id[:8]} url={event_url!r} reuse_scrape={bool(prescraped)}")
    return {"job_id": job_id, "event_url": event_url}


@app.post("/api/audience/plan")
async def start_audience_plan_standalone(req: AudienceRunRequest):
    """
    Standalone Phase 1 — plan-only, no email session required.
    Scrapes the event page and produces a Segment Plan; creates no HubSpot lists.
    Stream output via GET /api/audience-stream/{job_id}, then call /api/audience/run
    with the reviewed plan text to actually build the lists.
    """
    event_url = req.event_url.strip()
    if not event_url:
        raise HTTPException(status_code=400, detail="event_url is required")

    job_id = audience_tools.start_plan_job(event_url)
    log.info(f"[AUDIENCE-PLAN] standalone job {job_id[:8]} url={event_url!r}")
    return {"job_id": job_id, "event_url": event_url}


@app.post("/api/audience/run")
async def run_audience_standalone(req: AudienceRunRequest):
    """
    Standalone audience build — no active email session required.
    Runs the full two-phase flow (planning → building) when plan is empty,
    or Phase 2 only when plan text is supplied.
    Stream output via GET /api/audience-stream/{job_id}.
    """
    event_url = req.event_url.strip()
    if not event_url:
        raise HTTPException(status_code=400, detail="event_url is required")

    job_id = audience_tools.start_build_job(event_url, plan=req.plan, qa=req.qa)
    log.info(f"[AUDIENCE-RUN] standalone job {job_id[:8]} url={event_url!r} plan={'yes' if req.plan else 'no'}")
    return {"job_id": job_id, "event_url": event_url}


@app.get("/api/audience/status")
async def audience_status():
    """Return current audience builder config so the UI can show mode details."""
    from config import LITELLM_BASE_URL, LITELLM_API_KEY
    has_litellm = bool(LITELLM_BASE_URL and LITELLM_API_KEY)
    return {
        "mode": "litellm" if has_litellm else "cli",
        "litellm_base_url": LITELLM_BASE_URL or None,
        "litellm_key_set": bool(LITELLM_API_KEY),
        "hubspot_token_set": bool(audience_tools.HUBSPOT_ACCESS_TOKEN),
    }


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
        loop = asyncio.get_running_loop()  # get_event_loop() is deprecated; get_running_loop() is correct inside a coroutine
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
                try:
                    all_text          = "\n".join(accumulated)
                    # Prefer the ID captured straight from the hubspot_create_list tool
                    # result (ground truth); only fall back to scraping the model's
                    # narration text if that tracking somehow came up empty.
                    master_id         = str(item.get("master_list_id") or "").strip()
                    if not master_id:
                        master_id = audience_tools.extract_master_list_id(all_text)
                        if master_id:
                            log.warning(
                                f"[AUDIENCE] master_list_id missing from tool tracking — "
                                f"fell back to text extraction, got {master_id!r}"
                            )
                    suppression_lists = audience_tools.extract_suppression_lists(all_text)
                    posthoc_applied   = False

                    if session_id and master_id:
                        sess = session_store.get(session_id)
                        if sess:
                            sess.meta["audience_list_id"] = master_id
                            if suppression_lists:
                                sess.meta["suppression_lists"] = suppression_lists
                            session_store.update(sess)
                            log.info(f"[AUDIENCE] master list {master_id} stored in session {session_id[:8]}")

                            # Email was already cloned before build finished — apply send list now
                            if sess.email_id:
                                try:
                                    suppression_ids = (sess.meta.get("brand_history") or {}).get("suppression_list_ids", [])
                                    sls = hubspot_tools.set_email_send_list(sess.email_id, master_id, suppression_ids)
                                    posthoc_applied = sls.get("success", False)
                                    log.info(f"[AUDIENCE] post-hoc send list: email={sess.email_id} list={master_id} success={posthoc_applied}")
                                except Exception as exc:
                                    log.warning(f"[AUDIENCE] post-hoc send list failed: {exc}")

                    log.info(f"[AUDIENCE] build complete — master_id={master_id!r} posthoc_applied={posthoc_applied} suppressions={len(suppression_lists)}")
                    yield f"data: {json.dumps({'type':'complete','done':True,'master_list_id':master_id,'suppression_lists':suppression_lists,'posthoc_applied':posthoc_applied,'success':item.get('success',False)})}\n\n"
                except Exception as exc:
                    log.error(f"[AUDIENCE] completion handling error: {exc}")
                    yield f"data: {json.dumps({'type':'complete','done':True,'master_list_id':'','suppression_lists':[],'posthoc_applied':False,'success':False})}\n\n"
                finally:
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
