"""
Agentic HubSpot-list discovery: given an event URL, scrapes the event page,
searches HubSpot for existing lists/campaigns related to it, and classifies
matches into 6 signal buckets for the user to pick from. Read-only — the
agent has no tool that can create or modify anything in HubSpot.

Ported/adapted from emailcreationskill/backend/audience_builder/discovery_agent.py.
Adapted to this project's module layout:
  - `import llm_gateway`                                -> `from llm import gateway as llm_gateway`
  - `from audience_builder.discovery_tools import ...`  -> `from audience_builder.tools import ...`
"""
import queue
import threading
import uuid

from llm import gateway as llm_gateway
from audience_builder.tools import TOOL_DEFS_OPENAI, TOOL_HANDLERS

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
    "You are a HubSpot marketing-operations assistant helping find EXISTING contact "
    "lists relevant to promoting an event, so the user can reuse them instead of "
    "rebuilding an audience from scratch. You are strictly read-only: you cannot "
    "create, edit, or delete anything in HubSpot. Investigate thoroughly using the "
    "tools available, then call present_discovered_lists exactly once with your "
    "findings. Never fabricate list IDs, sizes, or filter details — only report what "
    "the tools actually returned."
)

DISCOVERY_PROMPT_TEMPLATE = """\
Find existing HubSpot lists relevant to promoting this event: {event_url}

{qa_block}
Work through these steps:

STEP 1 — Identify the event.
Call web_fetch on the event URL. From the page content, identify:
  - The event's proper name (event_name)
  - Its short brand/foundation code (brand_short), e.g. CNCF, PyTorch, Hyperledger, LF
  - Its dates (event_dates), if visible

STEP 2 — Search broadly for related HubSpot assets.
Call hubspot_search_lists and hubspot_search_campaigns using the event's core name
alone (e.g. "KubeCon" rather than "KubeCon North America 2026Q2 EMEA") — a broad query
surfaces every edition/country/quarter variant in ONE call, since HubSpot caps search
results at 20 and does not return them in any recency order. Only narrow the query if
the broad one returns nothing usable. Do not iterate one narrow guess after another.

STEP 3 — Classify each relevant list into exactly one of these 6 signals, by
inspecting its actual filter SHAPE via hubspot_get_list — never by name alone:
  - project_opt_in        (opted in to updates about the specific open-source project)
  - lf_newsletter_opt_in   (opted in to a broader Linux Foundation / foundation newsletter)
  - event_registration     (registered/attended this event, any edition)
  - education_enrollment   (enrolled in a related training/certification course)
  - page_view              (visited event-related web pages, e.g. via tracked page-view filters)
  - event_speakers         (submitted a talk / accepted as speaker for this event)

Rules:
  1. Only classify a list into a signal if its filter branch (from hubspot_get_list)
     actually supports that classification — a plausible-sounding name is not enough.
  2. If a list rolls up other lists (nested IN_LIST filters), resolve ONE hop only —
     do not recursively expand rollups indefinitely.
  3. If a list doesn't confidently fit one of the 6 signals but still looks
     event-relevant, put it in `uncertain` instead of guessing a signal.
  4. Record the list's real `processingType` value (DYNAMIC/MANUAL/SNAPSHOT) as
     `list_type` — never guess this field; omit it if you didn't call hubspot_get_list.
  5. Record a short `reason` tying the list to its signal.
  6. For `event_speakers` specifically, determine `scope`:
       - "current" if the list is clearly scoped to only this event's upcoming edition
       - "past" if it's clearly a prior edition's speaker list
       - "current_past" if it appears to cover multiple editions or you can't tell
     Omit `scope` for every other signal.

STEP 4 — Present results.
Call present_discovered_lists exactly ONCE with brand_short, event_name, and every
list you classified (in `lists`) or couldn't confidently classify (in `uncertain`).
Do this even if you found few or no matches — an empty `lists`/`uncertain` array is a
valid and useful result; do not keep searching indefinitely.
"""


def build_discovery_prompt(event_url: str, qa: str = "") -> str:
    qa_block = f"Additional context from the user:\n{qa}\n\n" if qa else ""
    return DISCOVERY_PROMPT_TEMPLATE.format(event_url=event_url, qa_block=qa_block)


def _normalize_list_items(items: list) -> list:
    """Normalize camelCase keys some model responses use (listId/notes/listType)
    into the snake_case shape routes.py/models.py expect."""
    out = []
    for item in items or []:
        out.append({
            "list_id": str(item.get("list_id") or item.get("listId") or ""),
            "name": item.get("name", ""),
            "signal": item.get("signal", ""),
            "size": item.get("size"),
            "reason": item.get("reason") or item.get("notes") or "",
            "list_type": item.get("list_type") or item.get("listType") or "",
            "scope": item.get("scope", ""),
        })
    return out


def _compute_missing_signals(lists: list) -> list:
    present = {l.get("signal") for l in lists}
    return [s for s in ALL_SIGNALS if s not in present]


def _discovery_execute(name: str, tool_input: dict) -> str:
    import json
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = handler(tool_input)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


_jobs: dict = {}


def _run_discovery_agent(prompt: str, q: "queue.Queue") -> None:
    discovered_payload = {"lists": [], "uncertain": [], "brand_short": "", "event_name": ""}

    def _on_event(event: dict) -> None:
        etype = event.get("type")
        if etype == "output_delta":
            q.put({"type": "output", "text": event.get("text", "")})
        elif etype == "output":
            q.put({"type": "output", "text": event.get("text", "")})
        elif etype == "tool":
            q.put({"type": "tool", "name": event.get("name"), "input": event.get("input")})
            if event.get("name") == "present_discovered_lists":
                inp = event.get("input") or {}
                discovered_payload["lists"] = _normalize_list_items(inp.get("lists"))
                discovered_payload["uncertain"] = _normalize_list_items(inp.get("uncertain"))
                discovered_payload["brand_short"] = inp.get("brand_short", "")
                discovered_payload["event_name"] = inp.get("event_name", "")
        elif etype == "tool_result":
            q.put({"type": "tool_result", "text": event.get("text", "")})

    try:
        messages = [{"role": "user", "content": prompt}]
        llm_gateway.run_agent(
            messages,
            system=DISCOVERY_SYSTEM,
            tools=DISCOVERY_TOOLS,
            execute_tool=_discovery_execute,
            max_tokens=16000,
            max_steps=40,
            on_event=_on_event,
        )
        if discovered_payload["lists"] or discovered_payload["uncertain"]:
            discovered_payload["missing_signals"] = _compute_missing_signals(discovered_payload["lists"])
            q.put({"type": "discovered", "data": discovered_payload})
        else:
            q.put({"type": "error", "text": "Agent finished without calling present_discovered_lists."})
    except Exception as exc:
        q.put({"type": "error", "text": str(exc)})
    finally:
        q.put({"type": "done"})


def start_discovery_job(event_url: str, qa: str = "") -> str:
    job_id = uuid.uuid4().hex
    q: "queue.Queue" = queue.Queue()
    _jobs[job_id] = q
    prompt = build_discovery_prompt(event_url, qa)
    t = threading.Thread(target=_run_discovery_agent, args=(prompt, q), daemon=True)
    t.start()
    return job_id


def get_job_queue(job_id: str):
    return _jobs.get(job_id)


def remove_job(job_id: str) -> None:
    _jobs.pop(job_id, None)
