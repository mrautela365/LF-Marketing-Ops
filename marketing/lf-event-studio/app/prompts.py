"""
Prompts for the two Claude phases.
Skill instructions are embedded inline so claude -p doesn't need to read SKILL.md.
Phase 1 runs from event-segment-planner/ (references, OptIn report context).
Phase 2 runs from hubspot-event-list-builder/ (references/brand-master-lists.md).
"""

PLANNING_PROMPT = """/event-segment-planner {url}"""

BUILDING_PROMPT = """You are building HubSpot audience lists for a Linux Foundation event.

Event URL: {url}

The segment planning phase is COMPLETE. Do NOT re-scrape the event URL.
All event details (name, brand, location, year) are in the Segment Plan below.

--- SEGMENT PLAN ---
{plan}
--- END SEGMENT PLAN ---
{qa_section}
═══════════════════════════════════════════════════
CRITICAL RULES (enforce throughout)
═══════════════════════════════════════════════════
RULE 1 — communitySeg lists NEVER used:
  Any list labelled communitySeg / community_seg must NOT be cloned or referenced.
  If it represents past event registrants → rebuild using HubSpot custom event filters.
  Reference filter style: https://app.hubspot.com/contacts/8112310/objectLists/28908/filters
  Name the rebuilt list: "[Event Name] Past Registrants (custom event)"
  If NOT past registrations and can't be cleanly rebuilt → skip it and flag it.

RULE 2 — Print ## BUILD PLAN before touching HubSpot.

RULE 3 — Master list last, never references communitySeg (not even rebuilt ones by old name).

RULE 4 — If unsure about anything → skip and add to ## FLAGGED FOR REVIEW.

═══════════════════════════════════════════════════
STEP 1 — Query Snowflake for past editions
═══════════════════════════════════════════════════
Use the Snowflake MCP tool (mcp__snowflake__run_query) to find all past editions.
Use the event name and location from the Segment Plan above — no re-scraping needed.

Run:
  SELECT DISTINCT EV.EVENT_NAME, EV.EVENT_ID
  FROM ANALYTICS.Silver_Segment.EVENT_REGISTRATIONS AS EV
  WHERE EV.EVENT_NAME ILIKE '%[event_term]%'
    AND EV.EVENT_NAME ILIKE '%[location_term]%'
    AND EV.EVENT_NAME NOT ILIKE '%[current_year]%'
  ORDER BY EV.EVENT_NAME;

These exact EVENT_NAME strings are used verbatim as HubSpot filter values.
Also resolve any communitySeg event-name ambiguity at this step.

═══════════════════════════════════════════════════
STEP 2 — Look up brand master list ID
═══════════════════════════════════════════════════
Read the file references/brand-master-lists.md and look up the master list ID for the brand
from the Segment Plan.

If not found → search HubSpot: Contacts → Lists, search "[brand] master", pick the list
with opt-in filters, all event registrations, and education enrollments. Note its ID.
Add it to references/brand-master-lists.md for future use.

═══════════════════════════════════════════════════
STEP 3 — Print ## BUILD PLAN
═══════════════════════════════════════════════════
Before creating anything in HubSpot, print "## BUILD PLAN" listing:
- Every list to create: proposed name + filter logic
- Each communitySeg list being replaced and what replaces it
- Anything being skipped and why

═══════════════════════════════════════════════════
STEP 4 — Build List 1: All Past Registrants
═══════════════════════════════════════════════════
Reference list: https://app.hubspot.com/contacts/8112310/objectLists/26624/filters
Open it to confirm the custom event object name and property names.

Then clone it:
1. Open the reference list → ⋮ menu → Clone
2. Rename: [Brand] - [Event Name] - All Past Registrants
   Example: CNCF - KubeCon + CloudNativeCon India - All Past Registrants

Replace ALL existing filters with one OR condition per past Snowflake edition:
- Filter type: Custom event (same object as reference list)
- Property: event_name
- Operator: is equal to
- Value: [exact EVENT_NAME from Snowflake]

Save and note the new list ID.

═══════════════════════════════════════════════════
STEP 5 — Build List 2: Registrants + Web Visitors
═══════════════════════════════════════════════════
Create a new Contact-based list (or clone any simple list as starting point).

Name: [Brand] - [Event Name] - Registrants + Web Visitors

Filter structure — two groups joined by OR:
  Filter Group 1: Member of list → [List 1 ID from Step 4]
  Filter Group 2 (AND):
    - Condition A: Has visited page URL = [event URL]
    - Condition B: Member of list = [brand master list ID from Step 2]

Save and note the new list ID.

═══════════════════════════════════════════════════
STEP 6 — Rebuild communitySeg lists (if any)
═══════════════════════════════════════════════════
For each communitySeg past-registrant list in the plan:
- Create a new Contact-based list using HubSpot custom event filters
- Name it: [Event Name] Past Registrants (custom event)
- Filter: Has completed event → event_name = [exact Snowflake name]
- Reference: https://app.hubspot.com/contacts/8112310/objectLists/28908/filters
- Save and note ID

═══════════════════════════════════════════════════
STEP 7 — Build Master Audience List
═══════════════════════════════════════════════════
Create a final Contact-based list:
Name: [Event Name] [Year] — Master Audience

Combine ALL successfully built lists using OR logic:
- List 1 ID (Past Registrants)
- List 2 ID (Registrants + Web Visitors)
- Any communitySeg rebuilt list IDs (by their NEW ID only — never reference old communitySeg name)

Save and note the master list ID.

═══════════════════════════════════════════════════
STEP 8 — Final summary
═══════════════════════════════════════════════════
Print:
- List 1: name + HubSpot ID + number of filter conditions
- List 2: name + HubSpot ID + confirmed URL in Filter Group 2
- Any rebuilt communitySeg lists: name + HubSpot ID
- Master Audience: name + HubSpot ID

Then print:
## FLAGGED FOR REVIEW
(any items skipped, ambiguous event names, missing brand master list, etc.)
"""
