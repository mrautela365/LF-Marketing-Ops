"""
Read-only tool set for the Audience Builder discovery agent.

Ported from emailcreationskill/backend/audience_tools.py (the `web_fetch`,
`hubspot_search_campaigns`, `hubspot_search_lists`, `hubspot_get_list`,
`snowflake_query`, `read_reference_file` implementations + the `_fn()` tool-
schema builder + the `present_discovered_lists` synthetic terminal tool from
emailcreationskill/backend/audience_builder/discovery_tools.py), re-homed to
call into this project's `integrations/hubspot.py` for the HubSpot parts
instead of raw `requests` calls, since audience_tools.py itself does not
exist in this project.

Deliberately EXCLUDES hubspot_create_list / hubspot_update_list_filters /
hubspot_get_event_types: discovery must never create or modify HubSpot state
(those already exist, for the *building* side, in integrations/hubspot.py's
create_list/update_list_filters, used by audience_builder/master_list.py).
"""
import datetime
import decimal
import os
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from integrations import hubspot as hs

# Snowflake + cryptography (optional — import error is caught gracefully, same
# as emailcreationskill/backend/audience_tools.py). Requires SNOWFLAKE_ACCOUNT,
# SNOWFLAKE_USER, SNOWFLAKE_PRIVATE_KEY (PEM) env vars; SNOWFLAKE_DATABASE
# (default ANALYTICS), SNOWFLAKE_SCHEMA (default Silver_Segment),
# SNOWFLAKE_WAREHOUSE / SNOWFLAKE_ROLE optional. If these aren't set,
# snowflake_query() raises a clear RuntimeError rather than silently no-op'ing.
try:
    import snowflake.connector
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, load_pem_private_key,
    )
    _SNOWFLAKE_AVAILABLE = True
except ImportError:
    _SNOWFLAKE_AVAILABLE = False

_BACKEND = Path(__file__).parent.parent
# References dir local to this package — this project has no pre-existing
# skills/hubspot-event-list-builder/references directory like the source
# project does, so read_reference_file will simply report "not found" (its
# existing FileNotFoundError branch) until reference files are added here.
_REFERENCES_DIR = Path(__file__).parent / "references"


# ── web_fetch ──────────────────────────────────────────────────────────────
_WEB_FETCH_CACHE: dict[str, tuple[float, dict]] = {}
_WEB_FETCH_CACHE_TTL = 1800  # 30 min — long enough to span discover -> compose-master on the same event


def web_fetch(url: str) -> dict:
    """Fetch a URL and return its cleaned text content. Short-lived per-URL
    cache so re-running discovery right after a prior pass doesn't re-scrape."""
    now = time.time()
    cached = _WEB_FETCH_CACHE.get(url)
    if cached and (now - cached[0]) < _WEB_FETCH_CACHE_TTL:
        return cached[1]

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
        result = {"url": url, "status": r.status_code, "content": "\n".join(lines)[:12000]}
    except Exception as exc:
        result = {"url": url, "error": str(exc)}

    if "error" not in result:
        _WEB_FETCH_CACHE[url] = (now, result)
    return result


# ── HubSpot read-only tools (delegate to integrations/hubspot.py) ──────────

def hubspot_search_campaigns(query: str) -> dict:
    """Search HubSpot marketing emails by name or subject."""
    return hs.search_campaigns(query)


def hubspot_search_lists(query: str) -> dict:
    """Search HubSpot contact lists by name. Normalizes to the
    {"query", "results": [{"listId","name","size"}]} shape the discovery
    agent / master_list.py / last_sent.py all expect."""
    lists = hs.search_lists(query, count=20)

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
    return hs.get_list(list_id)


def hubspot_list_membership_ids(list_id: str, cap_pages: int = 100) -> set:
    """Exact set of contact record IDs currently in a list — bounded exact
    de-dup path for master_list.union_size()."""
    return hs.list_membership_ids(list_id, cap_pages=cap_pages)


def hubspot_search_emails_raw(name_contains: str, limit: int = 30) -> list:
    """Raw HubSpot marketing-email search results for last_sent.py."""
    return hs.search_emails_raw(name_contains, limit=limit)


def hubspot_legacy_v1_list_name(list_id: str) -> str | None:
    """Legacy v1 list-name recovery for a 404'd v3 list ID (renumbered list)."""
    return hs.legacy_v1_list_name(list_id)


# ── Snowflake ────────────────────────────────────────────────────────────────

def _sf_private_key_bytes() -> bytes:
    pem = os.environ.get("SNOWFLAKE_PRIVATE_KEY", "").strip()
    if not pem:
        raise RuntimeError("SNOWFLAKE_PRIVATE_KEY not set")
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
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


def snowflake_query(sql: str) -> dict:
    """Run a SQL query against Snowflake and return rows as a list of dicts.
    Raises a clear RuntimeError (surfaced back to the agent as a tool error,
    never silently swallowed) if Snowflake env vars/driver aren't configured —
    this project has no Snowflake infra set up by default."""
    conn = _sf_connect()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [{col: _sf_json_safe(val) for col, val in zip(cols, row)} for row in cur.fetchall()]
        return {"columns": cols, "rows": rows, "count": len(rows)}
    finally:
        conn.close()


# ── Reference files ──────────────────────────────────────────────────────────

def read_reference_file(filename: str) -> dict:
    """Read a file from this package's references/ directory."""
    safe = Path(filename).name
    path = _REFERENCES_DIR / safe
    try:
        return {"filename": safe, "content": path.read_text(encoding="utf-8")}
    except FileNotFoundError:
        return {"error": f"{safe} not found in references/"}
    except Exception as exc:
        return {"error": str(exc)}


# ── Tool schema builder + definitions (OpenAI / LiteLLM function-tool format,
#    converted to Anthropic format via llm.gateway.openai_tools_to_anthropic) ──

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


def present_discovered_lists(lists: list = None, uncertain: list = None,
                              brand_short: str = "", event_name: str = "") -> dict:
    """No-op — discovery_agent's on_event handler intercepts this tool call by
    name and emits the structured 'discovered' SSE frame from there."""
    return {"presented": len(lists or []) + len(uncertain or [])}


_READ_ONLY_TOOL_DEFS = [
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

_PRESENT_DISCOVERED_LISTS_DEF = _fn(
    "present_discovered_lists",
    "Present the final set of discovered HubSpot lists for user selection. Call this "
    "exactly ONCE, after you have investigated the event and classified every relevant "
    "existing list into one of the 6 signal buckets (or into 'uncertain' if it doesn't "
    "confidently fit). This is a read-only discovery pass — you have no tool that can "
    "create or modify a HubSpot list, so do not attempt to.",
    {
        "brand_short": {
            "type": "string",
            "description": "The event's short brand/foundation code identified in STEP 1 (e.g. CNCF, PyTorch, Hyperledger, LF) — reused to look up brand-scoped suppression lists.",
        },
        "event_name": {
            "type": "string",
            "description": "The event's proper name identified in STEP 1 — reused to look up any pre-existing suppression list for this specific event and to find what was last sent for it.",
        },
        "lists": {
            "type": "array",
            "description": "Every existing HubSpot list confidently matched to one of the 6 signals.",
            "items": {
                "type": "object",
                "properties": {
                    "list_id": {"type": "string"},
                    "name": {"type": "string"},
                    "signal": {
                        "type": "string",
                        "enum": [
                            "project_opt_in",
                            "lf_newsletter_opt_in",
                            "event_registration",
                            "education_enrollment",
                            "page_view",
                            "event_speakers",
                        ],
                    },
                    "size": {"type": "integer", "description": "Membership count, if known."},
                    "reason": {"type": "string", "description": "Short justification tying this list to the signal."},
                    "list_type": {
                        "type": "string",
                        "description": "The list's real processingType field from hubspot_get_list, verbatim (e.g. DYNAMIC, MANUAL, SNAPSHOT). Do not guess — omit if you didn't call hubspot_get_list on it.",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["current", "past", "current_past"],
                        "description": "Only meaningful when signal is 'event_speakers' — which edition(s) of the event this speaker list actually covers, per STEP 3 rule 6. Omit for every other signal.",
                    },
                },
                "required": ["list_id", "name", "signal"],
            },
        },
        "uncertain": {
            "type": "array",
            "description": "Lists that look event-relevant but don't confidently map to one of the 6 signals.",
            "items": {
                "type": "object",
                "properties": {
                    "list_id": {"type": "string"},
                    "name": {"type": "string"},
                    "size": {"type": "integer"},
                    "reason": {"type": "string"},
                    "list_type": {"type": "string", "description": "Real processingType from hubspot_get_list, if known."},
                },
                "required": ["list_id", "name"],
            },
        },
    },
    ["lists", "uncertain"],
)

TOOL_DEFS_OPENAI = _READ_ONLY_TOOL_DEFS + [_PRESENT_DISCOVERED_LISTS_DEF]

TOOL_HANDLERS: dict = {
    "web_fetch":                lambda i: web_fetch(i["url"]),
    "hubspot_search_campaigns": lambda i: hubspot_search_campaigns(i["query"]),
    "hubspot_search_lists":     lambda i: hubspot_search_lists(i["query"]),
    "hubspot_get_list":         lambda i: hubspot_get_list(i["list_id"]),
    "snowflake_query":          lambda i: snowflake_query(i["sql"]),
    "read_reference_file":      lambda i: read_reference_file(i["filename"]),
    "present_discovered_lists": lambda i: present_discovered_lists(
        i.get("lists"), i.get("uncertain"), i.get("brand_short", ""), i.get("event_name", "")
    ),
}
