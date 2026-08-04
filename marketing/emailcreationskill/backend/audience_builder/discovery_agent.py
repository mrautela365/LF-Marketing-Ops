"""
Audience Builder — existing-list discovery agent.

Given an event URL, finds HubSpot lists that ALREADY EXIST for that event and
classifies them into 6 signals (Project Opt-In, LF Newsletter Opt-In, Event
Registration, Education Enrollment, Page View, Event Speakers). Read-only — never
creates or modifies a HubSpot list (see discovery_tools.py's restricted tool set).

Structurally mirrors audience_tools.py's job/queue/SSE architecture
(_run_agent / start_plan_job / get_job_queue / remove_job), but keeps its own
_jobs store rather than sharing audience_tools._jobs, so this feature stays
decoupled from the list-building flow it does not touch.
"""
import json
import logging
import queue
import threading
import uuid

import llm_gateway
from audience_builder.discovery_tools import TOOL_DEFS_OPENAI, TOOL_HANDLERS

log = logging.getLogger("audience-builder-discovery")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    log.addHandler(_h)
    log.propagate = False

_jobs: dict[str, queue.Queue] = {}

ALL_SIGNALS = [
    "project_opt_in",
    "lf_newsletter_opt_in",
    "event_registration",
    "education_enrollment",
    "page_view",
    "event_speakers",
]

DISCOVERY_TOOLS = llm_gateway.openai_tools_to_anthropic(TOOL_DEFS_OPENAI)

DISCOVERY_SYSTEM = (
    "You are an LF audience-discovery agent operating in READ-ONLY DISCOVERY MODE. "
    "Your only job is to find HubSpot lists that ALREADY EXIST for a given event and "
    "classify them into signal buckets. You have no tool that can create or modify a "
    "HubSpot list — do not attempt to. Do NOT ask for confirmation and do NOT enter "
    "plan mode. Narrate each step, then call present_discovered_lists exactly once at the end."
)

DISCOVERY_PROMPT_TEMPLATE = """\
Find every EXISTING HubSpot list already associated with this event — do not create
or modify anything, this is a read-only audit.

Event URL: {url}

STEP 1 — Identify the event
Call web_fetch on the event URL. Extract the exact event name, its brand/foundation
(e.g. PyTorch Foundation, CNCF, OpenSearch Software Foundation, The Linux Foundation),
and its location/edition (city/country, or region if it's a regional edition).

STEP 2 — Search for candidate lists
Call hubspot_search_lists using the FULL exact event name you extracted in STEP 1,
verbatim — including every brand/foundation joiner it contains (e.g. "KubeCon +
CloudNativeCon North America", never shortened to just "KubeCon" or "KubeCon NA").
This is NOT optional: hubspot_search_lists caps results at 20 with no recency
ordering, and a bare brand acronym like "KubeCon" matches hundreds of lists spanning
every year and every region (NA, EU, China, India, Japan) since this brand started —
those 20 slots fill up entirely with old/unrelated-region noise and the current
edition's own master lists never appear. The full series name is specific enough to
stay within the 20-result cap while still surfacing the whole family across quarters.
Then run a second search adding the edition year to the full series name (e.g.
"KubeCon + CloudNativeCon North America 2026") — master-list names usually embed the
year, and this catches current-edition lists that might rank below other results on
the first, year-less query. Only fall back to a narrower query (e.g. adding the brand
short name) if both of those come back with too few or clearly unrelated results.
Also call hubspot_search_campaigns with the same event name to find prior email
campaigns whose audience lists are worth inspecting via hubspot_get_list.

STEP 3 — Inspect and classify each candidate
For every candidate list whose name plausibly references this event or its brand,
call hubspot_get_list(list_id) to read its filterBranch, then classify it into
EXACTLY ONE of these 6 signals using both the name and the actual filter shape
(never classify by name alone if the filterBranch contradicts it):

Master/rollup lists are common here — a candidate's filterBranch may contain ONLY
IN_LIST/NOT_IN_LIST filters pointing at other lists, with no PROPERTY/UNIFIED_EVENTS/
PAGE_VIEW filter of its own. If so, resolve ONE level deep only: call hubspot_get_list
on the referenced list ID(s) to see their real filter shape, then classify the
ORIGINAL candidate from what you find at that one hop. Do NOT recurse a second level
deep (e.g. into lists referenced BY those referenced lists) even if some of them are
themselves rollups — you have a strict tool-call budget for this whole task, and going
two-plus hops deep on every rollup will exhaust it before you ever call
present_discovered_lists, silently producing an empty result. If a one-hop peek still
leaves the signal ambiguous, classify from the name and the one-hop evidence you do
have, or place it in `uncertain` with a reason — never spend a second hop chasing it.

1. project_opt_in — a PROPERTY filter on an email-subscription-type property tied
   to the EVENT'S OWN project/foundation newsletter (e.g. "PyTorch", "CNCF",
   "OpenSearch" subscription type) — NOT the generic Linux Foundation newsletter.
   Names often contain "Opt-In" or "Subscribed" plus the project name.
2. lf_newsletter_opt_in — same filter shape as above, but tied specifically to the
   "Linux Foundation Newsletter" subscription type. Keep this DISTINCT from
   project_opt_in even if the list name doesn't say so explicitly — check the
   filter's actual subscription-type value.
3. event_registration — LIST_MEMBERSHIP/IN_LIST or UNIFIED_EVENTS filter
   representing all-time registration for this event (e.g. "All Event
   Registrations", "All Registrants"). Includes past-edition registrant lists
   used for regional-expansion targeting.
4. education_enrollment — LIST_MEMBERSHIP/IN_LIST or UNIFIED_EVENTS filter
   (fixed eventTypeId "6-58204655") representing enrollment in "Education
   Enrolled" / "LFX Education" courses, scoped to this event's own brand/
   foundation (e.g. via a CONTAINS filter on a course/topic property, or a
   list name naming the specific brand). If the list's filter or name shows
   it covers ALL LFX Education courses with no brand/topic scoping, treat it
   as uncertain instead — note the missing brand scoping in its reason.
5. page_view — a PAGE_VIEW filterType (operator like GTE 0/1) on this event's page,
   or a project-specific page-view segment. May be named "Page Views" or similar.
6. event_speakers — a list scoped to this event's SPEAKERS specifically, not all
   registrants. Look for a name containing "Speaker(s)" (e.g. "[Event] Speakers",
   "[Event] Speaker List"), or a PROPERTY filter on hosted_events whose value ends
   in " - Speakers" for this event. Do not classify a general registration/attendee
   list here just because speakers are technically included in it — this signal is
   only for lists that are speaker-specific.

   Also determine which SCOPE this speaker list actually covers, and set it on the
   `scope` field ("current" | "past" | "current_past"):
   - If the list's name ends in " - Current" (the new naming convention, e.g.
     "[Event] Speakers - Current"), scope is "current". Ends in " - Past" → "past".
     Ends in " - Current + Past" → "current_past".
   - If the name doesn't carry one of those suffixes (an older list predating this
     convention), infer from the filterBranch's event_name values instead: compare
     each value's edition/year against this event's own current/upcoming edition
     (identified in STEP 1). If every value is this event's current edition (and
     any of its co-located tracks), scope is "current". If every value is a PRIOR
     edition/year only (never the current one), scope is "past". If it has a mix
     of the current edition and at least one prior edition, scope is "current_past".
   - If you truly cannot tell (e.g. no inspectable filter and no suffix), default
     to "current_past" rather than guessing narrower — this is the safest default
     since it means the list will be treated as covering both.

Anything that clearly references this event but doesn't confidently fit one of the
6 above goes in the `uncertain` bucket with a short `reason` explaining why (e.g.
"suppression list, not an inclusion signal" or "ambiguous filter, could not
determine subscription type").

Do NOT include unrelated lists for other events/brands — if hubspot_search_lists
returns noise, filter it out rather than guessing.
{qa_section}
STEP 4 — Present results
Call present_discovered_lists ONCE with the full `lists` (6-signal matches) and
`uncertain` arrays, plus the `brand_short` and `event_name` you identified in STEP 1
as top-level fields (these are reused to look up suppression lists and prior sends
for this event — always include them, even if a signal list came back empty). Do
not call it more than once, and do not create or update any HubSpot list at any
point in this task. For every list you inspected with hubspot_get_list, copy its
real `processingType` value verbatim into that list's `list_type` field — do not
invent or guess a value for lists you didn't inspect. For every list classified as
`event_speakers`, also set its `scope` field per STEP 3 rule 6 — omit `scope`
entirely for all other signals, it has no meaning for them.
"""


def build_discovery_prompt(event_url: str, qa: str = "") -> str:
    qa_section = f"\nUser answers to clarifying questions:\n{qa}\n" if qa else ""
    return DISCOVERY_PROMPT_TEMPLATE.format(url=event_url, qa_section=qa_section)


def _normalize_list_items(items: list) -> list:
    """The model sometimes emits HubSpot's own camelCase keys (listId, notes)
    instead of the schema's list_id/reason — normalize so downstream code (and
    the frontend) always sees list_id/reason."""
    normalized = []
    for item in items or []:
        item = dict(item)
        if "list_id" not in item and "listId" in item:
            item["list_id"] = item.pop("listId")
        if "reason" not in item and "notes" in item:
            item["reason"] = item.pop("notes")
        if "list_type" not in item and "listType" in item:
            item["list_type"] = item.pop("listType")
        if "list_type" not in item and "processingType" in item:
            item["list_type"] = item.pop("processingType")
        normalized.append(item)
    return normalized


def _compute_missing_signals(lists: list) -> list:
    """Which of the qualifying signals had zero matched lists — surfaced in the
    UI as a separate 'create this list' panel rather than left implicit."""
    found = {item.get("signal") for item in (lists or [])}
    return [s for s in ALL_SIGNALS if s not in found]


def _discovery_execute(name: str, tool_input: dict) -> str:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return json.dumps(handler(tool_input), default=str)
    except Exception as exc:
        log.warning(f"[DISCOVERY] tool {name} failed: {exc}")
        return json.dumps({"error": str(exc)})


def _run_discovery_agent(prompt: str, q: queue.Queue) -> None:
    log.info(f"[DISCOVERY] starting — backend={llm_gateway.backend_name()!r} prompt_len={len(prompt)}")
    q.put({"type": "output", "text": f"🔍 Starting discovery (backend={llm_gateway.backend_name()})…"})

    discovered: dict = {"lists": [], "uncertain": [], "brand_short": "", "event_name": ""}

    def _execute_and_track(name: str, tool_input: dict) -> str:
        result_json = _discovery_execute(name, tool_input)
        if name == "present_discovered_lists":
            discovered["lists"] = _normalize_list_items(tool_input.get("lists"))
            discovered["uncertain"] = _normalize_list_items(tool_input.get("uncertain"))
            discovered["brand_short"] = tool_input.get("brand_short", "")
            discovered["event_name"] = tool_input.get("event_name", "")
        return result_json

    def _on_event(ev: dict) -> None:
        etype = ev.get("type")
        if etype == "output":
            for line in (ev.get("text") or "").splitlines():
                if line.strip():
                    q.put({"type": "output", "text": line})
        elif etype == "output_delta":
            text = ev.get("text") or ""
            if text:
                q.put({"type": "output", "text": text, "delta": True})
        elif etype == "tool":
            name = ev.get("name")
            if name == "present_discovered_lists":
                inp = ev.get("input") or {}
                lists = _normalize_list_items(inp.get("lists"))
                uncertain = _normalize_list_items(inp.get("uncertain"))
                missing_signals = _compute_missing_signals(lists)
                brand_short = inp.get("brand_short", "")
                event_name = inp.get("event_name", "")
                q.put({"type": "output", "text": f"✅ {len(lists)} list(s) discovered, {len(uncertain)} uncertain"})
                q.put({
                    "type": "discovered", "lists": lists, "uncertain": uncertain,
                    "missing_signals": missing_signals,
                    "brand_short": brand_short, "event_name": event_name,
                })
            elif name == "snowflake_query":
                q.put({"type": "output", "text": f"🔧 {name}:\n{ev.get('input', {}).get('sql', '')}"})
            else:
                q.put({"type": "output", "text": f"🔧 {name}({json.dumps(ev.get('input', {}))[:100]})"})
        elif etype == "tool_result":
            q.put({"type": "output", "text": f"   ↳ {str(ev.get('text', ''))[:200]}"})

    try:
        llm_gateway.run_agent(
            [{"role": "user", "content": prompt}],
            system=DISCOVERY_SYSTEM,
            tools=DISCOVERY_TOOLS,
            execute_tool=_execute_and_track,
            max_tokens=16000,
            max_steps=40,
            on_event=_on_event,
        )
        log.info(f"[DISCOVERY] done — {len(discovered['lists'])} lists, {len(discovered['uncertain'])} uncertain")
        q.put({"type": "done", "done": True, "success": True,
               "lists": discovered["lists"], "uncertain": discovered["uncertain"],
               "missing_signals": _compute_missing_signals(discovered["lists"]),
               "brand_short": discovered["brand_short"], "event_name": discovered["event_name"]})
    except Exception as exc:
        log.error(f"[DISCOVERY] fatal error: {exc}", exc_info=True)
        q.put({"type": "output", "text": f"❌ Discovery error: {exc}"})
        q.put({"type": "done", "done": True, "success": False,
               "lists": discovered["lists"], "uncertain": discovered["uncertain"],
               "missing_signals": _compute_missing_signals(discovered["lists"]),
               "brand_short": discovered["brand_short"], "event_name": discovered["event_name"]})


def start_discovery_job(event_url: str, qa: str = "") -> str:
    """Start a discovery job. Returns job_id for SSE polling via
    GET /api/audience-builder/discover-stream/{job_id}."""
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    log.info(f"[DISCOVERY] job {job_id[:8]} — url={event_url!r}")
    prompt = build_discovery_prompt(event_url, qa=qa)
    threading.Thread(target=_run_discovery_agent, args=(prompt, q), daemon=True).start()
    return job_id


def get_job_queue(job_id: str) -> queue.Queue | None:
    return _jobs.get(job_id)


def remove_job(job_id: str) -> None:
    _jobs.pop(job_id, None)
