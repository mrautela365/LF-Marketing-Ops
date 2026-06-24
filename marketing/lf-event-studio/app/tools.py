"""
Tool implementations for the LF Event Audience Studio agent.
HubSpot (REST API), Snowflake (Python connector), web fetch (requests).
All credentials are read from environment variables.
"""

import json
import os
from pathlib import Path

import requests
import snowflake.connector
from bs4 import BeautifulSoup

# ── HubSpot ──────────────────────────────────────────────────────────────────

HUBSPOT_BASE = "https://api.hubapi.com"
HS_PORTAL_ID = "8112310"


def _hs_headers() -> dict:
    key = os.environ.get("HUBSPOT_API_KEY", "")
    if not key:
        raise RuntimeError("HUBSPOT_API_KEY not set")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def hubspot_search_campaigns(query: str) -> dict:
    """Search HubSpot marketing emails by name or subject."""
    url = f"{HUBSPOT_BASE}/marketing/v3/emails"
    params = {"limit": 50, "sort": "-updatedAt"}
    r = requests.get(url, headers=_hs_headers(), params=params, timeout=15)
    r.raise_for_status()
    emails = r.json().get("results", [])
    q = query.lower()
    matches = [
        {
            "id": e.get("id"),
            "name": e.get("name"),
            "subject": e.get("subject"),
            "updatedAt": e.get("updatedAt"),
            "stats": e.get("stats", {}),
        }
        for e in emails
        if q in (e.get("name", "") + " " + e.get("subject", "")).lower()
    ]
    return {"query": query, "results": matches[:15]}


def hubspot_search_lists(query: str) -> dict:
    """Search HubSpot contact lists by name."""
    url = f"{HUBSPOT_BASE}/crm/v3/lists/search"
    payload = {"query": query, "count": 20, "includeFilters": False}
    r = requests.post(url, headers=_hs_headers(), json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    lists = data.get("lists", [])
    return {
        "query": query,
        "results": [
            {"listId": l.get("listId"), "name": l.get("name"), "size": l.get("size")}
            for l in lists
        ],
    }


def hubspot_get_list(list_id: str) -> dict:
    """Get a HubSpot contact list including its filter branch."""
    url = f"{HUBSPOT_BASE}/crm/v3/lists/{list_id}"
    params = {"includeFilters": "true"}
    r = requests.get(url, headers=_hs_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def hubspot_create_list(name: str, filter_branch: dict) -> dict:
    """
    Create a new dynamic HubSpot contact list.
    filter_branch must be a valid HubSpot filterBranch object.
    """
    url = f"{HUBSPOT_BASE}/crm/v3/lists/"
    payload = {
        "name": name,
        "objectTypeId": "0-1",
        "processingType": "DYNAMIC",
        "filterBranch": filter_branch,
    }
    r = requests.post(url, headers=_hs_headers(), json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    return {
        "listId": data.get("listId"),
        "name": data.get("name"),
        "size": data.get("size"),
        "raw": data,
    }


def hubspot_update_list_filters(list_id: str, filter_branch: dict) -> dict:
    """Replace the filter branch on an existing HubSpot list."""
    url = f"{HUBSPOT_BASE}/crm/v3/lists/{list_id}/filter-branch"
    r = requests.put(url, headers=_hs_headers(), json={"filterBranch": filter_branch}, timeout=15)
    r.raise_for_status()
    return {"listId": list_id, "updated": True}


def hubspot_get_event_types() -> dict:
    """List HubSpot custom event type definitions (needed for Has-completed-event filters)."""
    url = f"{HUBSPOT_BASE}/events/v3/event-definitions"
    r = requests.get(url, headers=_hs_headers(), timeout=15)
    r.raise_for_status()
    defs = r.json().get("results", [])
    return {
        "results": [
            {"fullyQualifiedName": d.get("fullyQualifiedName"), "label": d.get("label")}
            for d in defs
        ]
    }


# ── Snowflake ─────────────────────────────────────────────────────────────────


def _sf_connect():
    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Snowflake env vars not set: {', '.join(missing)}")
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
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


# ── Web fetch ─────────────────────────────────────────────────────────────────


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
        # Collapse excessive blank lines
        lines = [l for l in text.splitlines() if l.strip()]
        return {"url": url, "status": r.status_code, "content": "\n".join(lines)[:12000]}
    except Exception as exc:
        return {"url": url, "error": str(exc)}


# ── Local file read ────────────────────────────────────────────────────────────
# Restricted to the hubspot-event-list-builder/references/ directory.

_REFERENCES_DIR = Path(__file__).parent.parent.parent / "hubspot-event-list-builder" / "references"


def read_reference_file(filename: str) -> dict:
    """Read a file from the references/ directory (e.g. brand-master-lists.md)."""
    safe = Path(filename).name  # strip any path traversal
    path = _REFERENCES_DIR / safe
    try:
        return {"filename": safe, "content": path.read_text(encoding="utf-8")}
    except FileNotFoundError:
        return {"error": f"{safe} not found in references/"}
    except Exception as exc:
        return {"error": str(exc)}


# ── Tool definitions (OpenAI / LiteLLM format) ───────────────────────────────
# Each entry: {"type": "function", "function": {"name", "description", "parameters"}}

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
        ("Create a new dynamic HubSpot contact list. "
         "filter_branch must follow the HubSpot filterBranch schema. "
         "For custom-event filters use filterType='BEHAVIORAL_EVENT'. "
         "For list-membership filters use filterType='LIST_MEMBERSHIP'. "
         "For page-view filters use filterType='PAGE_VIEW'."),
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
        ("Run a SQL query against Snowflake. "
         "Default database: ANALYTICS, schema: Silver_Segment. "
         "Use to find past event editions in EVENT_REGISTRATIONS."),
        {"sql": {"type": "string", "description": "SQL query to execute"}},
        ["sql"]),

    _fn("read_reference_file",
        "Read a file from the references/ directory. Use 'brand-master-lists.md' to look up brand master list IDs.",
        {"filename": {"type": "string", "description": "Filename only, e.g. 'brand-master-lists.md'"}},
        ["filename"]),
]

TOOL_HANDLERS: dict = {
    "web_fetch":                  lambda i: web_fetch(i["url"]),
    "hubspot_search_campaigns":   lambda i: hubspot_search_campaigns(i["query"]),
    "hubspot_search_lists":       lambda i: hubspot_search_lists(i["query"]),
    "hubspot_get_list":           lambda i: hubspot_get_list(i["list_id"]),
    "hubspot_create_list":        lambda i: hubspot_create_list(i["name"], i["filter_branch"]),
    "hubspot_update_list_filters":lambda i: hubspot_update_list_filters(i["list_id"], i["filter_branch"]),
    "hubspot_get_event_types":    lambda i: hubspot_get_event_types(),
    "snowflake_query":            lambda i: snowflake_query(i["sql"]),
    "read_reference_file":        lambda i: read_reference_file(i["filename"]),
}
