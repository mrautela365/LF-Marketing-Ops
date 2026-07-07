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
    return {
        "query": query,
        "results": [
            {"listId": l.get("listId"), "name": l.get("name"), "size": l.get("size")}
            for l in lists
        ],
    }


def hubspot_get_list(list_id: str) -> dict:
    """Get a HubSpot contact list including its filter branch."""
    url = f"{_HS_BASE}/crm/v3/lists/{list_id}"
    r = requests.get(url, headers=_hs_headers(), params={"includeFilters": "true"}, timeout=15)
    r.raise_for_status()
    return r.json()


def hubspot_create_list(name: str, filter_branch: dict) -> dict:
    """Create a new dynamic HubSpot contact list."""
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
        f"https://app.hubspot.com/contacts/{HUBSPOT_PORTAL_ID}/lists/{list_id}"
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
    url = f"{_HS_BASE}/crm/v3/lists/{list_id}/filter-branch"
    r = requests.put(url, headers=_hs_headers(), json={"filterBranch": filter_branch}, timeout=15)
    if not r.ok:
        raise RuntimeError(f"HubSpot {r.status_code}: {r.text[:500]}")
    hs_url = f"https://app.hubspot.com/contacts/{HUBSPOT_PORTAL_ID}/lists/{list_id}"
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
        "Search HubSpot marketing emails by keyword (name or subject). Use to find prior sends for an event.",
        {"query": {"type": "string", "description": "Search keyword, e.g. 'KubeCon North America 2025'"}},
        ["query"]),

    _fn("hubspot_search_lists",
        "Search HubSpot contact lists by name keyword.",
        {"query": {"type": "string", "description": "List name keyword to search"}},
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
}

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
     note above); N/A only if the foundation has no LF Education presence
  5. Event Registered [Country] — standard regional-expansion group; any past LF
     event registration, gated by this event's own country
  6. Expanded Web Visitors — standard regional-expansion group; nearest sibling
     regional event's page OR training.linuxfoundation.org + this event's country
  7. [Region] Event Registrants — standard regional-expansion group; registrants
     of sibling events in the same broader region this cycle; N/A only if none found
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

Derive the short name / slug and event type from the above. Do NOT call web_fetch for
this URL — it has already been scraped and re-fetching would waste a step. Only fall
back to web_fetch if a detail you need is genuinely missing from the data above.
"""


def build_planning_prompt(url: str, prescraped: dict | None = None) -> str:
    step1 = _format_prescraped_step1(prescraped) if prescraped else _STEP1_SCRAPE
    return PLANNING_PROMPT_TEMPLATE.format(url=url, step1=step1)


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

RULE 4 — MASTER LIST IS MANDATORY. You MUST always build the master list as the final step.
  Even if some inclusion lists failed, build the master from whatever IDs you DO have.
  Never end without creating the master list. It is the primary deliverable.

RULE 5 — After EVERY successful hubspot_create_list call print:
  ✅ [List name] created — ID: [listId] — [hubspot_url]

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

═══════════════════════════════════════════════════
STEP 3 — Print ## BUILD PLAN
═══════════════════════════════════════════════════
Print a numbered plan of EVERY list you will create, derived from the
Inclusion strategy in the Segment Plan. Include:
- List number and name
- Filter type(s)
- Why it's needed
- Anything being SKIPPED and why (including any communitySeg lists found — excluded per policy, not rebuilt)

═══════════════════════════════════════════════════
STEP 4 — Build ALL inclusion lists (one per inclusion source)
═══════════════════════════════════════════════════
Create every list from your BUILD PLAN in order. Use the correct filter type for each:

── UNIFIED_EVENTS (past registrants — group 1) ────────────────
Use for: past-registrant lists (built fresh from Snowflake EVENT_NAME data — never as
a rebuild or replacement of a communitySeg list; see RULE 2).
Uses the SAME portal-wide "Event Registered" eventTypeId "6-48984571" as groups
5 and 7 below — the only difference is the event_name filter inside it (exact
match here, vs no filter for group 5 and CONTAINS multi-value for group 7).
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

── UNIFIED_EVENTS + PROPERTY (regional expansion — groups 4 & 5) ────
Use for: "Education Enrolled [Country]" and "Event Registered [Country]".
These use HubSpot's built-in unified custom-behavioral-event IDs for this
portal — literal, portal-wide constants (do NOT look these up per event):
  Education Enrolled → eventTypeId "6-58204655"
  Event Registered (any past LF event, any brand) → eventTypeId "6-48984571"
Root is OR of two AND branches (country, then ip_country) so either property
qualifies. [location_term] is this event's own country (RULE 7/8), e.g. "Korea".
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
          "eventTypeId": "[6-58204655 or 6-48984571]",
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
          "eventTypeId": "[same eventTypeId as above]",
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
Every suppression found here is combined into ONE "Combined Suppression" list in
STEP 5B, and that single list is then applied as a NOT_IN_LIST exclusion in each
inclusion branch of the master list (STEP 6). Do NOT add the individual suppression
lists into the inclusion groups. They are ALSO reported in the ## SUPPRESSION LISTS
section so they can be applied at email send time. Your job here is to find their IDs.

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
STEP 5B — Build the Combined Suppression list (one list holding ALL suppressions)
═══════════════════════════════════════════════════
Create ONE dynamic list whose members are every contact in ANY suppression list found
in STEP 5. This is a pure OR of IN_LIST membership filters — one AND branch per
suppression list. STEP 6 references this single list as the only exclusion, so the
suppression set is defined in exactly ONE place instead of being repeated in every group.

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
DO NOT end without attempting to create the master list.

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

    # Ground-truth list IDs, captured directly from each hubspot_create_list
    # tool result — not parsed from the model's free-text narration, which can
    # misreport the ID it just printed. RULE 4 in the building prompt guarantees
    # the master list is always the LAST list created, so the last entry here
    # is unambiguously the master list.
    created_lists: list[dict] = []

    def _execute_and_track(name: str, tool_input: dict) -> str:
        result_json = _audience_execute(name, tool_input)
        if name == "hubspot_create_list":
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
            if name == "snowflake_query":
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

def start_plan_job(event_url: str, prescraped: dict | None = None) -> str:
    """Phase 1 — start segment planning job. Returns job_id for SSE polling.
    Always routes through the deterministic gateway (SDK or CLI, chosen inside it).

    `prescraped` — event data already scraped during the Email Content stage
    (session.meta["url_data"]). When present, the planning agent reuses it
    instead of re-fetching the event page."""
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    log.info(f"[AUDIENCE] plan job {job_id[:8]} — backend={llm_gateway.backend_name()!r} — url={event_url!r} reuse_scrape={bool(prescraped)}")
    prompt = build_planning_prompt(event_url, prescraped)
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
