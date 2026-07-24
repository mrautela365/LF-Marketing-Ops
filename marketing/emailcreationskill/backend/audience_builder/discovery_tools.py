"""
Read-only tool set for the Audience Builder discovery agent. Reuses
audience_tools' existing HubSpot/Snowflake/web functions directly instead of
reimplementing them — this module adds no new HubSpot read logic of its own.

Deliberately EXCLUDES hubspot_create_list / hubspot_update_list_filters /
hubspot_get_event_types: discovery must never create or modify HubSpot state.
"""
import audience_tools

_READ_ONLY_TOOL_NAMES = {
    "web_fetch",
    "hubspot_search_campaigns",
    "hubspot_search_lists",
    "hubspot_get_list",
    "snowflake_query",
    "read_reference_file",
}

_BASE_TOOL_DEFS = [
    d for d in audience_tools.TOOL_DEFS_OPENAI
    if d["function"]["name"] in _READ_ONLY_TOOL_NAMES
]


def present_discovered_lists(lists: list = None, uncertain: list = None) -> dict:
    """No-op — discovery_agent's on_event handler intercepts this tool call by
    name and emits the structured 'discovered' SSE frame from there (mirrors
    audience_tools.present_open_questions)."""
    return {"presented": len(lists or []) + len(uncertain or [])}


_PRESENT_DISCOVERED_LISTS_DEF = audience_tools._fn(
    "present_discovered_lists",
    "Present the final set of discovered HubSpot lists for user selection. Call this "
    "exactly ONCE, after you have investigated the event and classified every relevant "
    "existing list into one of the 5 signal buckets (or into 'uncertain' if it doesn't "
    "confidently fit). This is a read-only discovery pass — you have no tool that can "
    "create or modify a HubSpot list, so do not attempt to.",
    {
        "lists": {
            "type": "array",
            "description": "Every existing HubSpot list confidently matched to one of the 5 signals.",
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
                        ],
                    },
                    "size": {"type": "integer", "description": "Membership count, if known."},
                    "reason": {"type": "string", "description": "Short justification tying this list to the signal."},
                    "list_type": {
                        "type": "string",
                        "description": "The list's real processingType field from hubspot_get_list, verbatim (e.g. DYNAMIC, MANUAL, SNAPSHOT). Do not guess — omit if you didn't call hubspot_get_list on it.",
                    },
                },
                "required": ["list_id", "name", "signal"],
            },
        },
        "uncertain": {
            "type": "array",
            "description": "Lists that look event-relevant but don't confidently map to one of the 5 signals.",
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

TOOL_DEFS_OPENAI = _BASE_TOOL_DEFS + [_PRESENT_DISCOVERED_LISTS_DEF]

TOOL_HANDLERS: dict = {
    "web_fetch":                lambda i: audience_tools.web_fetch(i["url"]),
    "hubspot_search_campaigns": lambda i: audience_tools.hubspot_search_campaigns(i["query"]),
    "hubspot_search_lists":     lambda i: audience_tools.hubspot_search_lists(i["query"]),
    "hubspot_get_list":         lambda i: audience_tools.hubspot_get_list(i["list_id"]),
    "snowflake_query":          lambda i: audience_tools.snowflake_query(i["sql"]),
    "read_reference_file":      lambda i: audience_tools.read_reference_file(i["filename"]),
    "present_discovered_lists": lambda i: present_discovered_lists(i.get("lists"), i.get("uncertain")),
}
