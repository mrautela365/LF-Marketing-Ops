"""
Prompts for the two Claude phases.
The {skill} placeholder is filled at runtime by reading the sibling app's SKILL.md
from disk — this ensures claude -p gets the exact same instructions as interactive use
without relying on slash-command invocation (which does not work in -p mode).
"""

PLANNING_PROMPT = """You are working as an LF email audience strategist.
Plan the HubSpot audience segment for this Linux Foundation event:

{url}

Follow EVERY step in the skill instructions below exactly.
Narrate each sub-step as you work through it so progress is visible.

{skill}
"""

BUILDING_PROMPT = """Build the HubSpot audience lists for this Linux Foundation event.

Event URL: {url}

The segment planning phase is COMPLETE. The event page has already been scraped.
Do NOT re-scrape or re-fetch the event URL. All event details are in the Segment Plan below.

--- SEGMENT PLAN ---
{plan}
--- END SEGMENT PLAN ---
{qa_section}
═══════════════════════════════════════════════════
CRITICAL OVERRIDES (take precedence over the skill instructions below)
═══════════════════════════════════════════════════
OVERRIDE 1 — Skip Step 1 (scraping). The event URL has already been scraped.
  Use all event details (name, brand, location, year, URL) from the Segment Plan above.
  Start directly at Step 2 (Snowflake query).

OVERRIDE 2 — communitySeg lists MUST NEVER be used:
  Any list labelled communitySeg / community_seg in the plan must NOT be cloned or referenced.
  If it represents past event registrants → rebuild as a HubSpot custom event list.
  Reference filter style: https://app.hubspot.com/contacts/8112310/objectLists/28908/filters
  Use Snowflake (mcp__snowflake__run_query) to resolve the exact event name if unclear.
  Name the rebuilt list: "[Event Name] Past Registrants (custom event)"
  If NOT past registrations and cannot be cleanly rebuilt → skip it and flag it.

OVERRIDE 3 — Print ## BUILD PLAN before touching anything in HubSpot.
  List every list to create, each communitySeg replacement, and anything being skipped.

OVERRIDE 4 — Master list last, OR of all built lists. Zero communitySeg sources.

OVERRIDE 5 — If unsure about anything → skip and add to ## FLAGGED FOR REVIEW.

═══════════════════════════════════════════════════
SKILL INSTRUCTIONS (follow from Step 2 onwards)
═══════════════════════════════════════════════════
{skill}
"""
