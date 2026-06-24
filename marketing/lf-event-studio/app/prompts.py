"""
Prompts for the two agent phases.
Tools (web_fetch, hubspot_*, snowflake_query, read_reference_file) are
injected by the agentic loop — no subprocess or SKILL.md needed.
"""

PLANNING_PROMPT = """You are an experienced LF email audience strategist.
Plan the HubSpot audience segment for this Linux Foundation event:

{url}

Work through ALL 4 steps below, narrating each sub-step so progress is visible.

═══════════════════════════════════════════════════
STEP 1 — Scrape the event page
═══════════════════════════════════════════════════
Use web_fetch to fetch the URL above. Extract:
- Event name (full title, e.g. "KubeCon + CloudNativeCon North America 2026")
- Short name / slug (e.g. "KCNA", "OSSNA") — used for HubSpot search terms
- Foundation / brand (e.g. CNCF, The Linux Foundation, PyTorch, OpenSearch)
- Location (city + country/region)
- Event dates and year
- Event type (in-person conference, virtual, hybrid, summit)

═══════════════════════════════════════════════════
STEP 2 — Find previous edition emails in HubSpot
═══════════════════════════════════════════════════
Use hubspot_search_campaigns to find emails sent for the previous year's edition.
Try: event short name, foundation + event type, year variants (2025, 2024).

For each email found, note: name, subject, send date, list used, metrics.

Then use hubspot_search_lists to find the master list used for prior sends.
Note the list name, ID, and any opt-in filter pattern in the name.

═══════════════════════════════════════════════════
STEP 3 — Analyse historical segmentation logic
═══════════════════════════════════════════════════
Reconstruct the full audience strategy from prior emails and lists:

Inclusion sources: past registrants, web visitors, geographic segments,
topic interests, newsletter subscribers, foundation subscriber lists.

Exclusion sources: LF Events Global Opt Outs, LF Global Opt-Outs,
GDPR suppression, current registrants, internal LF contacts,
foundation-specific opt-outs.

Opt-in filter logic: whether applied, which variant (Foundation / LF Events /
LF Newsletter), and why.

Flag any communitySeg / community_seg lists found — note which are
past-registrant lists (rebuildable) vs other (skip and flag).

═══════════════════════════════════════════════════
STEP 4 — Produce the Segment Plan Report
═══════════════════════════════════════════════════
Write a complete structured report using this format:

### 📋 Event Segment Plan: [Event Name] [Year]

**Event summary** — name, foundation, location, dates, type.

**Historical context** — prior master list name, send counts, key changes, QA notes.

**Recommended master list name**
Follow foundation naming convention, e.g.:
`Q3 2026 - CNCF Foundation - KubeCon + CloudNativeCon North America Master (With Opt-In and Filters)`

**Inclusion strategy** — per source list: name, why it belongs, dynamic vs snapshot.
Group by: (1) Past registrants (2) Web visitors (3) Geographic (4) Topic/persona (5) Foundation subscribers.

**Exclusion strategy** — per suppression list: name and reason.
Always include: LF Events Global Opt Outs, LF Global Opt-Outs, GDPR Suppression (if EU in scope),
23Q1 LF Master Exclusion List, foundation opt-out, current registrants segment.

**Opt-in filter recommendation** — whether to apply, which variant, and why.

**Estimated list size** — based on prior counts, expected growth, opt-in filter impact.

**Recommended HubSpot list structure** — filter group sketch (OR/AND logic).

**communitySeg lists** — list each one found; classify as past-registrant (rebuildable) or other.

**Open questions / flags** — anything to confirm before building.

End with: "Ready to proceed? Say yes and I'll build the segment in HubSpot."
"""


BUILDING_PROMPT = """Build the HubSpot audience lists for this Linux Foundation event.

Event URL: {url}

The segment planning phase is COMPLETE — the event page has already been scraped.
Do NOT re-scrape or re-fetch the event URL.
All event details (name, brand, location, year, page URL) are in the Segment Plan below.

--- SEGMENT PLAN ---
{plan}
--- END SEGMENT PLAN ---
{qa_section}
═══════════════════════════════════════════════════
CRITICAL RULES (enforce throughout all steps)
═══════════════════════════════════════════════════
RULE 1 — communitySeg lists MUST NEVER be used:
  Any list labelled communitySeg / community_seg must NOT be referenced or included.
  Past-registrant communitySeg → rebuild using HubSpot behavioral event filters
    (filterType: BEHAVIORAL_EVENT). Name: "[Event Name] Past Registrants (custom event)".
  Non-registrant communitySeg → skip it and add to ## FLAGGED FOR REVIEW.

RULE 2 — Print ## BUILD PLAN before creating anything in HubSpot.
  List every list to create, each communitySeg replacement, and anything being skipped.

RULE 3 — Master list is last. OR of all built list IDs. Zero communitySeg sources.

RULE 4 — If unsure about anything → skip and add to ## FLAGGED FOR REVIEW.

═══════════════════════════════════════════════════
STEP 1 — Query Snowflake for past editions
═══════════════════════════════════════════════════
Use snowflake_query. Derive [event_term], [location_term], [current_year] from the
Segment Plan above — do NOT re-scrape the URL.

  SELECT DISTINCT EV.EVENT_NAME, EV.EVENT_ID
  FROM ANALYTICS.Silver_Segment.EVENT_REGISTRATIONS AS EV
  WHERE EV.EVENT_NAME ILIKE '%[event_term]%'
    AND EV.EVENT_NAME ILIKE '%[location_term]%'
    AND EV.EVENT_NAME NOT ILIKE '%[current_year]%'
  ORDER BY EV.EVENT_NAME;

Copy the exact EVENT_NAME strings — they are used verbatim as HubSpot filter values.
Also resolve any communitySeg event-name ambiguity here.

═══════════════════════════════════════════════════
STEP 2 — Look up brand master list ID
═══════════════════════════════════════════════════
Use read_reference_file("brand-master-lists.md") to look up the brand key from the plan.
If not found → use hubspot_search_lists("[brand] master") to find it, note the ID.

═══════════════════════════════════════════════════
STEP 3 — Print ## BUILD PLAN
═══════════════════════════════════════════════════
Before creating anything, print a section headed "## BUILD PLAN" listing:
- List 1 name + filter logic
- List 2 name + filter logic
- Each communitySeg list being replaced and its replacement name
- Anything being skipped and why

═══════════════════════════════════════════════════
STEP 4 — Build List 1: All Past Registrants
═══════════════════════════════════════════════════
First call hubspot_get_event_types() to find the fullyQualifiedName of the
custom event object (e.g. "pe8112310_event_registration").

Use hubspot_create_list with a filter branch containing one BEHAVIORAL_EVENT
filter per Snowflake past edition, all OR'd together in a single filter group.

Name: [Brand] - [Event Name] - All Past Registrants
Example: CNCF - KubeCon + CloudNativeCon India - All Past Registrants

filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{
          "filterType": "BEHAVIORAL_EVENT",
          "eventTypeId": "[fullyQualifiedName from event types]",
          "operator": "HAS_EVENT",
          "filterGroups": [
            {{
              "filters": [
                {{
                  "property": "hs_event_name",
                  "operator": "EQ",
                  "value": "[exact EVENT_NAME from Snowflake]"
                }}
              ]
            }}
          ]
        }}
      ]
    }}
  ]
  ... (one AND branch per Snowflake past edition)
}}

Save List 1 ID.

═══════════════════════════════════════════════════
STEP 5 — Build List 2: Registrants + Web Visitors
═══════════════════════════════════════════════════
Use hubspot_create_list with two OR filter groups:

Group 1 — past registrants:
  filterType: LIST_MEMBERSHIP, listId: [List 1 ID], operator: IN_LIST

Group 2 — web visitors (AND):
  filterType: PAGE_VIEW, value: [event URL from plan], operator: HAS_VIEWED_URL
  filterType: LIST_MEMBERSHIP, listId: [brand master list ID], operator: IN_LIST

Name: [Brand] - [Event Name] - Registrants + Web Visitors

═══════════════════════════════════════════════════
STEP 6 — Rebuild communitySeg past-registrant lists
═══════════════════════════════════════════════════
For each communitySeg past-registrant list in the plan, use hubspot_create_list
with BEHAVIORAL_EVENT filters (same pattern as Step 4, appropriate event names).
Name: [Event Name] Past Registrants (custom event)
Save each new list ID.

═══════════════════════════════════════════════════
STEP 7 — Build Master Audience List
═══════════════════════════════════════════════════
Use hubspot_create_list. OR together ALL successfully built list IDs
(List 1 ID, List 2 ID, any rebuilt communitySeg IDs).

Name: [Event Name] [Year] — Master Audience
Use LIST_MEMBERSHIP filters, one per list. NEVER reference any communitySeg list.

═══════════════════════════════════════════════════
STEP 8 — Final summary
═══════════════════════════════════════════════════
Print a table of all created lists:
| List name | HubSpot ID | Notes |

Then print:
## FLAGGED FOR REVIEW
(skipped communitySeg lists, ambiguous event names, missing IDs, etc.)
"""
