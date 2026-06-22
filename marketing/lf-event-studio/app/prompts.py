"""
Prompts for the two Claude phases.
Phase 1 — segment planning: runs from event-segment-planner/ (has SKILL.md)
Phase 2 — list building:    runs from hubspot-event-list-builder/ (has SKILL.md + references/)
"""

PLANNING_PROMPT = """Plan the HubSpot audience segment for this Linux Foundation event:

{url}

Follow the event-segment-planner skill instructions in SKILL.md exactly, working through all 4 steps:
1. Scrape the event page — extract event name, brand/foundation, location, dates, event type
2. Find previous edition emails in HubSpot — search for prior sends and check the LF Event \
Audiences Foundation OptIn Report
3. Analyse historical segmentation logic — reconstruct inclusion, exclusion, and opt-in \
filter strategy
4. Produce the full Segment Plan Report in the standard format

Narrate what you are doing at every sub-step so progress is visible.
End with: "Ready to proceed? Say yes and I'll build the segment in HubSpot."
"""

BUILDING_PROMPT = """Build the HubSpot audience lists for this Linux Foundation event.

Event URL: {url}

The segment planning phase is COMPLETE. The event page has already been scraped.
Do NOT re-scrape or re-fetch the event URL. All event details are in the plan below.

--- SEGMENT PLAN ---
{plan}
--- END SEGMENT PLAN ---
{qa_section}
=== CRITICAL RULES ===

RULE 1 — communitySeg lists must NEVER be used:
  Any list labelled communitySeg / community_seg in the plan must NOT be cloned,
  referenced, or included anywhere — not even indirectly.
  If the list represents past event registrants: rebuild an equivalent from scratch
  using HubSpot custom event filters ("Has completed event" filter type).
  Reference filter style: https://app.hubspot.com/contacts/8112310/objectLists/28908/filters
  If the exact event name is unclear, query Snowflake EVENT_REGISTRATIONS to find it.
  Name the rebuilt list: "[Event Name] Past Registrants (custom event)"
  If the list is NOT past registrations and cannot be cleanly rebuilt: skip it and flag it.

RULE 2 — Print the build plan first:
  Before creating any list in HubSpot, print "## BUILD PLAN" listing:
  - Every list you will create and its proposed name + filter logic
  - Each communitySeg list being replaced and what replaces it
  - Anything being skipped and why

RULE 3 — Build a master audience list last:
  After all individual lists are built, create one final master list:
  - Name: "[Event Name] [Year] — Master Audience"
  - Combines ALL successfully built lists using OR logic
  - NEVER references any communitySeg list as a source, even indirectly

RULE 4 — Flag uncertainty, never guess:
  If unsure about anything — skip and add to "## FLAGGED FOR REVIEW" at the end,
  explaining what was unclear and what information would resolve it.

=== BUILD STEPS ===

Use the hubspot-event-list-builder skill instructions in SKILL.md (starting from Step 2 —
skip Step 1 since scraping is already done). Work through these in order, narrating every sub-step:

Step 2 — Query Snowflake for past editions using the event name from the plan above.
         Also resolve any communitySeg event-name ambiguity at this step.
Step 3 — Look up brand master list ID from references/brand-master-lists.md.
Step 4 — Print "## BUILD PLAN"
Step 5 — Build List 1 — All Past Registrants (clone reference list, replace filters with
         one custom-event filter per Snowflake past edition; no communitySeg sources)
Step 6 — Build List 2 — Registrants + Web Visitors
         (List 1 OR page-visit AND brand master; no communitySeg sources)
Step 7 — For each communitySeg past-registrant list in the plan: rebuild as custom event list
Step 8 — Build Master Audience List (OR of Steps 5+6+7 results; zero communitySeg sources)
Step 9 — Print final summary with all list IDs + names, then "## FLAGGED FOR REVIEW" if applicable
"""
