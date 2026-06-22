"""
Prompts for the two Claude phases.
Skill instructions are embedded inline so claude -p doesn't need to read SKILL.md.
Phase 1 runs from event-segment-planner/ (references, OptIn report context).
Phase 2 runs from hubspot-event-list-builder/ (references/brand-master-lists.md).
"""

PLANNING_PROMPT = """You are an experienced LF email audience strategist.
Plan the HubSpot audience segment for this Linux Foundation event:

{url}

Work through ALL 4 steps below, narrating every sub-step so progress is visible.

═══════════════════════════════════════════════════
STEP 1 — Scrape the event page
═══════════════════════════════════════════════════
Use web_fetch or mcp__Claude_in_Chrome__navigate + get_page_text to fetch the URL above.

Extract:
- Event name (full title, e.g. "KubeCon + CloudNativeCon North America 2026")
- Short name / slug (e.g. "KCNA", "OSSNA") — for HubSpot searching
- Foundation / brand (e.g. CNCF, The Linux Foundation, PyTorch)
- Location (city + country/region)
- Event dates and year
- Event type (in-person, virtual, hybrid, summit, webinar)

If the page is client-rendered, use Chrome navigate + get_page_text.

═══════════════════════════════════════════════════
STEP 2 — Find previous edition emails in HubSpot
═══════════════════════════════════════════════════
Search HubSpot email history for the previous year's edition.

Use HubSpot MCP search tools. Try: event short name, foundation name + event type, year variants.

For each email found, note: name, subject, send date, audience/list used, open/click metrics.

Also check the LF Event Audiences Foundation OptIn Report (in your context) — extract:
- Master list name used in prior sends
- Previous list count vs current list count
- Whether opt-in filters were applied
- QA notes and report links

═══════════════════════════════════════════════════
STEP 3 — Analyse historical segmentation logic
═══════════════════════════════════════════════════
Reconstruct the full audience strategy:

Inclusion sources: past registrants, web visitors, geographic segments, topic interests,
newsletter subscribers, SSO users by job title/country, foundation subscriber lists.

Exclusion sources: LF Events Global Opt Outs, LF Global Opt-Outs, GDPR suppression,
current registrants, internal LF contacts, foundation-specific opt-outs.

Opt-in filter logic: whether applied, which variant (Foundation / LF Events / LF Newsletter).

═══════════════════════════════════════════════════
STEP 4 — Produce the Segment Plan Report
═══════════════════════════════════════════════════
Write a complete structured report:

### 📋 Event Segment Plan: [Event Name] [Year]

**Event summary** — name, foundation, location, dates, event type.

**Historical context** — previous master list name, prior/current send counts, key changes,
QA notes.

**Recommended master list name** — follow foundation naming convention, e.g.:
`Q2 2026 - CNCF Foundation - KubeCon + CloudNativeCon North America Master (With Opt-In and Filters)`

**Inclusion strategy** — for each source list: name, why it belongs, dynamic vs snapshot.
Group by: (1) Past registrants (2) Web visitors (3) Geographic (4) Topic/persona (5) Foundation subscribers.

**Exclusion strategy** — for each suppression list: name and reason.
Always include: LF Events Global Opt Outs, LF Global Opt-Outs, 24Q1 GDPR Suppression
(if European contacts in scope), 23Q1 LF Master Exclusion List, foundation opt-out,
current registrants segment.

**Opt-in filter recommendation** — whether to apply, which variant, and why.

**Estimated list size** — based on prior counts, expected growth, opt-in filter impact.

**Recommended HubSpot list structure** — filter group sketch (OR/AND logic).

**communitySeg lists** — explicitly list any communitySeg / community_seg lists found.
Flag each: is it past registrants (can be rebuilt via custom event filter) or other?

**Open questions / flags** — anything to confirm before building.

End with: "Ready to proceed? Say yes and I'll build the segment in HubSpot."
"""

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
