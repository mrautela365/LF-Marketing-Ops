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
)

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
_BACKEND      = Path(__file__).parent
SKILL_DIR     = _BACKEND.parent.parent / "LF-Marketing-Ops" / "marketing" / "hubspot-event-list-builder"
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
        "name": name,
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
    pem = pem.replace("\\n", "\n")
    key = load_pem_private_key(pem.encode(), password=None, backend=default_backend())
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


def snowflake_query(sql: str) -> dict:
    """Run a SQL query against Snowflake and return rows as a list of dicts."""
    conn = _sf_connect()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
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
            "For custom-event filters use filterType='BEHAVIORAL_EVENT'. "
            "For list-membership filters use filterType='LIST_MEMBERSHIP'. "
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
        "Read a file from the references/ directory. Use 'brand-master-lists.md' to look up brand master list IDs.",
        {"filename": {"type": "string", "description": "Filename only, e.g. 'brand-master-lists.md'"}},
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


# ══════════════════════════════════════════════════════════════════════════════
# Prompts (ported verbatim from lf-event-studio/app/prompts.py)
# ══════════════════════════════════════════════════════════════════════════════

PLANNING_PROMPT = """You are an experienced LF email audience strategist.
Plan the HubSpot audience segment for this Linux Foundation event:

{url}

Work through ALL 4 steps below, narrating each sub-step so progress is visible.

═══════════════════════════════════════════════════
STEP 1 — Scrape the event page
═══════════════════════════════════════════════════
Use web_fetch to fetch the URL above. Extract:
- Event name (full title, e.g. "KubeCon + CloudNativeCon North America 2026")
- Short name / slug (e.g. "KCNA", "OSSNA") — used for HubSpot search terms
- Foundation / brand (e.g. CNCF, The Linux Foundation, PyTorch, OpenSearch)
- Location (city + country/region)
- Event dates and year
- Event type (in-person conference, virtual, hybrid, summit)

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

═══════════════════════════════════════════════════
STEP 3 — Analyse historical segmentation logic
═══════════════════════════════════════════════════
Reconstruct the full audience strategy from prior emails and lists:

Inclusion sources: past registrants, web visitors, geographic segments,
topic interests, newsletter subscribers, foundation subscriber lists.

Exclusion sources: LF Events Global Opt Outs, LF Global Opt-Outs,
GDPR suppression, current registrants, internal LF contacts,
foundation-specific opt-outs.

Opt-in filter logic: whether applied, which variant (Foundation / LF Events /
LF Newsletter), and why.

Flag any communitySeg / community_seg lists found — note which are
past-registrant lists (rebuildable) vs other (skip and flag).

═══════════════════════════════════════════════════
STEP 4 — Produce the Segment Plan Report
═══════════════════════════════════════════════════
Write a complete structured report using this format:

### 📋 Event Segment Plan: [Event Name] [Year]

**Event summary** — name, foundation, location, dates, type.

**Historical context** — prior master list name, send counts, key changes, QA notes.

**Recommended master list name**
Follow foundation naming convention, e.g.:
`Q3 2026 - CNCF Foundation - KubeCon + CloudNativeCon North America Master (With Opt-In and Filters)`

**Inclusion strategy** — per source list: name, why it belongs, dynamic vs snapshot.
Group by and number each list:
  1. Past registrants (BEHAVIORAL_EVENT filter)
  2. Web visitors (PAGE_VIEW + brand master)
  3. Geographic segments (if applicable)
  4. Topic / persona lists (if applicable)
  5. Foundation / newsletter subscribers (if applicable)
  6. Any other inclusion lists from prior sends

For each inclusion list, state:
  - Proposed HubSpot list name
  - Filter type (BEHAVIORAL_EVENT / PAGE_VIEW / LIST_MEMBERSHIP / property)
  - Why it belongs

**Exclusion strategy** — per suppression list: name and reason.
Always include: LF Events Global Opt Outs, LF Global Opt-Outs, GDPR Suppression (if EU in scope),
23Q1 LF Master Exclusion List, foundation opt-out, current registrants segment.

**Opt-in filter recommendation** — whether to apply, which variant, and why.

**Estimated list size** — based on prior counts, expected growth, opt-in filter impact.

**Recommended HubSpot list structure** — filter group sketch (OR/AND logic).

**communitySeg lists** — list each one found; classify as past-registrant (rebuildable) or other.

**Open questions / flags** — anything to confirm before building.

End with: "Ready to proceed? Say yes and I'll build the segment in HubSpot."
"""


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
  numbered inclusion source. Do not skip any.

RULE 2 — communitySeg lists MUST NEVER be used as sources:
  Any list labelled communitySeg / community_seg must NOT be referenced or included.
  Past-registrant communitySeg → rebuild using BEHAVIORAL_EVENT filters.
  Non-registrant communitySeg → skip and add to ## FLAGGED FOR REVIEW.

RULE 3 — Print ## BUILD PLAN before creating anything in HubSpot.
  Number each list to create. State its filter type and logic.

RULE 4 — MASTER LIST IS MANDATORY. You MUST always build the master list as the final step.
  Even if some inclusion lists failed, build the master from whatever IDs you DO have.
  Never end without creating the master list. It is the primary deliverable.

RULE 5 — After EVERY successful hubspot_create_list call print:
  ✅ [List name] created — ID: [listId] — [hubspot_url]

RULE 6 — If unsure about anything → skip and add to ## FLAGGED FOR REVIEW.

═══════════════════════════════════════════════════
STEP 1 — Query Snowflake for past editions
═══════════════════════════════════════════════════
Use snowflake_query. Derive [event_term], [location_term], [current_year] from the
Segment Plan above — do NOT re-scrape the URL.

  SELECT DISTINCT EV.EVENT_NAME, EV.EVENT_ID
  FROM ANALYTICS.Silver_Segment.EVENT_REGISTRATIONS AS EV
  WHERE EV.EVENT_NAME ILIKE '%[event_term]%'
    AND EV.EVENT_NAME ILIKE '%[location_term]%'
    AND EV.EVENT_NAME NOT ILIKE '%[current_year]%'
  ORDER BY EV.EVENT_NAME;

Copy the exact EVENT_NAME strings — they are used verbatim as HubSpot filter values.

═══════════════════════════════════════════════════
STEP 2 — Look up brand master list ID
═══════════════════════════════════════════════════
Use read_reference_file("brand-master-lists.md") to look up the brand key from the plan.
If not found → use hubspot_search_lists("[brand] master") to find it, note the ID.

Call hubspot_get_event_types() now so the fullyQualifiedName is ready for Step 4.
Look for a name containing "event_registration". The value looks like "pe8112310_event_registration".

═══════════════════════════════════════════════════
STEP 3 — Print ## BUILD PLAN
═══════════════════════════════════════════════════
Print a numbered plan of EVERY list you will create, derived from the
Inclusion strategy in the Segment Plan. Include:
- List number and name
- Filter type(s)
- Why it's needed
- Any communitySeg list it replaces (→ BEHAVIORAL_EVENT rebuild)
- Anything being SKIPPED and why

═══════════════════════════════════════════════════
STEP 4 — Build ALL inclusion lists (one per inclusion source)
═══════════════════════════════════════════════════
Create every list from your BUILD PLAN in order. Use the correct filter type for each:

── BEHAVIORAL_EVENT (past registrants) ──────────────────────
Use for: past-registrant lists, communitySeg rebuilds.
filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{
          "filterType": "BEHAVIORAL_EVENT",
          "eventTypeId": "[exact fullyQualifiedName e.g. pe8112310_event_registration]",
          "operator": "HAS_EVENT",
          "filterGroups": [
            {{
              "filters": [
                {{
                  "property": "hs_event_name",
                  "operator": "EQ",
                  "value": "[exact EVENT_NAME from Snowflake]"
                }}
              ]
            }}
          ]
        }}
      ]
    }}
  ],
  "filters": []
}}
Add one AND branch per past edition. All inside the top OR.

── PAGE_VIEW + LIST_MEMBERSHIP (web visitors) ───────────────
Use for: web-visitor + brand-master combination.
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

── LIST_MEMBERSHIP (reference existing HubSpot lists) ───────
Use for: geographic lists, topic/persona lists, newsletter lists already in HubSpot.
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
# OpenAI / LiteLLM agent loop (ported verbatim from lf-event-studio/app/agent.py)
# ══════════════════════════════════════════════════════════════════════════════

_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        base_url = LITELLM_BASE_URL.rstrip("/")
        api_key  = LITELLM_API_KEY
        if not base_url or not api_key:
            raise RuntimeError("LITELLM_BASE_URL and LITELLM_API_KEY must be set in .env")
        log.info(f"[AGENT] Creating OpenAI client → base_url={base_url!r}")
        _openai_client = OpenAI(base_url=base_url, api_key=api_key)
    return _openai_client


def _litellm_model() -> str:
    return os.environ.get("LITELLM_MODEL", os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"))


def _run_agent(prompt: str, q: queue.Queue) -> None:
    """Agentic loop using the OpenAI-compatible LiteLLM proxy (matches lf-event-studio)."""
    model = _litellm_model()
    turn = 0
    log.info(f"[AGENT] starting — model={model!r} prompt_len={len(prompt)}")
    try:
        client = _get_openai_client()
        messages = [{"role": "user", "content": prompt}]

        while True:
            turn += 1
            collected_text  = ""
            pending_text    = ""
            collected_calls = {}
            finish_reason   = None

            log.info(f"[AGENT] turn {turn} — calling LiteLLM (messages={len(messages)})")
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOL_DEFS_OPENAI,
                tool_choice="auto",
                stream=True,
                max_tokens=32000,
            )
            log.info(f"[AGENT] turn {turn} — stream open, reading chunks")

            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                finish_reason = choice.finish_reason or finish_reason
                delta = choice.delta

                if delta.content:
                    collected_text += delta.content
                    pending_text   += delta.content
                    while "\n" in pending_text:
                        line, pending_text = pending_text.split("\n", 1)
                        if line.strip():
                            q.put({"type": "output", "text": line})

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in collected_calls:
                            collected_calls[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.id:
                            collected_calls[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                collected_calls[idx]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                collected_calls[idx]["function"]["arguments"] += tc.function.arguments

            if pending_text.strip():
                q.put({"type": "output", "text": pending_text})

            log.info(f"[AGENT] turn {turn} — finish_reason={finish_reason!r} text_len={len(collected_text)} tool_calls={len(collected_calls)}")

            if finish_reason == "stop":
                log.info("[AGENT] done (stop)")
                q.put({"type": "done", "done": True, "success": True})
                break

            if finish_reason == "tool_calls":
                tool_call_list = [collected_calls[i] for i in sorted(collected_calls)]

                messages.append({
                    "role": "assistant",
                    "content": collected_text or None,
                    "tool_calls": tool_call_list,
                })

                for tc in tool_call_list:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    brief = json.dumps(args)[:120]
                    log.info(f"[AGENT] → tool call: {name}({brief})")
                    q.put({"type": "output", "text": f"🔧 {name}({json.dumps(args)[:100]})"})

                    handler = TOOL_HANDLERS.get(name)
                    if handler:
                        try:
                            result = handler(args)
                        except Exception as exc:
                            log.warning(f"[AGENT] tool {name} raised: {exc}")
                            result = {"error": str(exc)}
                    else:
                        result = {"error": f"Unknown tool: {name}"}

                    result_preview = json.dumps(result)[:200]
                    log.info(f"[AGENT] ← tool result: {name} → {result_preview}")
                    q.put({"type": "output", "text": f"   ↳ {result_preview}"})

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result),
                    })

            else:
                log.info(f"[AGENT] done (finish_reason={finish_reason!r})")
                q.put({"type": "done", "done": True, "success": True})
                break

    except Exception as exc:
        log.error(f"[AGENT] fatal error: {exc}", exc_info=True)
        q.put({"type": "output", "text": f"❌ Agent error: {exc}"})
        q.put({"type": "done", "done": True, "success": False})


# ══════════════════════════════════════════════════════════════════════════════
# CLI fallback (used when LITELLM_BASE_URL is not configured)
# ══════════════════════════════════════════════════════════════════════════════

_CLI_PROMPT = """\
Build the HubSpot event audience lists for this Linux Foundation event:

{url}

Follow the hubspot-event-list-builder skill instructions in SKILL.md exactly, \
working through all 6 steps:
1. Scrape the event page to extract name, edition, brand key, and Snowflake search terms
2. Query Snowflake for all past editions (excluding the current year)
3. Look up the brand master list ID from references/brand-master-lists.md
4. Clone the reference list and build List 1 — All Past Registrants
5. Build List 2 — Registrants + Web Visitors
6. Confirm and report both list IDs, names, and filter counts

After all individual lists are created, build one final Master Audience list:
- Name: "[Event Name] [Year] — Master Audience"
- Combines ALL lists using OR logic

Narrate what you are doing at every sub-step.

IMPORTANT: At the very end output exactly this line (substitute the real numeric ID):
MASTER_LIST_ID: <numeric_hubspot_list_id>
"""

_CLAUDE_CLI: str | None = None


def _get_claude_cli() -> str:
    global _CLAUDE_CLI
    if _CLAUDE_CLI:
        return _CLAUDE_CLI
    found = shutil.which("claude")
    if found:
        _CLAUDE_CLI = found
        return found
    fallback = r"C:\Users\VinayU\AppData\Roaming\npm\claude.cmd"
    if os.path.exists(fallback):
        _CLAUDE_CLI = fallback
        return fallback
    raise RuntimeError("claude CLI not found — install with: npm install -g @anthropic-ai/claude-code")


def _cli_run(event_url: str, q: queue.Queue) -> None:
    """Fallback: spawn claude CLI subprocess (uses local Claude Code session auth)."""
    try:
        claude_cmd = _get_claude_cli()
    except RuntimeError as exc:
        q.put({"type": "output", "text": f"Error: {exc}"})
        q.put({"type": "done", "done": True, "success": False})
        return

    skill_dir = str(SKILL_DIR) if SKILL_DIR.is_dir() else None
    if not skill_dir:
        q.put({"type": "output", "text": f"⚠ Skill directory not found: {SKILL_DIR}"})

    prompt = _CLI_PROMPT.format(url=event_url)
    try:
        proc = subprocess.Popen(
            [claude_cmd, "-p", prompt, "--dangerously-skip-permissions"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=skill_dir,
        )

        def _reader():
            for line in proc.stdout:
                q.put({"type": "output", "text": line.rstrip()})

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        try:
            proc.wait(timeout=_CLI_TIMEOUT)
            reader.join(timeout=10)
            success = proc.returncode == 0
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            reader.join(timeout=5)
            q.put({"type": "output", "text": f"\n⚠ Timed out after {_CLI_TIMEOUT // 60} min — process killed."})
            success = False

        q.put({"type": "done", "done": True, "success": success})

    except Exception as exc:
        q.put({"type": "output", "text": f"Error: {exc}"})
        q.put({"type": "done", "done": True, "success": False})


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def start_plan_job(event_url: str) -> str:
    """Phase 1 — start segment planning job. Returns job_id for SSE polling."""
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    if LITELLM_BASE_URL and LITELLM_API_KEY:
        log.info(f"[AUDIENCE] plan job {job_id[:8]} — LiteLLM mode — url={event_url!r}")
        prompt = PLANNING_PROMPT.format(url=event_url)
        threading.Thread(target=_run_agent, args=(prompt, q), daemon=True).start()
    else:
        log.info(f"[AUDIENCE] plan job {job_id[:8]} — CLI fallback (no LiteLLM) — url={event_url!r}")
        threading.Thread(target=_cli_run, args=(event_url, q), daemon=True).start()
    return job_id


def start_build_job(event_url: str, plan: str = "", qa: str = "") -> str:
    """
    Start audience list building. Returns job_id for SSE polling.

    - plan provided  → Phase 2 only (building from existing plan)
    - plan empty     → Phase 1 + Phase 2 chained automatically in one job
    """
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q
    if LITELLM_BASE_URL and LITELLM_API_KEY:
        if plan:
            log.info(f"[AUDIENCE] build job {job_id[:8]} — Phase 2 only (plan provided, {len(plan)} chars)")
            qa_section = f"\nUser answers to clarifying questions:\n{qa}\n" if qa else ""
            prompt = BUILDING_PROMPT.format(url=event_url, plan=plan, qa_section=qa_section)
            threading.Thread(target=_run_agent, args=(prompt, q), daemon=True).start()
        else:
            log.info(f"[AUDIENCE] build job {job_id[:8]} — two-phase (no plan provided) — url={event_url!r}")
            threading.Thread(target=_run_two_phase, args=(event_url, qa, q), daemon=True).start()
    else:
        log.info(f"[AUDIENCE] build job {job_id[:8]} — CLI fallback (no LiteLLM) — url={event_url!r}")
        threading.Thread(target=_cli_run, args=(event_url, q), daemon=True).start()
    return job_id


def _run_two_phase(event_url: str, qa: str, q: queue.Queue) -> None:
    """
    Run PLANNING_PROMPT then BUILDING_PROMPT in sequence within a single job.
    Phase 1 output is captured and passed as {plan} to Phase 2.
    All output lines are forwarded to q; done=True is only emitted at the end.
    """
    # ── Phase 1: planning ────────────────────────────────────────────────────
    log.info("[AUDIENCE] two-phase: starting Phase 1 (planning)")
    q.put({"type": "output", "text": "═══ Phase 1: Segment Planning ═══"})
    plan_q: queue.Queue = queue.Queue()
    plan_prompt = PLANNING_PROMPT.format(url=event_url)
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
