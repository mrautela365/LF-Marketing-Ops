"""
Audience list builder — two-phase (PLANNING → BUILDING).

Uses the OpenAI-compatible LiteLLM proxy (same agent loop as lf-event-studio).
Falls back to Claude CLI subprocess when LITELLM_BASE_URL / LITELLM_API_KEY are not set.

All tool implementations are ported verbatim from
  lf-event-studio/app/tools.py
All prompt text is ported verbatim from
  lf-event-studio/app/prompts.py
The agent loop is ported verbatim from
  lf-event-studio/app/agent.py
"""
import datetime
import decimal
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config import (
    LITELLM_BASE_URL, LITELLM_API_KEY,
    HUBSPOT_ACCESS_TOKEN, HUBSPOT_PORTAL_ID,
    tag_asset_name,
)
import llm_gateway   # ALL AI calls route through this single deterministic gateway
from filter_optimizer import FilterOptimizer


def _optimize_filter_branch(filter_branch: dict) -> dict:
    """
    Apply automatic filter optimization to reduce redundant conditions.

    Combines multiple AND branches with identical structure but different
    values into a single combined branch using MULTISTRING values.
    """
    optimizer = FilterOptimizer(verbose=True)
    optimized = optimizer.optimize(filter_branch)
    if optimizer.optimizations_applied:
        log.info(optimizer.summary())
    return optimized


def _json_default(obj):
    """Fallback encoder for json.dumps — handles date/datetime/Decimal values that
    can slip into tool results (e.g. raw Snowflake rows) without crashing the agent loop."""
    if isinstance(obj, (datetime.date, datetime.datetime, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    return str(obj)


log = logging.getLogger("audience-builder")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    log.addHandler(_h)
    log.propagate = False

# ── Startup diagnostics ───────────────────────────────────────────────────────
# Logged once at import time so you can immediately see which mode will be used.
def _log_startup() -> None:
    has_litellm = bool(LITELLM_BASE_URL and LITELLM_API_KEY)
    mode = f"LiteLLM ({LITELLM_BASE_URL})" if has_litellm else "CLI fallback"
    log.info(f"[STARTUP] audience mode: {mode}")
    log.info(f"[STARTUP] LITELLM_BASE_URL={'set' if LITELLM_BASE_URL else 'MISSING'} "
             f"LITELLM_API_KEY={'set' if LITELLM_API_KEY else 'MISSING'} "
             f"HUBSPOT_ACCESS_TOKEN={'set' if HUBSPOT_ACCESS_TOKEN else 'MISSING'}")

_log_startup()

# Snowflake + cryptography (optional — import error is caught gracefully)
try:
    import snowflake.connector
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, load_pem_private_key,
    )
    _SNOWFLAKE_AVAILABLE = True
except ImportError:
    _SNOWFLAKE_AVAILABLE = False

# ── Paths ──────────────────────────────────────────────────────────────────────
_BACKEND        = Path(__file__).parent
SKILL_DIR       = _BACKEND.parent / "skills" / "hubspot-event-list-builder"
_REFERENCES_DIR = SKILL_DIR / "references"

# ── In-memory job store ────────────────────────────────────────────────────────
_jobs: dict[str, queue.Queue] = {}

# ── CLI timeout ────────────────────────────────────────────────────────────────
_CLI_TIMEOUT = 900  # 15 min

# ── HubSpot base URL ───────────────────────────────────────────────────────────
_HS_BASE = "https://api.hubapi.com"


def _hs_headers() -> dict:
    return {
        "Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Tool implementations (ported from lf-event-studio/app/tools.py)
# ══════════════════════════════════════════════════════════════════════════════

def web_fetch(url: str) -> dict:
    """Fetch a URL and return its cleaned text content."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l for l in text.splitlines() if l.strip()]
        return {"url": url, "status": r.status_code, "content": "\n".join(lines)[:12000]}
    except Exception as exc:
        return {"url": url, "error": str(exc)}


def hubspot_search_campaigns(query: str) -> dict:
    """Search HubSpot marketing emails by name or subject."""
    url = f"{_HS_BASE}/marketing/v3/emails"
    params = {"limit": 50, "sort": "-updatedAt"}
    r = requests.get(url, headers=_hs_headers(), params=params, timeout=15)
    r.raise_for_status()
    emails = r.json().get("results", [])
    q_lower = query.lower()
    matches = [
        {
            "id": e.get("id"),
            "name": e.get("name"),
            "subject": e.get("subject"),
            "updatedAt": e.get("updatedAt"),
            "stats": e.get("stats", {}),
        }
        for e in emails
        if q_lower in (e.get("name", "") + " " + e.get("subject", "")).lower()
    ]
    return {"query": query, "results": matches[:15]}


def hubspot_search_lists(query: str) -> dict:
    """Search HubSpot contact lists by name."""
    url = f"{_HS_BASE}/crm/v3/lists/search"
    payload = {"query": query, "count": 20, "includeFilters": False}
    r = requests.post(url, headers=_hs_headers(), json=payload, timeout=15)
    r.raise_for_status()
    lists = r.json().get("lists", [])

    def _size(l: dict):
        raw = l.get("size")
        if raw is None:
            raw = (l.get("additionalProperties") or {}).get("hs_list_size")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "query": query,
        "results": [
            {"listId": l.get("listId"), "name": l.get("name"), "size": _size(l)}
            for l in lists
        ],
    }


def hubspot_get_list(list_id: str) -> dict:
    """Get a HubSpot contact list including its filter branch."""
    url = f"{_HS_BASE}/crm/v3/lists/{list_id}"
    r = requests.get(url, headers=_hs_headers(), params={"includeFilters": "true"}, timeout=15)
    r.raise_for_status()
    return r.json()


def hubspot_list_membership_ids(list_id: str, cap_pages: int = 100) -> set:
    """Exact set of contact record IDs currently in a list, via
    /crm/v3/lists/{listId}/memberships pagination (confirmed shape:
    {"results": [{"recordId": "..."}], "paging": {"next": {"after": "..."}}}).
    Capped at cap_pages*250 (~25k) records — used only for the bounded
    exact-union-count preview, never for anything unbounded."""
    ids: set = set()
    after = None
    url = f"{_HS_BASE}/crm/v3/lists/{list_id}/memberships"
    for _ in range(cap_pages):
        params = {"limit": 250}
        if after:
            params["after"] = after
        r = requests.get(url, headers=_hs_headers(), params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        for rec in data.get("results", []):
            rid = rec.get("recordId")
            if rid:
                ids.add(str(rid))
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    return ids


def hubspot_search_emails_raw(name_contains: str, limit: int = 30) -> list:
    """Like hubspot_search_campaigns, but returns full raw HubSpot email
    objects (state/publishDate/to.contactLists/to.contactIlsLists included)
    for callers that need more than the id/name/subject/updatedAt/stats
    projection — mirrors the exact /marketing/v3/emails + name__icontains +
    orderBy=-publishDate pattern already proven in
    hubspot_tools.lookup_brand_history, which reads include/exclude list IDs
    straight off these list-search results with no extra per-email GET
    needed."""
    url = f"{_HS_BASE}/marketing/v3/emails"
    params = {"limit": limit, "name__icontains": name_contains, "orderBy": "-publishDate"}
    r = requests.get(url, headers=_hs_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("results", [])


def hubspot_create_list(name: str, filter_branch: dict) -> dict:
    """Create a new dynamic HubSpot contact list."""
    # Apply automatic filter optimization
    filter_branch = _optimize_filter_branch(filter_branch)

    url = f"{_HS_BASE}/crm/v3/lists/"
    payload = {
        "name": tag_asset_name(name),
        "objectTypeId": "0-1",
        "processingType": "DYNAMIC",
        "filterBranch": filter_branch,
    }
    r = requests.post(url, headers=_hs_headers(), json=payload, timeout=15)
    if not r.ok:
        raise RuntimeError(f"HubSpot {r.status_code}: {r.text[:500]}")
    data = r.json()
    list_id = data.get("listId") or data.get("list", {}).get("listId")
    hs_url = (
        f"https://app.hubspot.com/contacts/{HUBSPOT_PORTAL_ID}/objectLists/{list_id}/filters"
        if list_id else None
    )
    return {
        "listId": list_id,
        "name": data.get("name"),
        "size": data.get("size"),
        "hubspot_url": hs_url,
    }


def hubspot_update_list_filters(list_id: str, filter_branch: dict) -> dict:
    """Replace the filter branch on an existing HubSpot list."""
    # Apply automatic filter optimization
    filter_branch = _optimize_filter_branch(filter_branch)

    url = f"{_HS_BASE}/crm/v3/lists/{list_id}/filter-branch"
    r = requests.put(url, headers=_hs_headers(), json={"filterBranch": filter_branch}, timeout=15)
    if not r.ok:
        raise RuntimeError(f"HubSpot {r.status_code}: {r.text[:500]}")
    hs_url = f"https://app.hubspot.com/contacts/{HUBSPOT_PORTAL_ID}/objectLists/{list_id}/filters"
    return {"listId": list_id, "updated": True, "hubspot_url": hs_url}


def hubspot_get_event_types() -> dict:
    """List HubSpot custom event type definitions."""
    url = f"{_HS_BASE}/events/v3/event-definitions"
    r = requests.get(url, headers=_hs_headers(), params={"limit": 100, "includeProperties": "true"}, timeout=15)
    if not r.ok:
        return {"error": f"HubSpot {r.status_code}: {r.text[:300]}"}
    defs = r.json().get("results", [])
    return {
        "results": [
            {
                "fullyQualifiedName": d.get("fullyQualifiedName"),
                "label": d.get("label"),
                "name": d.get("name"),
                "properties": d.get("properties", []),
            }
            for d in defs
        ]
    }


def _sf_private_key_bytes() -> bytes:
    """Load Snowflake private key from SNOWFLAKE_PRIVATE_KEY env var (PEM string)."""
    pem = os.environ.get("SNOWFLAKE_PRIVATE_KEY", "").strip()
    if not pem:
        raise RuntimeError("SNOWFLAKE_PRIVATE_KEY not set")
    # Common .env copy/paste mistakes: stray wrapping quotes, literal \n / \r\n escapes,
    # and real CRLF line endings (all of which produce "MalformedFraming" from cryptography).
    if len(pem) >= 2 and pem[0] == pem[-1] and pem[0] in "'\"":
        pem = pem[1:-1].strip()
    pem = pem.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    try:
        key = load_pem_private_key(pem.encode(), password=None, backend=default_backend())
    except Exception as exc:
        raise RuntimeError(
            f"Failed to parse SNOWFLAKE_PRIVATE_KEY as a PEM key ({exc}). "
            "Check that .env holds the full unencrypted PKCS8 PEM "
            "(BEGIN/END PRIVATE KEY lines) with line breaks preserved as literal \\n."
        ) from exc
    return key.private_bytes(
        encoding=Encoding.DER,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )


def _sf_connect():
    if not _SNOWFLAKE_AVAILABLE:
        raise RuntimeError("snowflake-connector-python not installed — run: pip install snowflake-connector-python cryptography")
    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Snowflake env vars not set: {', '.join(missing)}")
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key=_sf_private_key_bytes(),
        database=os.environ.get("SNOWFLAKE_DATABASE", "ANALYTICS"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA", "Silver_Segment"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE") or None,
        role=os.environ.get("SNOWFLAKE_ROLE") or None,
    )


def _sf_json_safe(value):
    """Convert a Snowflake column value (date/datetime/Decimal/etc.) to a JSON-serializable type."""
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


def snowflake_query(sql: str) -> dict:
    """Run a SQL query against Snowflake and return rows as a list of dicts."""
    conn = _sf_connect()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [{col: _sf_json_safe(val) for col, val in zip(cols, row)} for row in cur.fetchall()]
        return {"columns": cols, "rows": rows, "count": len(rows)}
    finally:
        conn.close()


def read_reference_file(filename: str) -> dict:
    """Read a file from the references/ directory (e.g. brand-master-lists.md)."""
    safe = Path(filename).name
    path = _REFERENCES_DIR / safe
    try:
        return {"filename": safe, "content": path.read_text(encoding="utf-8")}
    except FileNotFoundError:
        return {"error": f"{safe} not found in references/"}
    except Exception as exc:
        return {"error": str(exc)}


# ── Tool definitions (OpenAI / LiteLLM format) ────────────────────────────────

def _fn(name: str, description: str, properties: dict, required: list) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


TOOL_DEFS_OPENAI = [
    _fn("web_fetch",
        "Fetch the text content of any URL. Use to scrape event pages.",
        {"url": {"type": "string", "description": "The URL to fetch"}},
        ["url"]),

    _fn("hubspot_search_campaigns",
        "Search HubSpot marketing emails by keyword (name or subject). Use to find prior sends for an event. "
        "Query broad first (event series name alone, e.g. 'Open Source Summit') — this returns every edition/"
        "country in one call. Only narrow the query if the broad one returns nothing; don't guess quarter/"
        "country/year permutations one at a time.",
        {"query": {"type": "string", "description": "Search keyword — event series name alone, e.g. 'KubeCon' not 'KubeCon North America 26Q3'"}},
        ["query"]),

    _fn("hubspot_search_lists",
        "Search HubSpot contact lists by name keyword. Query broad first (event series name alone) to see "
        "every edition/country/quarter variant in one call, then pick the match you need — don't iterate "
        "narrow guesses one at a time.",
        {"query": {"type": "string", "description": "List name keyword — event series name alone, not a full quarter+country guess"}},
        ["query"]),

    _fn("hubspot_get_list",
        "Get details of a HubSpot contact list by ID, including its filter branch.",
        {"list_id": {"type": "string", "description": "The numeric HubSpot list ID"}},
        ["list_id"]),

    _fn("hubspot_create_list",
        (
            "Create a new dynamic HubSpot contact list. "
            "filter_branch must follow the HubSpot filterBranch schema. "
            "For custom-event filters (past registrants, education enrolled, etc.) "
            "use filterBranchType='UNIFIED_EVENTS' with a fixed portal eventTypeId. "
            "For list-membership filters use filterType='LIST_MEMBERSHIP' or 'IN_LIST'. "
            "For page-view filters use filterType='PAGE_VIEW'."
        ),
        {
            "name":          {"type": "string", "description": "List name"},
            "filter_branch": {"type": "object", "description": "HubSpot filterBranch object"},
        },
        ["name", "filter_branch"]),

    _fn("hubspot_update_list_filters",
        "Replace the filter branch of an existing HubSpot contact list.",
        {
            "list_id":       {"type": "string"},
            "filter_branch": {"type": "object"},
        },
        ["list_id", "filter_branch"]),

    _fn("hubspot_get_event_types",
        "List all HubSpot custom event type definitions. Use to find the fullyQualifiedName for behavioral event filters.",
        {}, []),

    _fn("snowflake_query",
        (
            "Run a SQL query against Snowflake. "
            "Default database: ANALYTICS, schema: Silver_Segment. "
            "Use to find past event editions in EVENT_REGISTRATIONS."
        ),
        {"sql": {"type": "string", "description": "SQL query to execute"}},
        ["sql"]),

    _fn("read_reference_file",
        (
            "Read a file from the references/ directory. Use 'brand-master-lists.md' to look up "
            "brand master list IDs, or 'region-map.md' to look up an event's broader region "
            "(APAC/EMEA/NA/LATAM) for building the regional-expansion inclusion lists."
        ),
        {"filename": {"type": "string", "description": "Filename only, e.g. 'brand-master-lists.md' or 'region-map.md'"}},
        ["filename"]),

    _fn("present_open_questions",
        (
            "Present open/blocking questions to the user as selectable UI instead of plain text. "
            "Call this ONCE, during PLANNING only, when something must be confirmed before the "
            "segment plan can be finalized (location scope, which event(s), job-title approval, "
            "mailability gate, suppressions to apply, etc). After calling it, stop your turn — "
            "do not keep building further plan detail past this point; the user's answers will be "
            "appended to a new planning pass."
        ),
        {
            "questions": {
                "type": "array",
                "description": "One entry per open question.",
                "items": {
                    "type": "object",
                    "properties": {
                        "question":     {"type": "string", "description": "The question text"},
                        "why_it_blocks": {"type": "string", "description": "Why this blocks the build"},
                        "options":      {"type": "array", "items": {"type": "string"},
                                          "description": "Selectable options, e.g. ['Yes', 'No', 'Seoul only', 'Seoul + South Korea']"},
                        "allow_custom": {"type": "boolean", "description": "Whether a free-text 'Other' answer is allowed (default true)"},
                    },
                    "required": ["question", "options"],
                },
            },
        },
        ["questions"]),
]

TOOL_HANDLERS: dict = {
    "web_fetch":                   lambda i: web_fetch(i["url"]),
    "hubspot_search_campaigns":    lambda i: hubspot_search_campaigns(i["query"]),
    "hubspot_search_lists":        lambda i: hubspot_search_lists(i["query"]),
    "hubspot_get_list":            lambda i: hubspot_get_list(i["list_id"]),
    "hubspot_create_list":         lambda i: hubspot_create_list(i["name"], i["filter_branch"]),
    "hubspot_update_list_filters": lambda i: hubspot_update_list_filters(i["list_id"], i["filter_branch"]),
    "hubspot_get_event_types":     lambda i: hubspot_get_event_types(),
    "snowflake_query":             lambda i: snowflake_query(i["sql"]),
    "read_reference_file":         lambda i: read_reference_file(i["filename"]),
    "present_open_questions":      lambda i: present_open_questions(i["questions"]),
}


def present_open_questions(questions: list) -> dict:
    """No side effects here — the SSE 'question' event is emitted by _run_agent's
    on_event handler (which has queue access). This just acks the tool call so the
    agent loop can continue/stop cleanly."""
    return {"presented": len(questions or [])}

# ── Gateway integration ───────────────────────────────────────────────────────
# The same 9 tools in the canonical (Anthropic) format the gateway consumes, plus a
# single executor adapter. This is the ONLY audience AI path now — SDK and CLI both
# run through llm_gateway.run_agent, so results are deterministic and identical in
# shape regardless of backend (and the CLI path no longer needs Chrome/HubSpot MCP —
# it drives these Python tools directly).
AUDIENCE_TOOLS = llm_gateway.openai_tools_to_anthropic(TOOL_DEFS_OPENAI)

AUDIENCE_SYSTEM = (
    "You are an LF email audience-list building agent operating in EXECUTION MODE. "
    "Use the provided tools directly to query Snowflake and create HubSpot lists. "
    "Do NOT ask for confirmation and do NOT enter plan mode. Narrate each step."
)


def _audience_execute(name: str, tool_input: dict) -> str:
    """Execute one audience tool by name. Returns a JSON-encoded result string."""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return json.dumps(handler(tool_input), default=_json_default)
    except Exception as exc:
        log.warning(f"[AGENT] tool {name} raised: {exc}")
        return json.dumps({"error": str(exc)})


# ══════════════════════════════════════════════════════════════════════════════
# Prompts (ported verbatim from lf-event-studio/app/prompts.py)
# ══════════════════════════════════════════════════════════════════════════════

PLANNING_PROMPT_TEMPLATE = """You are an experienced LF email audience strategist.
Plan the HubSpot audience segment for this Linux Foundation event:

{url}

CRITICAL — Snowflake data integrity: past-edition EVENT_NAME values are ONLY valid
when they come from a successful snowflake_query call against EVENT_REGISTRATIONS.
If snowflake_query fails (connection/key error) or you skip calling it, do NOT
substitute guessed, remembered, or web-researched event name strings — including
values copied from existing HubSpot list filters (e.g. communitySeg snapshots).
Report the failure plainly and list past-registrant segmentation under
"Open questions / flags" as unresolved until Snowflake is reachable.

CRITICAL — Location scoping: many LF event series run parallel editions in
different countries/cities under the same brand (e.g. "MCP Dev Summit" has run
in North America, Seoul, Toronto, Bengaluru, Mumbai, and Nairobi; "KubeCon +
CloudNativeCon" has North America / Europe / China / Japan editions). Every
past-registrant and geographic inclusion segment you propose MUST be for the
SAME city/country/edition as the CURRENT event being planned — never propose a
segment for a different edition of the same series just because it shares a
brand or short name. If a prior master list you find in STEP 2 blended multiple
editions/countries into one list, do NOT reproduce that structure — note it
under "Open questions / flags" as a legacy pattern to leave behind, and scope
your new plan to this event's own location only.

CRITICAL — Regional-expansion segments (groups 4-7): every master list also
carries a standard second tier of FOUR inclusion lists that broaden reach
beyond this exact event, scoped to this event's own COUNTRY and its broader
REGION (not other editions of this series — that's the Location scoping rule
above, which stays untouched):
  4. Education Enrolled [Country] — anyone who ever enrolled in LF Education,
     located in this event's own country.
  5. Event Registered [Country] — anyone who ever registered for ANY past LF
     event (any brand), located in this event's own country.
  6. Expanded Web Visitors — visited the page of the nearest sibling event in
     the same broader region, OR visited training.linuxfoundation.org while
     located in this event's own country.
  7. [Region] Event Registrants — registrants of sibling events (any brand)
     held in OTHER countries of the same broader region during this event
     cycle (e.g. for an APAC event: other APAC editions of any LF/CNCF series).
Use read_reference_file("region-map.md") to find this event's region and how
to discover its sibling events. These 4 lists are standard and should be
proposed for every event unless the foundation has no LF Education presence
or no sibling events this cycle — in which case note it as N/A under "Open
questions / flags" rather than omitting them silently.

CRITICAL — Product/technology domain fit (groups 4, 5, 7 — MUST NOT violate):
The regional-expansion groups above broaden the audience beyond this event's
own registrants (group 1) and its own page/training visits (group 6, which
this rule does NOT touch), so they are the most likely place to accidentally
cross technology domains. Before researching groups 4/5/7, classify THIS
event from its scraped page content (STEP 1):
  a) Domain bucket — exactly one of HARDWARE or SOFTWARE/AI. HARDWARE means
     the event centers on physical systems, embedded/real-time engineering,
     automotive, robotics, industrial, or safety-critical firmware. SOFTWARE/AI
     means everything else that is primarily software, cloud, platform,
     developer-tooling, or AI/agentic in focus. Judge every event from its own
     page content — do not rely on a fixed list of past examples.
  b) Specific project/technology focus — a short free-text label naming the
     concrete project(s)/technology area the event centers on (e.g.
     "Kubernetes/cloud-native", "AI/agentic", "embedded automotive Linux",
     "PyTorch/ML", "observability").
Record both under a new **Product/technology domain** line in the STEP 4
report — the BUILDING phase does not re-scrape the event page, so this is the
ONLY place that classification is available downstream.
MUST NOT (non-negotiable, symmetric): when researching or building groups 4,
5, or 7, never include a past event or education enrollment whose bucket is
HARDWARE if the current event's bucket is SOFTWARE/AI, and never include one
whose bucket is SOFTWARE/AI if the current event's bucket is HARDWARE. This
floor rule applies regardless of any finer-grained project/technology
similarity judgment you also apply — bucket mismatch alone is disqualifying.
Within the same bucket, prefer events/courses in a similar or adjacent
project/technology area over an indiscriminate match — use judgment, not a
fixed lookup table.

Work through ALL 4 steps below, narrating each sub-step so progress is visible.

{step1}
═══════════════════════════════════════════════════
STEP 2 — Find previous edition emails in HubSpot
═══════════════════════════════════════════════════
Use hubspot_search_campaigns to find emails sent for the previous year's edition.
Try: event short name, foundation + event type, year variants (2025, 2024).

For each email found, note: name, subject, send date, list used, metrics.

Then use hubspot_search_lists to find the master list used for prior sends.
Note the list name, ID, and any opt-in filter pattern in the name.

Also search for each of the inclusion lists referenced in prior sends:
past-registrant lists, geographic lists, topic/persona lists, newsletter lists, etc.
Use hubspot_get_list on any list IDs found to inspect their filter logic.

Also research this event's regional-expansion groups (4-7, see the CRITICAL note
above): read_reference_file("region-map.md") for this event's region, then
hubspot_search_campaigns / hubspot_search_lists for sibling events (other
countries in the same region, current cycle) to identify candidates for the
Expanded Web Visitors and [Region] Event Registrants lists.

Search efficiently — do NOT brute-force many quarter/country/keyword permutations
one query at a time (e.g. "26Q3 United States", "26Q3 26Q4 US registrants",
"Open Source Summit US 2026", "Open Source Summit North America 2026", ...).
List names follow the pattern "(Segment) <Quarter> - <Event Series Name> <Year> -
<Country> Geo", so ONE broad query on just the event SERIES name (e.g.
"Open Source Summit", no quarter/country/year) returns every edition/country in
one shot — inspect that result set for the sibling country you need instead of
re-querying with a new guess each time a query comes back empty. Same for
hubspot_search_campaigns: query the series name alone first. Only issue a second,
more specific query if the broad one returns nothing at all.

For groups 5 and 7, factor in this event's domain bucket + project/technology
focus (from STEP 1) when evaluating candidates. Group 5's exact past EVENT_NAME
values will be re-queried fresh from Snowflake in the BUILDING phase (per the
Snowflake data-integrity rule above), so here you only need to record this
event's own domain classification in the STEP 4 report for that later step to
use. For group 7, from the sibling events you find via region-map.md, keep
only ones in the SAME domain bucket as this event (HARDWARE vs SOFTWARE/AI —
see the CRITICAL note above) and prefer ones in a similar/adjacent project or
technology area; a domain-bucket mismatch is never acceptable even if it's the
only sibling event found — treat that case as N/A instead.

When inspecting a prior master list's filter branches, check whether any AND
branch's event-name value (UNIFIED_EVENTS/event_name, or legacy BEHAVIORAL_EVENT/
hs_event_name) names a DIFFERENT city/country than this event's own location. If
so, that branch belongs to a different edition of the series (see the Location
scoping rule above) — record it as a legacy cross-edition branch to leave out,
not as a template to copy.

═══════════════════════════════════════════════════
STEP 3 — Analyse historical segmentation logic
═══════════════════════════════════════════════════
Reconstruct the full audience strategy from prior emails and lists:

Inclusion sources: past registrants, web visitors, geographic segments,
topic interests, newsletter subscribers, foundation subscriber lists.
Past-registrant and geographic sources are scoped to THIS event's own
city/country only — one segment for this edition, not one per country the
series has ever run in (see the Location scoping rule above).

Exclusion sources: LF Events Global Opt Outs, LF Global Opt-Outs,
GDPR suppression, current registrants, internal LF contacts,
foundation-specific opt-outs.
"Current registrants" means people ALREADY REGISTERED for THIS SAME upcoming
event (the one being planned right now) — they must be suppressed, never
included, since re-inviting someone who already registered is the mistake this
exclusion exists to prevent. Do not confuse this with past-registrant inclusion
sources above: past editions (prior years, same location) are for INCLUSION;
this event's own current-year registrants are for EXCLUSION only.

Opt-in filter logic: whether applied, which variant (Foundation / LF Events /
LF Newsletter), and why.

Flag any communitySeg / community_seg lists found. They are retired — exclude them
entirely from the plan. Do not propose rebuilding, replacing, or otherwise reusing
their logic; just note that they were found and excluded.

═══════════════════════════════════════════════════
STEP 4 — Produce the Segment Plan Report
═══════════════════════════════════════════════════
Write a complete structured report using this format:

### 📋 Event Segment Plan: [Event Name] [Year]

**Event summary** — name, foundation, location, dates, type.

**Product/technology domain** — HARDWARE or SOFTWARE/AI bucket, plus the
specific project/technology focus (see the CRITICAL "Product/technology
domain fit" note above). This is carried verbatim into the BUILDING phase,
which does not re-scrape the event page.

**Historical context** — prior master list name, send counts, key changes, QA notes.
If the prior master list included past-registrant branches for OTHER cities/countries
of this series, name them here and state they are being dropped (not carried forward).

**Recommended master list name**
Follow foundation naming convention, e.g.:
`Q3 2026 - CNCF Foundation - KubeCon + CloudNativeCon North America Master (With Opt-In and Filters)`

**Inclusion strategy** — per source list: name, why it belongs, dynamic vs snapshot.
Group by and number each list:
  1. Past registrants of THIS event's own location only (UNIFIED_EVENTS filter —
     one segment per past YEAR of this same city/country, never per other country)
  2. Web visitors (PAGE_VIEW only — no brand-master gate)
  3. Geographic segments for THIS event's own country/region only
     (LIST_MEMBERSHIP + brand-master gate — mandatory, if applicable)
  4. Education Enrolled [Country] — standard regional-expansion group (see CRITICAL
     note above); N/A only if the foundation has no LF Education presence.
     Country-gated only by default; note under "Open questions / flags" that a
     course/topic-level domain filter depends on a HubSpot property the
     BUILDING phase must investigate via hubspot_get_event_types.
  5. Event Registered [Country] — standard regional-expansion group; past LF
     event registrations (any brand), gated by this event's own country AND
     filtered to this event's domain bucket (see CRITICAL "Product/technology
     domain fit" note above) — never "any past event" unfiltered
  6. Expanded Web Visitors — standard regional-expansion group; nearest sibling
     regional event's page OR training.linuxfoundation.org + this event's country
  7. [Region] Event Registrants — standard regional-expansion group; registrants
     of sibling events in the same broader region this cycle, filtered to this
     event's domain bucket (see CRITICAL "Product/technology domain fit" note
     above); N/A only if none found in-bucket
  8. Topic / persona lists (if applicable)
  9. Foundation / newsletter subscribers (if applicable)
  10. Any other inclusion lists from prior sends

For each inclusion list, state:
  - Proposed HubSpot list name
  - Filter type (UNIFIED_EVENTS / PAGE_VIEW / LIST_MEMBERSHIP / property)
  - Why it belongs

**Exclusion strategy** — per suppression list: name and reason.
Always include: LF Events Global Opt Outs, LF Global Opt-Outs, GDPR Suppression (if EU in scope),
23Q1 LF Master Exclusion List, foundation opt-out, and this event's OWN current-year
registrants (people already registered for the event being planned — build this fresh
from Snowflake in the BUILDING phase if no existing HubSpot list already tracks it;
never skip it just because it doesn't exist yet).

**Opt-in filter recommendation** — whether to apply, which variant, and why.

**Estimated list size** — based on prior counts, expected growth, opt-in filter impact.

**Recommended HubSpot list structure** — filter group sketch (OR/AND logic).

**communitySeg lists** — list each one found and confirm it is excluded from this plan.
Do not recommend rebuilding, replacing, or reusing any of them.

**Open questions / flags** — anything to confirm before building.

If any open question is genuinely blocking (something the build cannot proceed
without confirming — location scope, which event(s), job-title approval,
mailability gate, suppressions to apply), ALSO call the present_open_questions
tool with one entry per blocking question (question text, why it blocks, and a
short list of selectable options) so the user can answer via the UI instead of
free text. Call it once, after finishing the rest of this plan output, and stop
your turn immediately after — do not keep narrating past it.

End with: "Ready to proceed? Say yes and I'll build the segment in HubSpot."
"""

_STEP1_SCRAPE = """═══════════════════════════════════════════════════
STEP 1 — Scrape the event page
═══════════════════════════════════════════════════
Use web_fetch to fetch the URL above. Extract:
- Event name (full title, e.g. "KubeCon + CloudNativeCon North America 2026")
- Short name / slug (e.g. "KCNA", "OSSNA") — used for HubSpot search terms
- Foundation / brand (e.g. CNCF, The Linux Foundation, PyTorch, OpenSearch)
- Location (city + country/region)
- Event dates and year
- Event type (in-person conference, virtual, hybrid, summit)
- Core product/technology domain — HARDWARE or SOFTWARE/AI bucket, plus the
  specific project/technology focus (see the CRITICAL "Product/technology
  domain fit" note above); judge this from the page's description/topics/
  tracks, not just the event name
"""


def _format_prescraped_step1(data: dict) -> str:
    """Render already-scraped event data (from the Email Content stage) into the
    STEP 1 block so the planning agent doesn't hit the event page a second time."""
    dates = ", ".join(data.get("event_dates") or []) or "unknown"
    headings = ", ".join(data.get("headings") or []) or "none captured"
    return f"""═══════════════════════════════════════════════════
STEP 1 — Event details (already scraped — do NOT re-fetch the page)
═══════════════════════════════════════════════════
The event page was already scraped while drafting the email content. Use this data
directly instead of calling web_fetch on the URL above:

- Event name: {data.get("event_name") or "unknown"}
- Foundation / brand: {data.get("brand_name") or "unknown"}
- Location: {data.get("location") or "unknown"}
- Event dates: {dates}
- Description: {data.get("description") or "unknown"}
- Page headings: {headings}

Derive the short name / slug, event type, and the Product/technology domain
(HARDWARE vs SOFTWARE/AI bucket + specific project/technology focus — see the
CRITICAL "Product/technology domain fit" note above) from the description and
page headings above. Do NOT call web_fetch for this URL — it has already been
scraped and re-fetching would waste a step. Only fall back to web_fetch if a
detail you need is genuinely missing from the data above.
"""


def build_planning_prompt(url: str, prescraped: dict | None = None, qa: str = "") -> str:
    step1 = _format_prescraped_step1(prescraped) if prescraped else _STEP1_SCRAPE
    prompt = PLANNING_PROMPT_TEMPLATE.format(url=url, step1=step1)
    if qa:
        prompt += (
            f"\n\nThe user has already answered these clarifying questions from a prior "
            f"planning pass — incorporate the answers directly, do not ask them again:\n{qa}\n"
        )
    return prompt


BUILDING_PROMPT = """Build ALL the HubSpot audience lists for this Linux Foundation event.

Event URL: {url}

The segment planning phase is COMPLETE — the event page has already been scraped.
Do NOT re-scrape or re-fetch the event URL.
All event details (name, brand, location, year, page URL) are in the Segment Plan below.

--- SEGMENT PLAN ---
{plan}
--- END SEGMENT PLAN ---
{qa_section}
═══════════════════════════════════════════════════
CRITICAL RULES (enforce throughout all steps)
═══════════════════════════════════════════════════
RULE 1 — Build EVERY inclusion list from the plan, not just 2.
  Read the "Inclusion strategy" section carefully. Create one HubSpot list per
  numbered inclusion source. Do not skip any — this includes the 4 standard
  regional-expansion lists (Education Enrolled / Event Registered / Expanded Web
  Visitors / [Region] Event Registrants) unless the plan flagged one N/A.

RULE 2 — communitySeg lists MUST NEVER be used, referenced, or rebuilt:
  Any list labelled communitySeg / community_seg must NOT be included as a source,
  and its logic must NOT be reproduced under a different filter type. Do not propose
  or build a UNIFIED_EVENTS (or any other) rebuild of it. Skip it entirely and add
  it to ## FLAGGED FOR REVIEW with reason "communitySeg — excluded per policy".

RULE 3 — Print ## BUILD PLAN before creating anything in HubSpot.
  Number each list to create. State its filter type and logic.

RULE 4 — MASTER LIST IS MANDATORY. You MUST always build (create OR, per RULE 10,
  update-in-place) the master list as the final step. Even if some inclusion lists
  failed, build the master from whatever IDs you DO have. Never end without a master
  list. It is the primary deliverable.

RULE 5 — After EVERY successful hubspot_create_list call print:
  ✅ [List name] created — ID: [listId] — [hubspot_url]
  (see RULE 10 for the update-in-place case, which prints a different line)

RULE 6 — If unsure about anything → skip and add to ## FLAGGED FOR REVIEW.

RULE 7 — LOCATION SCOPING IS MANDATORY for past-registrant and geographic segments.
  [location_term] in STEP 1 MUST be this event's own specific city or, if the series
  names editions by region (e.g. "North America", "Europe"), that exact region — NEVER
  the brand/series name alone, and NEVER omitted. A vague or missing [location_term]
  causes the Snowflake query to match every past edition worldwide, producing one
  inclusion branch per country instead of per year of THIS edition. If the Segment
  Plan's rows returned by STEP 1 name a city/country/region different from this
  event's own location, DROP those rows before building — do not create a branch for
  them, and do not carry forward any cross-edition branch from a prior master list
  (see the Segment Plan's "Historical context" notes on legacy branches).

RULE 8 — Regional-expansion lists (groups 4-7) use THIS event's own country as
  [location_term] (same value as RULE 7, e.g. "Korea") for country/ip_country
  filters — never the region name itself. Sibling events for groups 6-7 come
  from the Segment Plan's regional research (read_reference_file("region-map.md")
  + hubspot_search_campaigns/hubspot_search_lists), never guessed. If the plan
  flagged a regional-expansion group N/A, skip it and note why in ## FLAGGED FOR
  REVIEW rather than building an empty or irrelevant list.

RULE 9 — PRODUCT/TECHNOLOGY DOMAIN FIT IS MANDATORY for groups 4, 5, and 7
  (non-negotiable, symmetric). Read the Segment Plan's "Product/technology
  domain" line for this event's HARDWARE-vs-SOFTWARE/AI bucket and specific
  project/technology focus. You MUST NOT include, in group 4, 5, or 7, any
  past event or education enrollment from the OPPOSITE bucket — never
  software/AI history feeding a hardware event's audience, and never hardware
  history feeding a software/AI event's audience — regardless of any other
  similarity. Within the same bucket, prefer events/courses in a similar or
  adjacent project/technology area; use judgment, not a fixed table. Apply
  this when selecting candidate EVENT_NAME values for group 5 (STEP 4 below)
  and when carrying forward group 7's sibling events from the plan. For group
  4, apply it only if/when a topic-level property is found (see STEP 2 below)
  — otherwise group 4 keeps its existing country-only filter and the gap is
  flagged, not silently dropped.

RULE 10 — REUSE, DON'T DUPLICATE. Before calling hubspot_create_list for ANY list in
  this build (each inclusion list in STEP 4, the Combined Suppression list in STEP 5B,
  and the Master list in STEP 6), call hubspot_search_lists with that list's exact
  intended name FIRST. If a list with that EXACT name already exists — this happens
  when an event's build is re-run after an earlier run (e.g. to pick up a plan fix or
  a retry) — call hubspot_update_list_filters on its existing ID with the new
  filterBranch instead of calling hubspot_create_list and making a duplicate. Print
  🔁 [List name] updated in place — ID: [listId] — [hubspot_url]
  instead of the RULE 5 "created" line for that list. Only call hubspot_create_list
  when hubspot_search_lists finds no exact-name match. This keeps re-running a build
  for the same event idempotent instead of littering the portal with duplicate
  inclusion/suppression/master lists every time.

RULE 11 — USER-ADDED FILTERS. If the Segment Plan below contains a
  "## USER-ADDED FILTERS" section, each line there is an extra condition the user
  typed in during plan review (e.g. Property "job_title" contains "director"). Add
  EVERY listed condition as an additional PROPERTY filter inside EACH inclusion
  list's AND branch(es) you build in STEP 4 (ANDed with that branch's existing
  filters — same nesting used for the RULE 9 domain-fit filter). Translate the
  plain-English operator to the matching HubSpot PROPERTY operation: "is equal to"
  → IS_EQUAL_TO, "contains" → CONTAINS_TOKEN, "is any of" → IS_ANY_OF, "is not any
  of" → NOT_ANY_OF, "is known" → HAS_PROPERTY (no value), "is unknown" →
  NOT_HAS_PROPERTY (no value); operationType "MULTISTRING" unless the property is a
  HubSpot enumeration property, in which case use "ENUMERATION". Apply to inclusion
  lists only — never to the Combined Suppression list. If a listed property name
  isn't a real HubSpot contact property, do NOT guess a similar-sounding one — skip
  it and add to ## FLAGGED FOR REVIEW with reason "unknown property".

═══════════════════════════════════════════════════
PRE-BUILD CHECK — Reuse Existing Lists (MANDATORY)
═══════════════════════════════════════════════════
CRITICAL: Before building ANY new list, ALWAYS search for existing lists from
PRIOR email campaigns/sends for THIS SAME EVENT. Do NOT create new lists by default.

WORKFLOW:
1. Search for prior campaigns: hubspot_search_campaigns("[event_name]")
   - Look for campaigns that mention this event
   - Note which lists were used as email recipients
2. If no campaigns found, search for emails sent to this event:
   - Query email send history (if available) to identify lists used
   - Campaigns can be deleted but email records remain
3. Identify ALL lists used in prior sends for this event
4. Report findings to user in a structured table:
   | List Name | Size | Last Modified | Used In Campaign/Email | Still Valid? |
5. Ask user to choose: REUSE existing / UPDATE existing / or CREATE new
   - REUSE: Use the existing list as-is for this send
   - UPDATE: CLONE the list first, modify the clone, use the new version
   - CREATE: Only if no suitable prior lists exist OR user explicitly requests new

WHY REUSE?
- Reduces HubSpot portal clutter (same event, same segment = one list, not 10)
- Maintains audit trail (can track list evolution across sends)
- Cleaner list naming: "PyTorch NA 2026 - Newsletter" v2, v3 (cloned versions)
  instead of: "PyTorch NA 2026 - Newsletter", "PyTorch Newsletter 2026 Updated",
  "PyTorch Conf Newsletter (new)", etc.
- Efficiency: one decision per segment per event, not one list per send

WHEN TO CLONE (UPDATE):
If the user wants to modify a prior list but keep the original for reference:
1. Clone the existing list: hubspot_create_list("[original name] (v2 - [reason])", filter)
2. Modify the cloned version based on user request
3. Use the cloned version for the new send
4. Keep original as historical reference

WHEN TO CREATE NEW:
Only if:
- No prior lists found for this event, OR
- User explicitly says "create a new list for this" (not an update/reuse scenario)

Document the decision in the BUILD PLAN: "Reusing [List ID] from [prior send]" or
"Cloning [List ID] and updating based on: [user request]" or "Creating new because: [reason]"

═══════════════════════════════════════════════════
STEP 1 — Query Snowflake for past editions
═══════════════════════════════════════════════════
Use snowflake_query. Derive [event_term], [location_term], [current_year] from the
Segment Plan above — do NOT re-scrape the URL. [location_term] must be THIS event's
own city/region (per RULE 7), not the brand/series name — otherwise this query
matches every country the series has ever run in.

  SELECT DISTINCT EV.EVENT_NAME, EV.EVENT_ID
  FROM ANALYTICS.Silver_Segment.EVENT_REGISTRATIONS AS EV
  WHERE EV.EVENT_NAME ILIKE '%[event_term]%'
    AND EV.EVENT_NAME ILIKE '%[location_term]%'
    AND EV.EVENT_NAME NOT ILIKE '%[current_year]%'
  ORDER BY EV.EVENT_NAME;

Copy the exact EVENT_NAME strings — they are used verbatim as HubSpot filter values.
Every returned EVENT_NAME should refer to THIS event's own location (different past
YEARS of it are expected and fine); if any row clearly names a different city/country,
exclude that row per RULE 7 rather than building a branch for it.

Print the exact SQL you ran before showing its results, so it's auditable.

If snowflake_query errors (connection/key failure) or returns zero rows, you MUST NOT
substitute guessed, remembered, or web-researched event name strings — including values
seen in the Segment Plan above or in existing HubSpot list filters (e.g. communitySeg
snapshots). Those are not guaranteed to match Snowflake's exact EVENT_NAME values and
will silently miscount the list. Instead: skip the UNIFIED_EVENTS past-registrant
list entirely, add it to ## FLAGGED FOR REVIEW with reason "Snowflake unavailable —
exact EVENT_NAME values could not be verified", and continue with the remaining
inclusion lists + master list per RULE 4.

═══════════════════════════════════════════════════
STEP 2 — Look up brand master list ID
═══════════════════════════════════════════════════
Only needed if the plan includes a geographic/regional inclusion list — the brand-master
gate is mandatory there, but is NOT applied to web-visitor lists (Step 4 below).

Use read_reference_file("brand-master-lists.md") to look up the brand key from the plan.
If not found → use hubspot_search_lists("[brand] master") to find it, note the ID.

The past-registrant, Event Registered, and [Region] Event Registrants lists (STEP 4)
all use the fixed portal-wide eventTypeId "6-48984571" — no lookup needed. The
Education Enrolled list (STEP 4) uses the fixed eventTypeId "6-58204655".

── Education topic property investigation (group 4, RULE 9) ──
If the plan includes the Education Enrolled group, call hubspot_get_event_types
once and find the entry for eventTypeId "6-58204655". Inspect its properties
for one that plausibly holds a course/topic/subject name (its name or label
containing something like "course", "topic", "subject", "program",
"curriculum"). If such a property exists, note its exact property name — STEP
4 will add a domain-fit CONTAINS filter on it, using the same nesting as
group 5/7 below. If no such property exists, do NOT skip group 4 and do NOT
silently drop the RULE 9 requirement for it: build it with the existing
country-only filter (a course-level exclusion isn't mechanically possible
without that property) and add a line to ## FLAGGED FOR REVIEW noting that
Education Enrolled could not be domain-filtered because no topic/course
property was found on eventTypeId "6-58204655".

═══════════════════════════════════════════════════
STEP 3 — Print ## BUILD PLAN
═══════════════════════════════════════════════════
Print a numbered plan of EVERY list you will create, derived from the
Inclusion strategy in the Segment Plan. Include:
- List number and name
- Filter type(s)
- Why it's needed
- Anything being SKIPPED and why (including any communitySeg lists found — excluded per policy, not rebuilt)
- For groups 4/5/7: this event's domain bucket (from the plan's Product/
  technology domain line) and, for groups 5/7, which candidate event names
  (or the topic property, for group 4) were kept vs excluded for domain
  mismatch per RULE 9

═══════════════════════════════════════════════════
COMBINING CONDITIONS INTELLIGENTLY — MULTISTRING VALUES
═══════════════════════════════════════════════════
CRITICAL: When building filters with multiple similar values that share the SAME
gates/structure, COMBINE them into a single AND branch using MULTISTRING values
instead of creating separate branches.

EXAMPLE — What NOT to do (inefficient):
  Group 13: AND [jobtitle CONTAINS "microservices", IN_LIST 26716]
  Group 14: AND [jobtitle CONTAINS "solutions architect", IN_LIST 26716]
  (Creates 2 redundant branches with identical structure)

EXAMPLE — What TO do (efficient):
  Group 13: AND [jobtitle CONTAINS ["microservices", "solutions architect"], IN_LIST 26716]
  (Single branch with MULTISTRING values, same logic)

WHEN TO COMBINE:
- Same AND branch structure: identical filter types, operators, and gates
- Only VALUES differ: the property values (e.g., different job titles) are different
- Use MULTISTRING operationType: "values": ["value_1", "value_2", ...] with
  deduplicated, sorted values for deterministic output

WHEN NOT TO COMBINE:
- Different filter structures: e.g., one branch has IN_LIST gate, another doesn't
- Different properties: e.g., one filters "jobtitle", another filters "country"
- Nested structures: UNIFIED_EVENTS with complex filterBranches (keep separate)
- Identifier values: IN_LIST values are list IDs — never combine those

APPLY THIS PATTERN TO:
- Job title / function filters (e.g., "cloud native", "kubernetes", "devops")
- Topic/tag filters (e.g., multiple course topics, event categories)
- Property CONTAINS filters with identical secondary gates
The automatic filter optimizer will catch redundancies you miss, but building
combined filters from the start is cleaner and more efficient.

═══════════════════════════════════════════════════
STEP 4 — Build ALL inclusion lists (one per inclusion source)
═══════════════════════════════════════════════════
Create every list from your BUILD PLAN in order. Use the correct filter type for each:

── UNIFIED_EVENTS (past registrants — group 1) ────────────────
Use for: past-registrant lists (built fresh from Snowflake EVENT_NAME data — never as
a rebuild or replacement of a communitySeg list; see RULE 2).
Uses the SAME portal-wide "Event Registered" eventTypeId "6-48984571" as groups
5 and 7 below — the only difference is the event_name filter inside it (exact
match here, vs a domain-fit-filtered CONTAINS multi-value for groups 5 and 7 —
see RULE 9 and the group 5/7 headers below).
This is the schema HubSpot's own UI produces for this filter (confirmed from a
live reference list) — do NOT use the older BEHAVIORAL_EVENT/HAS_EVENT/filterGroups
shape, which is a different, legacy event system in this portal.
filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [
        {{
          "filterBranchType": "UNIFIED_EVENTS",
          "operator": "HAS_COMPLETED",
          "eventTypeId": "6-48984571",
          "filterBranches": [
            {{
              "filterBranchType": "AND",
              "filterBranches": [],
              "filters": [
                {{
                  "filterType": "PROPERTY",
                  "property": "event_name",
                  "operation": {{"operator": "IS_EQUAL_TO", "includeObjectsWithNoValueSet": false,
                                 "values": ["[exact EVENT_NAME from Snowflake]"], "operationType": "MULTISTRING"}}
                }}
              ]
            }}
          ],
          "filters": []
        }}
      ],
      "filters": []
    }}
  ],
  "filters": []
}}
Add one AND branch per past EVENT_NAME row from STEP 1 — i.e. one per past YEAR of
THIS event's own location, never one per other country/city (per RULE 7). All
branches go inside the top OR.

── PAGE_VIEW (web visitors) ──────────────────────────────────
Use for: web-visitor lists. NO brand-master gate — a page view alone qualifies.
filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{
          "filterType": "PAGE_VIEW",
          "value": "[event URL]",
          "operator": "HAS_VIEWED_URL"
        }}
      ]
    }}
  ],
  "filters": []
}}

── LIST_MEMBERSHIP + brand master (geographic / regional segments) ──
Use for: geographic or regional contact lists. The brand-master gate is MANDATORY
here — a regional filter alone is too broad. Look up the brand master list ID in
Step 2 before building this list.
filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{
          "filterType": "LIST_MEMBERSHIP",
          "listId": "[existing geographic/regional HubSpot list ID as string]",
          "operator": "IN_LIST"
        }},
        {{
          "filterType": "LIST_MEMBERSHIP",
          "listId": "[brand master list ID as string]",
          "operator": "IN_LIST"
        }}
      ]
    }}
  ],
  "filters": []
}}

── LIST_MEMBERSHIP (other existing HubSpot lists) ───────────
Use for: topic/persona lists, newsletter lists already in HubSpot (not geographic/regional
— no brand-master gate needed here).
Use hubspot_search_lists to find the existing list ID first.
filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{
          "filterType": "LIST_MEMBERSHIP",
          "listId": "[existing HubSpot list ID as string]",
          "operator": "IN_LIST"
        }}
      ]
    }}
  ],
  "filters": []
}}

── UNIFIED_EVENTS + PROPERTY (regional expansion — group 4: Education Enrolled) ──
Use for: "Education Enrolled [Country]". Fixed portal-wide eventTypeId
"6-58204655" (do NOT look this up per event). Root is OR of two AND branches
(country, then ip_country) so either property qualifies. [location_term] is
this event's own country (RULE 7/8), e.g. "Korea".
Default filterBranch structure (used when STEP 2 found no topic/course property):
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [
        {{
          "filterBranchType": "UNIFIED_EVENTS",
          "operator": "HAS_COMPLETED",
          "eventTypeId": "6-58204655",
          "filterBranches": [],
          "filters": []
        }}
      ],
      "filters": [
        {{
          "filterType": "PROPERTY",
          "property": "country",
          "operation": {{"operator": "CONTAINS", "includeObjectsWithNoValueSet": false,
                         "values": ["[location_term]"], "operationType": "MULTISTRING"}}
        }}
      ]
    }},
    {{
      "filterBranchType": "AND",
      "filterBranches": [
        {{
          "filterBranchType": "UNIFIED_EVENTS",
          "operator": "HAS_COMPLETED",
          "eventTypeId": "6-58204655",
          "filterBranches": [],
          "filters": []
        }}
      ],
      "filters": [
        {{
          "filterType": "PROPERTY",
          "property": "ip_country",
          "operation": {{"operator": "CONTAINS", "includeObjectsWithNoValueSet": false,
                         "values": ["[location_term]"], "operationType": "MULTISTRING"}}
        }}
      ]
    }}
  ],
  "filters": []
}}
If STEP 2 DID find a topic/course property on eventTypeId "6-58204655", add ONE
domain-fit filter inside EACH UNIFIED_EVENTS node's "filterBranches" (currently
[] above), same nesting pattern as group 5 below — one AND branch with a
"filters" entry using that exact property name, operator "CONTAINS", and
values populated with domain-compatible course/topic keywords per RULE 9.

── UNIFIED_EVENTS + PROPERTY + event_name CONTAINS (regional expansion — group 5: Event Registered) ──
Use for: "Event Registered [Country]". Fixed portal-wide eventTypeId
"6-48984571" (do NOT look this up per event). Root is OR of two AND branches
(country, then ip_country), same as group 4, PLUS a nested event_name CONTAINS
filter inside each UNIFIED_EVENTS node (per RULE 9 — this is the change from
the old "any past event" match).
First, query Snowflake for candidate past EVENT_NAME values in this event's own
country over the last 3 years, across ANY brand/event (no [event_term] filter —
that's what makes this "any past LF event" instead of group 1's own-series
query; the 3-year lookback keeps the candidate set small enough to judge for
domain fit):
  SELECT DISTINCT EV.EVENT_NAME, EV.EVENT_ID
  FROM ANALYTICS.Silver_Segment.EVENT_REGISTRATIONS AS EV
  WHERE EV.EVENT_NAME ILIKE '%[location_term]%'
    AND EV.EVENT_NAME NOT ILIKE '%[current_year]%'
    AND (EV.EVENT_NAME ILIKE '%[current_year - 1]%'
      OR EV.EVENT_NAME ILIKE '%[current_year - 2]%'
      OR EV.EVENT_NAME ILIKE '%[current_year - 3]%')
  ORDER BY EV.EVENT_NAME;
Print the exact SQL you ran before showing its results, same as STEP 1. If this
query fails or returns zero rows, do NOT substitute guessed/remembered event
names (same Snowflake data-integrity rule as STEP 1) — skip group 5 entirely
and add it to ## FLAGGED FOR REVIEW with reason "Snowflake unavailable — exact
EVENT_NAME values for Event Registered could not be verified".
From the returned EVENT_NAME values, apply RULE 9: keep only the ones in the
SAME domain bucket as this event (from the Segment Plan's Product/technology
domain line), preferring similar/adjacent project or technology areas; drop
any from the opposite bucket even if that leaves very few candidates. If NO
candidate EVENT_NAME survives the RULE 9 filter, treat group 5 as N/A for this
event and note why in ## FLAGGED FOR REVIEW rather than building an empty or
unfiltered list.
filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [
        {{
          "filterBranchType": "UNIFIED_EVENTS",
          "operator": "HAS_COMPLETED",
          "eventTypeId": "6-48984571",
          "filterBranches": [
            {{
              "filterBranchType": "AND",
              "filterBranches": [],
              "filters": [
                {{
                  "filterType": "PROPERTY",
                  "property": "event_name",
                  "operation": {{"operator": "CONTAINS", "includeObjectsWithNoValueSet": false,
                                 "values": ["[domain_compatible_event_name_1]", "[domain_compatible_event_name_2]"],
                                 "operationType": "MULTISTRING"}}
                }}
              ]
            }}
          ],
          "filters": []
        }}
      ],
      "filters": [
        {{
          "filterType": "PROPERTY",
          "property": "country",
          "operation": {{"operator": "CONTAINS", "includeObjectsWithNoValueSet": false,
                         "values": ["[location_term]"], "operationType": "MULTISTRING"}}
        }}
      ]
    }},
    {{
      "filterBranchType": "AND",
      "filterBranches": [
        {{
          "filterBranchType": "UNIFIED_EVENTS",
          "operator": "HAS_COMPLETED",
          "eventTypeId": "6-48984571",
          "filterBranches": [
            {{
              "filterBranchType": "AND",
              "filterBranches": [],
              "filters": [
                {{
                  "filterType": "PROPERTY",
                  "property": "event_name",
                  "operation": {{"operator": "CONTAINS", "includeObjectsWithNoValueSet": false,
                                 "values": ["[domain_compatible_event_name_1]", "[domain_compatible_event_name_2]"],
                                 "operationType": "MULTISTRING"}}
                }}
              ]
            }}
          ],
          "filters": []
        }}
      ],
      "filters": [
        {{
          "filterType": "PROPERTY",
          "property": "ip_country",
          "operation": {{"operator": "CONTAINS", "includeObjectsWithNoValueSet": false,
                         "values": ["[location_term]"], "operationType": "MULTISTRING"}}
        }}
      ]
    }}
  ],
  "filters": []
}}

── PAGE_VIEW multi-branch (regional expansion — group 6: Expanded Web Visitors) ──
Use for: "Expanded Web Visitors". [sibling_event_url] is the nearest sibling
regional event's page from the Segment Plan's regional research.
filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{"filterType": "PAGE_VIEW", "operator": "HAS_PAGEVIEW_CONTAINS",
          "pageUrl": "[sibling_event_url]", "enableTracking": false}}
      ]
    }},
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{"filterType": "PAGE_VIEW", "operator": "HAS_PAGEVIEW_CONTAINS",
          "pageUrl": "training.linuxfoundation.org", "enableTracking": false}},
        {{"filterType": "PROPERTY", "property": "country",
          "operation": {{"operator": "CONTAINS", "includeObjectsWithNoValueSet": false,
                         "values": ["[location_term]"], "operationType": "MULTISTRING"}}}}
      ]
    }}
  ],
  "filters": []
}}

── UNIFIED_EVENTS multi-value CONTAINS (regional expansion — group 7: [Region] Event Registrants) ──
Use for: "[Region] Event Registrants". [sibling_event_name_1..N] are the exact
EVENT_NAME / event series names of sibling events found in the Segment Plan's
regional research (one CONTAINS list, not one branch per event).
Per RULE 9, before building, drop any sibling event whose domain bucket
(HARDWARE vs SOFTWARE/AI, from the Segment Plan) does not match this event's
own bucket — even if it's the only sibling event found this cycle; treat that
case as N/A rather than including a bucket mismatch.
filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [
        {{
          "filterBranchType": "UNIFIED_EVENTS",
          "operator": "HAS_COMPLETED",
          "eventTypeId": "6-48984571",
          "filterBranches": [
            {{
              "filterBranchType": "AND",
              "filterBranches": [],
              "filters": [
                {{
                  "filterType": "PROPERTY",
                  "property": "event_name",
                  "operation": {{"operator": "CONTAINS", "includeObjectsWithNoValueSet": false,
                                 "values": ["[sibling_event_name_1]", "[sibling_event_name_2]"],
                                 "operationType": "MULTISTRING"}}
                }}
              ]
            }}
          ],
          "filters": []
        }}
      ],
      "filters": []
    }}
  ],
  "filters": []
}}

After EACH successful hubspot_create_list call, print:
✅ [List name] created — ID: [listId] — [hubspot_url]

Save all created list IDs.

═══════════════════════════════════════════════════
STEP 5 — Look up standard suppression list IDs
═══════════════════════════════════════════════════
Your job here is to FIND suppression list IDs, but you will NOT build them
automatically — user approval is MANDATORY before any suppressions are applied.

After finding all suppressions (standard + event-specific), you will present them in a
structured table and ask the user to EXPLICITLY APPROVE which ones to include in the
Combined Suppression list. Never assume suppressions should be applied — different
events have different strategies (GDPR varies by region, event-specific opt-outs vary,
etc.). The user must have final say.

Every suppression found is combined into ONE "Combined Suppression" list in STEP 5B
(only AFTER user approval), and that single list is then applied as a NOT_IN_LIST
exclusion in each inclusion branch of the master list (STEP 6). Do NOT add the
individual suppression lists into the inclusion groups. They are ALSO reported in the
## SUPPRESSION LISTS section so they can be applied at email send time.

Use hubspot_search_lists to find the current list ID for each standard suppression.
Search by the key term shown — take the most recently updated match.

Standard suppressions to look up:
  "LF Global Opt-Outs"           → LF Global Opt-Outs
  "LF Europe Global Opt-Outs"    → LF Europe Global Opt-Outs
  "LF Events GDPR Suppression"   → most recent quarterly (e.g. 25Q2 - LF Events - GDPR Suppression)
  "LF Europe GDPR Suppression"   → most recent (e.g. 25Q2 - LF Europe - GDPR Suppression)
  "LF Master Exclusion"          → 23Q1 - LF - Master Exclusion List or similar
  "LF Events Suppression List"   → most recent (e.g. 23Q3 - LF Events - Suppression List)

Also look up any event-specific suppressions from the Segment Plan
(current registrants of this event, internal LF contacts, foundation opt-outs, etc.).

── Current-event registrants (MANDATORY — build fresh if no list exists) ──────
This event's OWN registrants (current year) MUST end up in the suppression set —
never in an inclusion branch. First try hubspot_search_lists for an existing
registration list for this event. If none exists (common for a brand-new event),
build it yourself:

  SELECT DISTINCT EV.EVENT_NAME, EV.EVENT_ID
  FROM ANALYTICS.Silver_Segment.EVENT_REGISTRATIONS AS EV
  WHERE EV.EVENT_NAME ILIKE '%[event_term]%'
    AND EV.EVENT_NAME ILIKE '%[location_term]%'
    AND EV.EVENT_NAME ILIKE '%[current_year]%'
  ORDER BY EV.EVENT_NAME;

This is the mirror image of the STEP 1 query (ILIKE the current year instead of
excluding it) — it must return THIS event's own EVENT_NAME, never a past edition's.
Use the exact EVENT_NAME(s) returned to build a UNIFIED_EVENTS list the same way
as a past-registrant list (same filterBranch shape as STEP 4's UNIFIED_EVENTS
past-registrant block), name it "[Quarter] [Year] - [Brand] - [Event Name] - Current Registrants",
and feed its list ID into STEP 5B's combined suppression — do NOT add it to the
master list's inclusion branches. If the query errors or returns zero rows, note it
in ## FLAGGED FOR REVIEW rather than skipping the exclusion silently — a missing
current-registrants suppression means people who already registered could get
re-invited.

Collect ALL found suppression list IDs into one set — they feed STEP 5B (the combined
list) and the ## SUPPRESSION LISTS section. If a search returns no match, note it in
## FLAGGED FOR REVIEW.

═══════════════════════════════════════════════════
STEP 5B — Build the Combined Suppression list (USER APPROVAL REQUIRED)
═══════════════════════════════════════════════════
CRITICAL: Before building the Combined Suppression list, STOP and ask the user to
EXPLICITLY APPROVE which suppression lists to include. Never auto-add suppressions.

Present all found suppression lists in a structured table format:
  | List Name | Size | Include? |
  Suppressions control WHO GETS EXCLUDED from email sends — this is critical business
  logic that must have explicit user approval. Different events have different suppression
  strategies (GDPR varies by region, event-specific opt-outs vary, etc.).

ONLY when the user explicitly approves suppression(s), create ONE dynamic list whose
members are every contact in ANY approved suppression list. This is a pure OR of IN_LIST
membership filters — one AND branch per approved suppression list. STEP 6 references
this single list as the only exclusion, so the suppression set is defined in exactly
ONE place instead of being repeated in every group.

CRITICAL: membership filters MUST use filterType "IN_LIST" (NOT "LIST_MEMBERSHIP",
which HubSpot rejects). The root MUST be "OR" with AND sub-branches.

filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{"filterType": "IN_LIST", "listId": "[suppression_id_1]", "operator": "IN_LIST"}}
      ]
    }},
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{"filterType": "IN_LIST", "listId": "[suppression_id_2]", "operator": "IN_LIST"}}
      ]
    }}
    ... (one AND branch per suppression list found in STEP 5)
  ],
  "filters": []
}}

Name: [Quarter] [Year] - [Brand] - [Event Name] - Combined Suppression
After success print:
✅ Combined Suppression list created — ID: [listId] — [hubspot_url]
Save this ID as [combined_suppression_id] — STEP 6 needs it.

If STEP 5 found NO suppression lists, skip this step (there is nothing to combine) and
note it; STEP 6 then builds a pure OR of inclusions with no exclusion filter.

═══════════════════════════════════════════════════
STEP 6 — Build Master Audience List (MANDATORY — never skip)
═══════════════════════════════════════════════════
THIS STEP IS REQUIRED. You must always execute it, even if only some inclusion lists succeeded.

The master list is an OR of all successfully built inclusion list IDs, with the SINGLE
Combined Suppression list from STEP 5B applied as ONE NOT_IN_LIST exclusion inside each
inclusion branch. Do NOT add the individual suppression lists into the groups — only the
one combined-suppression list ID goes in each branch.
Logically: (inc_1 AND NOT combined_supp) OR (inc_2 AND NOT combined_supp) ...
which equals (inc_1 OR inc_2 ...) AND NOT combined_supp.

This distributed shape is REQUIRED by HubSpot — the root filterBranch MUST be "OR"
with AND sub-branches (HubSpot rejects an AND root and rejects nested OR branches),
and HubSpot exposes no separate list-level exclusion field via the API, so each AND
branch carries the one combined-suppression NOT_IN_LIST filter.

CRITICAL: membership filters MUST use filterType "IN_LIST" (NOT "LIST_MEMBERSHIP",
which HubSpot rejects). operator "IN_LIST" includes; operator "NOT_IN_LIST" excludes.

For each successfully built inclusion list, create ONE AND branch whose filters are:
  • that inclusion list (operator IN_LIST), then
  • the Combined Suppression list from STEP 5B (operator NOT_IN_LIST) — the SAME single
    [combined_suppression_id] in every branch.

filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{"filterType": "IN_LIST", "listId": "[inclusion_id_1]", "operator": "IN_LIST"}},
        {{"filterType": "IN_LIST", "listId": "[combined_suppression_id]", "operator": "NOT_IN_LIST"}}
      ]
    }},
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{"filterType": "IN_LIST", "listId": "[inclusion_id_2]", "operator": "IN_LIST"}},
        {{"filterType": "IN_LIST", "listId": "[combined_suppression_id]", "operator": "NOT_IN_LIST"}}
      ]
    }}
    ... (one AND branch per inclusion list; EACH branch references the SAME single combined_suppression_id)
  ],
  "filters": []
}}

If STEP 5B was skipped (no suppressions), each AND branch contains only its single
inclusion-list filter (a pure OR of inclusions).

Name: follow the recommended master list name from the Segment Plan.
If none given: [Quarter] [Year] - [Brand] - [Event Name] Master (With Opt-In and Filters)

After success print:
🏆 Master list created — ID: [listId] — [hubspot_url]

If this step fails for any reason, print the exact HubSpot error and add it to ## FLAGGED FOR REVIEW.
DO NOT end without attempting to create (or, per RULE 10, update-in-place) the master list.

═══════════════════════════════════════════════════
STEP 7 — Final summary
═══════════════════════════════════════════════════
Print a markdown table of ALL created lists (inclusion lists, the Combined Suppression
list from STEP 5B, and the Master list from STEP 6):

| # | List name | HubSpot ID | Link | Notes |
|---|-----------|------------|------|-------|

Then print a clearly separated section:

## SUPPRESSION LISTS
Add ALL of the following as suppression lists when scheduling the email send in HubSpot:

| List name | HubSpot ID | Link |
|-----------|------------|------|
(one row per suppression found in Step 5)

Then print:
## FLAGGED FOR REVIEW
(skipped communitySeg lists, ambiguous event names, missing IDs, unresolvable filters, etc.)
"""


# ══════════════════════════════════════════════════════════════════════════════
# Custom Request flow — free-form, usually location-based "mailable contacts"
# audiences built for the context of one or more named events, rather than a
# single event's own registrant/master list. Modeled on two live reference
# lists (HubSpot list IDs 29911, 29913 — "Mailable Contacts" for Seoul).
# ══════════════════════════════════════════════════════════════════════════════

CUSTOM_PLANNING_PROMPT_TEMPLATE = """You are an experienced LF email audience strategist.

Plan a CUSTOM HubSpot audience segment from this free-form request. Unlike the
event-URL flow, this is not one event's registrant list — it is usually a
LOCATION-based "mailable contacts" audience built for the CONTEXT of one or more
named events, reusable across whichever of them needs to send mail.

Request:
{request}

Two real, live examples of this exact pattern already exist in HubSpot — use them
as your model, not a hypothetical:
  - "26Q3 - Seoul - Mailable Contacts - OSS Korea + MCP Dev Summit Seoul"
  - "26Q3 - Seoul and South Korea - Mailable Contacts - OSS Korea + MCP Dev Summit Seoul"
Use hubspot_search_lists("[location] mailable") to find the closest existing example
(or one for a different location, if none matches yet), then hubspot_get_list to
inspect its exact filterBranch — confirm property names, operators, and eventTypeIds
still match before proposing anything; do not assume they are frozen.

═══════════════════════════════════════════════════
STEP 1 — Parse the request
═══════════════════════════════════════════════════
- LOCATION(s): the city, and — only if the request clearly implies broader reach
  ("...and South Korea", "...APAC", a country named alongside the city) — the
  country/region too. Default to city-only (the narrower scope) when in doubt;
  note the choice and let the user widen it in review rather than guessing broad.
- NAMED EVENT(s): contextual only — they explain WHY this audience is being built
  and feed the list name. Do NOT filter to only past registrants of these specific
  events unless the request explicitly says so (e.g. "only people who registered
  for X") — the proven pattern is a broader location audience, not an attendee list.
- FOUNDATION / BRAND: derive from the named event(s) via
  read_reference_file("brand-master-lists.md") (e.g. Open Source Summit / MCP Dev
  Summit → brand key "lf", master list 26716). This determines the master-list gate.

═══════════════════════════════════════════════════
STEP 2 — Confirm the filter shape against a live reference
═══════════════════════════════════════════════════
From the reference list you inspected above, confirm:
- Contact-property branches (city / ip_city, plus country_dropdown / ip_country if
  the scope is broad) are gated by IN_LIST on the brand master list — mandatory,
  since these are regional/geographic contact-property filters.
- Event-history branches (UNIFIED_EVENTS on event_city / user_city, or
  event_country / user_country if broad) use the fixed portal-wide eventTypeIds
  "6-48984571" (Event Registered — completion of ANY past event) and "6-58204655"
  (Education Enrolled). In the reference pattern these do NOT carry the master-list
  gate (they're behavioral/event data, not a geographic contact-property filter).

── Education topic/brand-fit investigation (mandatory, not optional) ──
If the plan includes the Education Enrolled event-history branch (eventTypeId
"6-58204655"), call hubspot_get_event_types once and find that eventTypeId's
properties for one that plausibly holds a course/topic/subject name (its name
or label containing something like "course", "topic", "subject", "program",
"curriculum"). If such a property exists, note its exact property name — the
build phase will add a domain-fit CONTAINS filter on it, using the FOUNDATION/
BRAND resolved in STEP 1 (e.g. brand "cncf" → keywords like "Kubernetes",
"Cloud Native", "CNCF") so the Education Enrolled branch only counts enrollment
in THIS brand's own courses, not any LFX Education course enrollment broadly.
If no such property exists, do NOT silently drop this requirement: build the
branch with the existing city/country filter only, and add a line under "Open
questions / flags" noting Education Enrolled could not be brand-scoped because
no topic/course property was found on eventTypeId "6-58204655".

═══════════════════════════════════════════════════
STEP 3 — Flag the mailability gap for the user to decide
═══════════════════════════════════════════════════
The reference lists are named "Mailable Contacts" but their event-history branches
are not gated by the brand master list — so someone who registered for a past event
in this location but was never in the master list (no opt-in, or later suppressed)
could still be pulled in through those branches alone. Surface this explicitly under
"Open questions / flags" and ask the user to pick:
  (a) Match the reference pattern exactly — proven, faster, but not 100% opt-in-gated.
  (b) Add the master-list IN_LIST gate to the event-history branches too, for a
      stricter definition of "mailable".
Do not choose silently.

═══════════════════════════════════════════════════
STEP 4 — Suppressions
═══════════════════════════════════════════════════
This audience isn't tied to one upcoming event, so there is no "current registrants"
exclusion to build (that's specific to the event-URL flow). Still ask whether to
apply the standard hygiene suppressions (LF Global Opt-Outs, LF Events GDPR
Suppression if EU-adjacent, 23Q1 LF Master Exclusion List) via a combined
NOT_IN_LIST exclusion, or to leave them off to match the reference pattern exactly
(neither 29911 nor 29913 has any). Ask — don't assume.

Flag any communitySeg / community_seg lists found along the way. They are retired —
exclude them entirely; never rebuild or reuse their logic.

═══════════════════════════════════════════════════
STEP 5 — Produce the Segment Plan Report
═══════════════════════════════════════════════════
Write a complete structured report using this format:

### 📋 Custom Audience Plan: [short description]

**Request summary** — what was asked, in one sentence.
**Purpose / named events** — event(s) this audience will be used to mail; context only.
**Location scope** — city (and country/region if broad), with reasoning for the choice.
**Brand / master-list gate** — brand key + master list ID (from brand-master-lists.md).
**Reference list inspected** — name + ID of the closest existing example you found.
**Proposed list(s)** — name(s), and for each a filter-branch sketch:
  - contact-property branches (gated by the master list)
  - event-history branches (UNIFIED_EVENTS, gated per the STEP 3 decision;
    Education Enrolled additionally scoped to this brand's own courses via the
    STEP 2 topic/brand-fit investigation, when a topic/course property was found)
**Mailability gap decision** — (a) or (b) from STEP 3, pending the user's answer.
**Suppression decision** — apply hygiene suppressions, or match the reference (none) — pending the user's answer.
**Estimated list size** — the closest example list's size as a ballpark, if found.
**communitySeg lists** — list each one found and confirm it is excluded from this plan.
**Open questions / flags** — anything else to confirm before building.

If any open question is genuinely blocking, ALSO call the present_open_questions
tool with one entry per blocking question (question text, why it blocks, and a
short list of selectable options) so the user can answer via the UI instead of
free text. Call it once, after finishing the rest of this plan output, and stop
your turn immediately after — do not keep narrating past it.

End with: "Ready to proceed? Say yes and I'll build this list in HubSpot."
"""


def build_custom_planning_prompt(request_text: str, qa: str = "") -> str:
    prompt = CUSTOM_PLANNING_PROMPT_TEMPLATE.format(request=request_text)
    if qa:
        prompt += (
            f"\n\nThe user has already answered these clarifying questions from a prior "
            f"planning pass — incorporate the answers directly, do not ask them again:\n{qa}\n"
        )
    return prompt


CUSTOM_BUILDING_PROMPT = """Build the CUSTOM HubSpot audience list(s) from this approved plan.

Original request: {request}

The planning phase is COMPLETE — use the plan below, including its answers to the
mailability-gap and suppression questions. Do NOT re-parse the request from scratch.

--- SEGMENT PLAN ---
{plan}
--- END SEGMENT PLAN ---
{qa_section}
═══════════════════════════════════════════════════
CRITICAL RULES (enforce throughout all steps)
═══════════════════════════════════════════════════
RULE 1 — communitySeg lists MUST NEVER be used, referenced, or rebuilt. Skip any
  found and add to ## FLAGGED FOR REVIEW with reason "communitySeg — excluded per policy".
RULE 2 — Print ## BUILD PLAN before creating anything in HubSpot. Number each list,
  its filter shape, and why.
RULE 3 — After EVERY successful hubspot_create_list call print:
  ✅ [List name] created — ID: [listId] — [hubspot_url]
  (see RULE 6 for the update-in-place case, which prints a different line)
RULE 4 — Membership filters MUST use filterType "IN_LIST" (never "LIST_MEMBERSHIP",
  which HubSpot rejects). The root filterBranch MUST be "OR" with AND sub-branches
  (HubSpot rejects an AND root and rejects nested OR branches).
RULE 5 — If unsure about anything → skip and add to ## FLAGGED FOR REVIEW rather than guessing.
RULE 6 — REUSE, DON'T DUPLICATE. Before calling hubspot_create_list for STEP 1's
  list(s) or STEP 2's Combined Suppression list, call hubspot_search_lists with the
  exact intended name FIRST. If a list with that EXACT name already exists — this
  request is being rebuilt after an earlier run — call hubspot_update_list_filters on
  its existing ID instead of creating a duplicate, and print
  🔁 [List name] updated in place — ID: [listId] — [hubspot_url]
  instead of the RULE 3 "created" line. Only call hubspot_create_list when no
  exact-name match is found.
RULE 7 — USER-ADDED FILTERS. If the Segment Plan below contains a
  "## USER-ADDED FILTERS" section, each line there is an extra condition the user
  typed in during plan review (e.g. Property "job_title" contains "director"). Add
  EVERY listed condition as an additional PROPERTY filter inside EACH AND branch of
  STEP 1's list(s) (ANDed with that branch's existing filters). Translate the
  plain-English operator to the matching HubSpot PROPERTY operation: "is equal to"
  → IS_EQUAL_TO, "contains" → CONTAINS_TOKEN, "is any of" → IS_ANY_OF, "is not any
  of" → NOT_ANY_OF, "is known" → HAS_PROPERTY (no value), "is unknown" →
  NOT_HAS_PROPERTY (no value); operationType "MULTISTRING" unless the property is a
  HubSpot enumeration property, in which case use "ENUMERATION". Never apply to the
  Combined Suppression list. If a listed property name isn't a real HubSpot contact
  property, do NOT guess a similar-sounding one — skip it and add to
  ## FLAGGED FOR REVIEW with reason "unknown property".

RULE 8 — COMBINE CONDITIONS INTELLIGENTLY. When building filters with multiple similar
  property values that share the SAME AND branch structure, COMBINE them using MULTISTRING
  operationType instead of creating separate AND branches. Example: if building a custom
  list for "Cloud Native job functions", combine all job titles into ONE branch:
    [PROPERTY jobtitle CONTAINS ["cloud native", "kubernetes", "devops", ...], IN_LIST master]
  NOT separate branches like:
    [PROPERTY jobtitle="cloud native", IN_LIST master] OR [PROPERTY jobtitle="kubernetes", IN_LIST master]
  This reduces redundancy, improves efficiency, and is automatically optimized anyway.
  Apply this pattern to job titles, topics, tags, and any multi-value PROPERTY filters
  that share identical secondary gates (IN_LIST, location filters, etc.).

═══════════════════════════════════════════════════
PRE-BUILD CHECK — Reuse Existing Lists (MANDATORY)
═══════════════════════════════════════════════════
CRITICAL: Before building ANY new list, ALWAYS search for existing lists that could
be reused or updated. Do NOT create new lists by default — this is especially important
for location-based custom audiences that may be used across multiple events.

WORKFLOW:
1. Search HubSpot for similar lists using:
   - hubspot_search_lists("[location]") — find location-based audiences
   - hubspot_search_lists("[audience type]") — find by function (mailable contacts, etc.)
   - Look for prior campaigns mentioning this location
   - Check email send history for this location (campaigns may be deleted)
2. Identify ALL lists that have been used for this location/audience type before
3. Report findings in a structured table:
   | List Name | Size | Last Modified | Used In Campaign/Email | Reusable? |
4. Ask user to choose:
   - REUSE: Use existing list as-is for current request
   - UPDATE: Clone the list, modify the clone, use new version
   - CREATE: Only if no suitable lists exist OR user explicitly requests new

WHEN TO REUSE:
- If an existing list matches the current request scope (e.g., prior "Seoul - Mailable
  Contacts" list can be reused for a new event targeting Seoul)
- If the audience definition hasn't changed

WHEN TO UPDATE (Clone + Modify):
- If the existing list is 80% right but needs adjustments (add/remove a location,
  adjust eligibility criteria, different suppression scope)
- Clone first, modify the clone, keep original as historical reference
- Clone naming: "[original name] (v2 - [reason])" or "[original name] (updated [date])"

WHEN TO CREATE:
- Only if no prior lists exist for this location/audience type, OR
- User explicitly requests a new list (not a reuse/update scenario)

Document the decision in the BUILD PLAN: "Reusing [List ID] from [context]" or
"Cloning [List ID] and updating: [changes]" or "Creating new because: [reason]"

═══════════════════════════════════════════════════
STEP 1 — Build the primary location + event-history list
═══════════════════════════════════════════════════
One dynamic list per variant the plan proposed (usually one; build two only if the
plan explicitly proposed a narrow + broad pair). Root filterBranch is OR of AND
branches — one branch per source the plan approved:

── Contact-property branches (city / ip_city, +country if broad) — gated ──
{{
  "filterBranchType": "AND",
  "filterBranches": [],
  "filters": [
    {{"filterType": "PROPERTY", "property": "city", "operation": {{"operator": "IS_EQUAL_TO",
       "includeObjectsWithNoValueSet": false, "values": ["[city]"], "operationType": "MULTISTRING"}}}},
    {{"filterType": "IN_LIST", "listId": "[master_list_id]", "operator": "IN_LIST"}}
  ]
}}
Repeat this branch shape with property "ip_city" (same value). If the plan's scope
is broad, add two more branches the same way with property "country_dropdown"
(operator "IS_ANY_OF", operationType "ENUMERATION") and "ip_country" (operator
"IS_EQUAL_TO", operationType "MULTISTRING") — all four gated by the same
[master_list_id] IN_LIST filter.

── Event-history branches (UNIFIED_EVENTS) — gated per the plan's STEP 3 decision ──
{{
  "filterBranchType": "AND",
  "filterBranches": [
    {{
      "filterBranchType": "UNIFIED_EVENTS",
      "operator": "HAS_COMPLETED",
      "eventTypeId": "6-48984571",
      "filterBranches": [],
      "filters": [
        {{"filterType": "PROPERTY", "property": "event_city", "operation": {{"operator": "IS_EQUAL_TO",
           "includeObjectsWithNoValueSet": false, "values": ["[city]"], "operationType": "MULTISTRING"}}}}
      ]
    }}
  ],
  "filters": []
}}
If the plan's mailability decision was (b), add
{{"filterType": "IN_LIST", "listId": "[master_list_id]", "operator": "IN_LIST"}}
to this branch's "filters" array (sibling to the UNIFIED_EVENTS sub-branch, same
level as the empty [] shown above) — if (a), leave "filters" empty as shown.
Repeat this branch shape with property "user_city" + eventTypeId "6-58204655"
(Education Enrolled). If the plan's scope is broad, add the "event_country" /
"user_country" equivalents using the country value — match the exact case used in
the reference list you inspected (these properties can be case-sensitive).

── Brand-fit filter on the Education Enrolled (6-58204655) branch ──
If the plan's STEP 2 topic/brand-fit investigation found a course/topic property
on eventTypeId "6-58204655", add ONE domain-fit filter inside THAT branch's
UNIFIED_EVENTS node's "filterBranches" (currently [] in the shape above) — one
AND branch with a "filters" entry using that exact property name, operator
"CONTAINS", and values populated with domain-compatible course/topic keywords
for the plan's FOUNDATION/BRAND (from STEP 1 of the plan). This keeps the
Education Enrolled branch scoped to enrollments in THIS brand's own courses,
not any LFX Education course. If the plan's STEP 2 investigation found no such
property, leave this branch's "filterBranches" empty (city/country filter only)
— this should already be flagged under ## FLAGGED FOR REVIEW per the plan.

Name each list per the plan's "Proposed list(s)" section (e.g. "[Quarter] [Year] -
[Location] - Mailable Contacts - [named events]").

═══════════════════════════════════════════════════
STEP 2 — Suppressions (only if the plan's Suppression decision says to apply them)
═══════════════════════════════════════════════════
If the plan said to leave suppressions off (matching the reference pattern), skip
this step — STEP 1's list is the final deliverable as built.
If the plan said to apply hygiene suppressions: use hubspot_search_lists to find
each one, combine them into one "[Quarter] [Year] - [Location] - Mailable Contacts
- Combined Suppression" list (OR of AND branches, one IN_LIST filter per
suppression — same shape as RULE 4), then call hubspot_update_list_filters on
STEP 1's list to add a NOT_IN_LIST filter on this combined suppression list to
every AND branch.

═══════════════════════════════════════════════════
STEP 3 — Final summary
═══════════════════════════════════════════════════
Print a markdown table of every list created:

| # | List name | HubSpot ID | Link | Notes |
|---|-----------|------------|------|-------|

Then print:
## FLAGGED FOR REVIEW
(skipped communitySeg lists, ambiguous locations, missing IDs, unresolvable filters, etc.)
"""


# ══════════════════════════════════════════════════════════════════════════════
# Agent loop — routed entirely through llm_gateway (single deterministic path).
# The former OpenAI-SDK client + model helpers were removed; the gateway owns the
# backend choice, model, and sampling params.
# ══════════════════════════════════════════════════════════════════════════════

def _run_agent(prompt: str, q: queue.Queue) -> None:
    """Agentic loop via the unified deterministic gateway. Streams output to `q`
    in the same shape the SSE consumer expects; identical behavior on any backend."""
    log.info(f"[AGENT] starting — backend={llm_gateway.backend_name()!r} "
             f"model={llm_gateway.resolve_model()!r} prompt_len={len(prompt)}")
    q.put({"type": "output", "text": f"🚀 Starting agent (backend={llm_gateway.backend_name()})…"})

    # Ground-truth list IDs, captured directly from each hubspot_create_list (or,
    # per RULE 10/RULE 6 reuse-check, hubspot_update_list_filters) tool result —
    # not parsed from the model's free-text narration, which can misreport the ID
    # it just printed. RULE 4 in the building prompt guarantees the master list is
    # always the LAST list touched, so the last entry here is unambiguously the
    # master list — whether it was freshly created or updated in place on a rebuild.
    created_lists: list[dict] = []

    def _execute_and_track(name: str, tool_input: dict) -> str:
        result_json = _audience_execute(name, tool_input)
        if name in ("hubspot_create_list", "hubspot_update_list_filters"):
            try:
                parsed = json.loads(result_json)
                if parsed.get("listId"):
                    created_lists.append(parsed)
            except Exception:
                pass
        return result_json

    def _on_event(ev: dict) -> None:
        etype = ev.get("type")
        if etype == "output":
            for line in (ev.get("text") or "").splitlines():
                if line.strip():
                    q.put({"type": "output", "text": line})
        elif etype == "output_delta":
            # Partial streamed chunk — pushed raw (not line-split) so words/sentences
            # aren't mangled; tagged `delta` so the frontend doesn't force a newline.
            text = ev.get("text") or ""
            if text:
                q.put({"type": "output", "text": text, "delta": True})
        elif etype == "tool":
            name = ev.get("name")
            if name == "present_open_questions":
                questions = (ev.get("input") or {}).get("questions", [])
                q.put({"type": "output", "text": f"❓ {len(questions)} open question(s) — see selection above"})
                q.put({"type": "question", "questions": questions})
            elif name == "snowflake_query":
                q.put({"type": "output", "text": f"🔧 {name}:\n{ev.get('input', {}).get('sql', '')}"})
            else:
                q.put({"type": "output",
                       "text": f"🔧 {name}({json.dumps(ev.get('input', {}))[:100]})"})
        elif etype == "tool_result":
            q.put({"type": "output", "text": f"   ↳ {str(ev.get('text',''))[:200]}"})

    try:
        llm_gateway.run_agent(
            [{"role": "user", "content": prompt}],
            system=AUDIENCE_SYSTEM,
            tools=AUDIENCE_TOOLS,
            execute_tool=_execute_and_track,
            max_tokens=32000,
            max_steps=40,        # audience builds issue many tool calls (snowflake + N lists)
            on_event=_on_event,
        )
        log.info("[AGENT] done")
        master_list_id = created_lists[-1]["listId"] if created_lists else None
        q.put({"type": "done", "done": True, "success": True, "master_list_id": master_list_id})
    except Exception as exc:
        log.error(f"[AGENT] fatal error: {exc}", exc_info=True)
        q.put({"type": "output", "text": f"❌ Agent error: {exc}"})
        master_list_id = created_lists[-1]["listId"] if created_lists else None
        q.put({"type": "done", "done": True, "success": False, "master_list_id": master_list_id})


# The former SKILL.md/Chrome CLI fallback (_cli_run) was removed. In CLI mode the
# gateway now drives the local Python tools (snowflake_query, hubspot_create_list)
# via the tool protocol — so it needs neither a browser nor the HubSpot MCP.


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def start_plan_job(event_url: str, prescraped: dict | None = None, qa: str = "") -> str:
    """Phase 1 — start segment planning job. Returns job_id for SSE polling.
    Always routes through the deterministic gateway (SDK or CLI, chosen inside it).

    `prescraped` — event data already scraped during the Email Content stage
    (session.meta["url_data"]). When present, the planning agent reuses it
    instead of re-fetching the event page.

    `qa` — answers to clarifying questions from a prior planning pass (see
    present_open_questions); folded into the prompt so this pass doesn't ask again."""
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    log.info(f"[AUDIENCE] plan job {job_id[:8]} — backend={llm_gateway.backend_name()!r} — url={event_url!r} reuse_scrape={bool(prescraped)}")
    prompt = build_planning_prompt(event_url, prescraped, qa=qa)
    threading.Thread(target=_run_agent, args=(prompt, q), daemon=True).start()
    return job_id


def start_build_job(event_url: str, plan: str = "", qa: str = "", prescraped: dict | None = None) -> str:
    """
    Start audience list building. Returns job_id for SSE polling.
    Always routes through the deterministic gateway (SDK or CLI, chosen inside it).

    - plan provided  → Phase 2 only (building from existing plan)
    - plan empty     → Phase 1 + Phase 2 chained automatically in one job

    `prescraped` — event data already scraped during the Email Content stage;
    reused by Phase 1 planning instead of re-fetching the event page.
    """
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    if plan:
        log.info(f"[AUDIENCE] build job {job_id[:8]} — Phase 2 only (plan provided, {len(plan)} chars) "
                 f"— backend={llm_gateway.backend_name()!r}")
        qa_section = f"\nUser answers to clarifying questions:\n{qa}\n" if qa else ""
        prompt = BUILDING_PROMPT.format(url=event_url, plan=plan, qa_section=qa_section)
        threading.Thread(target=_run_agent, args=(prompt, q), daemon=True).start()
    else:
        log.info(f"[AUDIENCE] build job {job_id[:8]} — two-phase (no plan provided) — url={event_url!r} "
                 f"reuse_scrape={bool(prescraped)} — backend={llm_gateway.backend_name()!r}")
        threading.Thread(target=_run_two_phase, args=(event_url, qa, q, prescraped), daemon=True).start()
    return job_id


def _run_two_phase(event_url: str, qa: str, q: queue.Queue, prescraped: dict | None = None) -> None:
    """
    Run PLANNING_PROMPT then BUILDING_PROMPT in sequence within a single job.
    Phase 1 output is captured and passed as {plan} to Phase 2.
    All output lines are forwarded to q; done=True is only emitted at the end.
    """
    # ── Phase 1: planning ────────────────────────────────────────────────────
    log.info("[AUDIENCE] two-phase: starting Phase 1 (planning)")
    if prescraped:
        q.put({"type": "output", "text": "═══ Phase 1: Segment Planning (reusing already-scraped event data) ═══"})
    else:
        q.put({"type": "output", "text": "═══ Phase 1: Segment Planning ═══"})
    plan_q: queue.Queue = queue.Queue()
    plan_prompt = build_planning_prompt(event_url, prescraped)
    threading.Thread(target=_run_agent, args=(plan_prompt, plan_q), daemon=True).start()

    plan_lines: list[str] = []
    plan_success = False
    while True:
        item = plan_q.get()
        if item.get("type") == "output":
            plan_lines.append(item.get("text", ""))
            q.put(item)          # stream planning output to UI
        elif item.get("done"):
            plan_success = item.get("success", False)
            log.info(f"[AUDIENCE] Phase 1 done — success={plan_success} lines={len(plan_lines)}")
            break                # do NOT forward done — continue to phase 2

    if not plan_success:
        log.warning("[AUDIENCE] Phase 1 failed — aborting two-phase job")
        q.put({"type": "output", "text": "⚠ Planning phase failed — cannot continue to building."})
        q.put({"type": "done", "done": True, "success": False})
        return

    # ── Phase 2: building ────────────────────────────────────────────────────
    log.info(f"[AUDIENCE] two-phase: starting Phase 2 (building) with plan={len(plan_lines)} lines")
    q.put({"type": "output", "text": "\n═══ Phase 2: Building HubSpot Lists ═══"})
    plan_text = "\n".join(plan_lines)
    qa_section = f"\nUser answers to clarifying questions:\n{qa}\n" if qa else ""
    build_prompt = BUILDING_PROMPT.format(url=event_url, plan=plan_text, qa_section=qa_section)
    _run_agent(build_prompt, q)   # puts done=True when building completes
    log.info("[AUDIENCE] two-phase: Phase 2 complete")


def start_custom_plan_job(request_text: str, qa: str = "") -> str:
    """Custom Request flow — Phase 1. Free-form location/context description
    instead of an event URL. Returns job_id for SSE polling.

    `qa` — answers to clarifying questions from a prior planning pass (see
    present_open_questions); folded into the prompt so this pass doesn't ask again."""
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    log.info(f"[AUDIENCE] custom plan job {job_id[:8]} — backend={llm_gateway.backend_name()!r} "
             f"request={request_text[:80]!r}")
    prompt = build_custom_planning_prompt(request_text, qa=qa)
    threading.Thread(target=_run_agent, args=(prompt, q), daemon=True).start()
    return job_id


def start_custom_build_job(request_text: str, plan: str = "", qa: str = "") -> str:
    """
    Custom Request flow — start list building. Returns job_id for SSE polling.

    - plan provided  → Phase 2 only (building from existing plan)
    - plan empty     → Phase 1 + Phase 2 chained automatically in one job
    """
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    if plan:
        log.info(f"[AUDIENCE] custom build job {job_id[:8]} — Phase 2 only (plan provided, {len(plan)} chars) "
                 f"— backend={llm_gateway.backend_name()!r}")
        qa_section = f"\nUser answers to clarifying questions:\n{qa}\n" if qa else ""
        prompt = CUSTOM_BUILDING_PROMPT.format(request=request_text, plan=plan, qa_section=qa_section)
        threading.Thread(target=_run_agent, args=(prompt, q), daemon=True).start()
    else:
        log.info(f"[AUDIENCE] custom build job {job_id[:8]} — two-phase (no plan provided) "
                 f"— backend={llm_gateway.backend_name()!r}")
        threading.Thread(target=_run_custom_two_phase, args=(request_text, qa, q), daemon=True).start()
    return job_id


def _run_custom_two_phase(request_text: str, qa: str, q: queue.Queue) -> None:
    """
    Run CUSTOM_PLANNING_PROMPT then CUSTOM_BUILDING_PROMPT in sequence within a
    single job. Phase 1 output is captured and passed as {plan} to Phase 2.
    """
    log.info("[AUDIENCE] custom two-phase: starting Phase 1 (planning)")
    q.put({"type": "output", "text": "═══ Phase 1: Segment Planning ═══"})
    plan_q: queue.Queue = queue.Queue()
    plan_prompt = build_custom_planning_prompt(request_text)
    threading.Thread(target=_run_agent, args=(plan_prompt, plan_q), daemon=True).start()

    plan_lines: list[str] = []
    plan_success = False
    while True:
        item = plan_q.get()
        if item.get("type") == "output":
            plan_lines.append(item.get("text", ""))
            q.put(item)          # stream planning output to UI
        elif item.get("done"):
            plan_success = item.get("success", False)
            log.info(f"[AUDIENCE] custom Phase 1 done — success={plan_success} lines={len(plan_lines)}")
            break                # do NOT forward done — continue to phase 2

    if not plan_success:
        log.warning("[AUDIENCE] custom Phase 1 failed — aborting two-phase job")
        q.put({"type": "output", "text": "⚠ Planning phase failed — cannot continue to building."})
        q.put({"type": "done", "done": True, "success": False})
        return

    log.info(f"[AUDIENCE] custom two-phase: starting Phase 2 (building) with plan={len(plan_lines)} lines")
    q.put({"type": "output", "text": "\n═══ Phase 2: Building HubSpot Lists ═══"})
    plan_text = "\n".join(plan_lines)
    qa_section = f"\nUser answers to clarifying questions:\n{qa}\n" if qa else ""
    build_prompt = CUSTOM_BUILDING_PROMPT.format(request=request_text, plan=plan_text, qa_section=qa_section)
    _run_agent(build_prompt, q)   # puts done=True when building completes
    log.info("[AUDIENCE] custom two-phase: Phase 2 complete")


def get_job_queue(job_id: str) -> queue.Queue | None:
    return _jobs.get(job_id)


def remove_job(job_id: str) -> None:
    _jobs.pop(job_id, None)


def extract_master_list_id(text: str) -> str:
    """
    Parse the master list ID from accumulated agent output.
    Handles output from both the lf-event-studio agent (🏆 pattern) and
    the Claude CLI fallback (MASTER_LIST_ID: pattern + various prose formats).
    """
    # lf-event-studio: "🏆 Master list created — ID: 12345 — https://..."
    m = re.search(r"🏆[^\n]*?ID:\s*(\d+)", text)
    if m:
        return m.group(1)

    # RULE 10/RULE 6 reuse-check: "🔁 [Master list name] updated in place — ID: 12345 — https://..."
    m = re.search(r"(?i)🔁[^\n]*?master[^\n]*?ID:\s*(\d+)", text)
    if m:
        return m.group(1)

    # CLI explicit marker: "MASTER_LIST_ID: 12345"
    m = re.search(r"MASTER_LIST_ID:\s*(\d+)", text)
    if m:
        return m.group(1)

    # HubSpot list URLs — both objectLists and contacts/<portal>/lists/ formats
    for pat in [
        r"(?i)master[^\n]{0,400}objectLists/(\d+)",
        r"(?i)objectLists/(\d+)[^\n]{0,400}master",
        r"(?i)master[^\n]{0,400}/lists/(\d+)",
        r"(?i)/lists/(\d+)[^\n]{0,400}master",
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1)

    # Prose patterns: "Master Audience list — ID: 12345" / "listId: 12345" near "master"
    for pat in [
        r"[Mm]aster[^\n]{0,80}[Ii][Dd][:\s]+(\d{4,8})",
        r"[Mm]aster [Aa]udience[^\n]{0,80}\b(\d{5,8})\b",
        r"[Mm]aster[^\n]{0,80}[Ll]ist[^\n]{0,80}\b(\d{5,8})\b",
        r"listId[\"']?\s*:\s*[\"']?(\d{4,8})[\"']?[^\n]{0,200}[Mm]aster",
        r"[Mm]aster[^\n]{0,200}listId[\"']?\s*:\s*[\"']?(\d{4,8})",
        r"[Mm]aster[^\n]{0,200}list[_ ]id[\"']?\s*[:=]\s*[\"']?(\d{4,8})",
        r"[Cc]reated[^\n]{0,80}[Mm]aster[^\n]{0,80}\b(\d{5,8})\b",
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1)

    # Last resort: master is always built last — take the final list ID seen in output
    all_ids = re.findall(r"(?:objectLists|/lists)/(\d+)", text)
    if all_ids:
        return all_ids[-1]
    return ""


def extract_suppression_lists(text: str) -> list:
    """
    Parse the ## SUPPRESSION LISTS section from build output.
    Returns list of dicts: [{name, list_id, url}, ...].
    """
    section_m = re.search(
        r"##\s*SUPPRESSION LISTS(.*?)(?:##\s*FLAGGED FOR REVIEW|$)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_m:
        return []
    section = section_m.group(1)
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) >= 2 and cols[0] and cols[0].lower() not in ("list name", "name"):
            rows.append({
                "name":    cols[0],
                "list_id": cols[1],
                "url":     cols[2] if len(cols) > 2 else "",
            })
    return rows
