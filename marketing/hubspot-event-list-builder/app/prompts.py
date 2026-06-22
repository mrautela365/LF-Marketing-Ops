LIST_BUILDER_PROMPT = """Build the HubSpot event audience lists for this Linux Foundation event:

{url}

Follow the hubspot-event-list-builder skill instructions exactly, working through all 6 steps:
1. Scrape the event page to extract name, edition, brand key, and Snowflake search terms
2. Query Snowflake for all past editions (excluding the current year)
3. Look up the brand master list ID
4. Clone the reference list and build List 1 — All Past Registrants
5. Build List 2 — Registrants + Web Visitors
6. Confirm and report both list IDs, names, and filter counts

Narrate what you are doing at every sub-step.
"""

LIST_BUILDER_PROMPT_WITH_PLAN = """Build the HubSpot event audience lists for this Linux Foundation event:

{url}

A segment plan has already been produced for this event. Use it as your reference:

--- SEGMENT PLAN ---
{plan}
--- END SEGMENT PLAN ---

=== CRITICAL RULES ===

RULE 1 — communitySeg lists must NEVER be used:
  Any list in the segment plan labelled "communitySeg" (or community_seg / CommunitySeg) must NOT
  be cloned, referenced, or included anywhere. If a communitySeg list represents past event
  registrants, rebuild an equivalent list from scratch using HubSpot custom event filters:
    • Find the matching event name in Snowflake (EVENT_REGISTRATIONS table) if unsure
    • Create the list using "Has completed event" filter, referencing that Snowflake event name
    • Reference filter style: https://app.hubspot.com/contacts/8112310/objectLists/28908/filters
    • Name the rebuilt list: "[Event Name] Past Registrants (custom event)"
  If a communitySeg list is for something other than past registrants (e.g. web visitors,
  demographics) and you cannot rebuild an equivalent — skip it and flag it.

RULE 2 — Show your build plan before starting:
  Before creating any list in HubSpot, print a clear plan section titled "## BUILD PLAN" listing:
    • Each list you will create, with its proposed name and filter logic
    • Which communitySeg lists you are replacing and what you are replacing them with
    • Anything you are skipping and why
  Then proceed to build.

RULE 3 — Build a master audience list last:
  After all individual lists are built, create one final master list that:
    • Combines ALL successfully built lists using OR logic
    • Never references any communitySeg list as a source — not even indirectly
    • Is named: "[Event Name] [Year] — Master Audience"
  If fewer than two individual lists were successfully built, note this and skip the master.

RULE 4 — Flag anything uncertain:
  If at any point you are unsure (event name match, filter logic, list ID) — do NOT guess.
  Skip that item, query Snowflake or HubSpot for clarification if possible, and if still
  unclear add it to a final "## FLAGGED FOR REVIEW" section explaining what was unclear
  and what information would resolve it.

=== BUILD STEPS ===

Work through these steps in order, narrating every sub-step:

1. Scrape the event page — confirm event name, brand, dates, edition
2. Query Snowflake for all past editions (excluding current year)
   — also use results to resolve any communitySeg event name ambiguity
3. Look up brand master list ID
4. Print "## BUILD PLAN" (see Rule 2)
5. Build List 1 — All Past Registrants (custom event filter per past edition)
6. Build List 2 — Registrants + Web Visitors
7. For each communitySeg past-registrant list in the plan: rebuild as custom-event list
8. Build Master Audience list combining all of the above (no communitySeg sources)
9. Print final summary: all list IDs + names, and "## FLAGGED FOR REVIEW" if applicable
"""
