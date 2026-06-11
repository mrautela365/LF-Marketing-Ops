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

A segment plan has already been produced for this event. Use it as your reference — it contains
the recommended master list name, inclusion strategy, exclusion stack, and filter logic:

--- SEGMENT PLAN ---
{plan}
--- END SEGMENT PLAN ---

Follow the hubspot-event-list-builder skill instructions exactly, working through all 6 steps:
1. Scrape the event page to extract name, edition, brand key, and Snowflake search terms
   (use the event name / brand from the segment plan above to confirm)
2. Query Snowflake for all past editions (excluding the current year)
3. Look up the brand master list ID (use the master list name from the segment plan if provided)
4. Clone the reference list and build List 1 — All Past Registrants
5. Build List 2 — Registrants + Web Visitors
6. Confirm and report both list IDs, names, and filter counts

Narrate what you are doing at every sub-step.
"""
