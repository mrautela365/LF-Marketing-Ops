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

Also search for each of the inclusion lists referenced in prior sends:
past-registrant lists, geographic lists, topic/persona lists, newsletter lists, etc.
Use hubspot_get_list on any list IDs found to inspect their filter logic.

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
Group by and number each list:
  1. Past registrants (BEHAVIORAL_EVENT filter)
  2. Web visitors (PAGE_VIEW + brand master)
  3. Geographic segments (if applicable)
  4. Topic / persona lists (if applicable)
  5. Foundation / newsletter subscribers (if applicable)
  6. Any other inclusion lists from prior sends

For each inclusion list, state:
  - Proposed HubSpot list name
  - Filter type (BEHAVIORAL_EVENT / PAGE_VIEW / LIST_MEMBERSHIP / property)
  - Why it belongs

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


BUILDING_PROMPT = """Build ALL the HubSpot audience lists for this Linux Foundation event.

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
RULE 1 — Build EVERY inclusion list from the plan, not just 2.
  Read the "Inclusion strategy" section carefully. Create one HubSpot list per
  numbered inclusion source. Do not skip any.

RULE 2 — communitySeg lists MUST NEVER be used as sources:
  Any list labelled communitySeg / community_seg must NOT be referenced or included.
  Past-registrant communitySeg → rebuild using BEHAVIORAL_EVENT filters.
  Non-registrant communitySeg → skip and add to ## FLAGGED FOR REVIEW.

RULE 3 — Print ## BUILD PLAN before creating anything in HubSpot.
  Number each list to create. State its filter type and logic.

RULE 4 — MASTER LIST IS MANDATORY. You MUST always build the master list as the final step.
  Even if some inclusion lists failed, build the master from whatever IDs you DO have.
  Never end without creating the master list. It is the primary deliverable.

RULE 5 — After EVERY successful hubspot_create_list call print:
  ✅ [List name] created — ID: [listId] — [hubspot_url]

RULE 6 — If unsure about anything → skip and add to ## FLAGGED FOR REVIEW.

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

═══════════════════════════════════════════════════
STEP 2 — Look up brand master list ID
═══════════════════════════════════════════════════
Use read_reference_file("brand-master-lists.md") to look up the brand key from the plan.
If not found → use hubspot_search_lists("[brand] master") to find it, note the ID.

Call hubspot_get_event_types() now so the fullyQualifiedName is ready for Step 4.
Look for a name containing "event_registration". The value looks like "pe8112310_event_registration".

═══════════════════════════════════════════════════
STEP 3 — Print ## BUILD PLAN
═══════════════════════════════════════════════════
Print a numbered plan of EVERY list you will create, derived from the
Inclusion strategy in the Segment Plan. Include:
- List number and name
- Filter type(s)
- Why it's needed
- Any communitySeg list it replaces (→ BEHAVIORAL_EVENT rebuild)
- Anything being SKIPPED and why

═══════════════════════════════════════════════════
STEP 4 — Build ALL inclusion lists (one per inclusion source)
═══════════════════════════════════════════════════
Create every list from your BUILD PLAN in order. Use the correct filter type for each:

── BEHAVIORAL_EVENT (past registrants) ──────────────────────
Use for: past-registrant lists, communitySeg rebuilds.
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
          "eventTypeId": "[exact fullyQualifiedName e.g. pe8112310_event_registration]",
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
  ],
  "filters": []
}}
Add one AND branch per past edition. All inside the top OR.

── PAGE_VIEW + LIST_MEMBERSHIP (web visitors) ───────────────
Use for: web-visitor + brand-master combination.
filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{
          "filterType": "PAGE_VIEW",
          "value": "[event URL]",
          "operator": "HAS_VIEWED_URL"
        }},
        {{
          "filterType": "LIST_MEMBERSHIP",
          "listId": "[brand master list ID as string]",
          "operator": "IN_LIST"
        }}
      ]
    }}
  ],
  "filters": []
}}

── LIST_MEMBERSHIP (reference existing HubSpot lists) ───────
Use for: geographic lists, topic/persona lists, newsletter lists already in HubSpot.
Use hubspot_search_lists to find the existing list ID first.
filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [
        {{
          "filterType": "LIST_MEMBERSHIP",
          "listId": "[existing HubSpot list ID as string]",
          "operator": "IN_LIST"
        }}
      ]
    }}
  ],
  "filters": []
}}

After EACH successful hubspot_create_list call, print:
✅ [List name] created — ID: [listId] — [hubspot_url]

Save all created list IDs.

═══════════════════════════════════════════════════
STEP 5 — Look up standard suppression list IDs
═══════════════════════════════════════════════════
Suppressions are NOT added to the master list filter — they are applied separately
at HubSpot email send time as suppression lists. Your job here is to find their IDs
and report them so they can be added when scheduling the email.

Use hubspot_search_lists to find the current list ID for each standard suppression.
Search by the key term shown — take the most recently updated match.

Standard suppressions to look up:
  "LF Global Opt-Outs"           → LF Global Opt-Outs
  "LF Europe Global Opt-Outs"    → LF Europe Global Opt-Outs
  "LF Events GDPR Suppression"   → most recent quarterly (e.g. 25Q2 - LF Events - GDPR Suppression)
  "LF Europe GDPR Suppression"   → most recent (e.g. 25Q2 - LF Europe - GDPR Suppression)
  "LF Master Exclusion"          → 23Q1 - LF - Master Exclusion List or similar
  "LF Events Suppression List"   → most recent (e.g. 23Q3 - LF Events - Suppression List)

Also look up any event-specific suppressions from the Segment Plan
(current registrants of this event, internal LF contacts, foundation opt-outs, etc.).

Print the found suppression list IDs — they will be added to the ## SUPPRESSION LISTS section.
If a search returns no match, note it in ## FLAGGED FOR REVIEW.

═══════════════════════════════════════════════════
STEP 6 — Build Master Audience List (MANDATORY — never skip)
═══════════════════════════════════════════════════
THIS STEP IS REQUIRED. You must always execute it, even if only some inclusion lists succeeded.

The master list is a PURE OR of all successfully built inclusion list IDs.
Do NOT add any AND NOT or suppression conditions to the filterBranch.
Suppressions are handled at email send time, not inside the list.

filterBranch structure:
{{
  "filterBranchType": "OR",
  "filterBranches": [
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [{{ "filterType": "LIST_MEMBERSHIP", "listId": "[inclusion_id_1]", "operator": "IN_LIST" }}]
    }},
    {{
      "filterBranchType": "AND",
      "filterBranches": [],
      "filters": [{{ "filterType": "LIST_MEMBERSHIP", "listId": "[inclusion_id_2]", "operator": "IN_LIST" }}]
    }}
    ... (one AND branch per successfully built inclusion list)
  ],
  "filters": []
}}

Name: follow the recommended master list name from the Segment Plan.
If none given: [Quarter] [Year] - [Brand] - [Event Name] Master (With Opt-In and Filters)

After success print:
🏆 Master list created — ID: [listId] — [hubspot_url]

If this step fails for any reason, print the exact HubSpot error and add it to ## FLAGGED FOR REVIEW.
DO NOT end without attempting to create the master list.

═══════════════════════════════════════════════════
STEP 7 — Final summary
═══════════════════════════════════════════════════
Print a markdown table of ALL created lists:

| # | List name | HubSpot ID | Link | Notes |
|---|-----------|------------|------|-------|

Then print a clearly separated section:

## SUPPRESSION LISTS
Add ALL of the following as suppression lists when scheduling the email send in HubSpot:

| List name | HubSpot ID | Link |
|-----------|------------|------|
(one row per suppression found in Step 5)

Then print:
## FLAGGED FOR REVIEW
(skipped communitySeg lists, ambiguous event names, missing IDs, unresolvable filters, etc.)
"""
