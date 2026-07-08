# Region Map

Used to determine an event's broader region, which drives the 4 standard
regional-expansion inclusion lists (Education Enrolled / Event Registered /
Expanded Web Visitors / Regional Event Registrants — see PLAN/BUILD prompts).

| Region | Countries |
|--------|-----------|
| APAC | South Korea, Japan, China, India, Singapore, Australia, Taiwan, Indonesia, Malaysia, Philippines, Vietnam, Thailand, New Zealand, Hong Kong |
| EMEA | United Kingdom, Germany, France, Netherlands, Spain, Italy, Ireland, Switzerland, Sweden, Poland, South Africa, Israel, UAE, Saudi Arabia |
| NA | United States, Canada, Mexico |
| LATAM | Brazil, Argentina, Chile, Colombia, Peru |

## How to use

1. Look up the event's own country in this table to get its region.
2. "Sibling events" for the Expanded Web Visitors and Regional Event
   Registrants lists are OTHER LF/CNCF/foundation events (any brand) held in
   OTHER countries of the SAME region during the current event cycle (same
   year/half) — never in the event's own country (that's already covered by
   groups 1-3).
3. Discover sibling events dynamically — do not assume a fixed list:
   - `hubspot_search_campaigns` / `hubspot_search_lists` with the region name
     and current year/quarter as keywords.
   - Snowflake: `SELECT DISTINCT EVENT_NAME FROM
     ANALYTICS.Silver_Segment.EVENT_REGISTRATIONS WHERE EVENT_NAME ILIKE
     '%[sibling country]%' AND EVENT_NAME ILIKE '%[current_year]%'` — run once
     per other country in the region, or OR them together.
4. For Expanded Web Visitors, pick the single most relevant/nearest sibling
   event (usually the closest by date or same brand family) for its page URL.
5. For Regional Event Registrants, include ALL sibling events found in step 3
   as one CONTAINS list (not one branch per event).
6. If a foundation has no LF Education presence or no sibling events in its
   region for this cycle, note it in "Open questions / flags" as N/A rather
   than forcing an empty/irrelevant list.
7. Sibling events (and Education Enrolled / Event Registered history) are also
   filtered by product/technology domain bucket (HARDWARE vs SOFTWARE/AI) per
   RULE 9 in the BUILDING prompt — a sibling event in the right region/quarter
   can still be dropped if its domain bucket doesn't match the current event.
