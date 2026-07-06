---
name: hubspot-event-list-builder
description: >
  Builds HubSpot audience lists for a Linux Foundation event given its URL.
  Scrapes the event page for brand/name, queries Snowflake for all past editions
  of that event, then creates two lists in HubSpot by cloning the reference
  example list and updating filters: (1) All Past Registrants filtered by custom
  event synced from Snowflake, and (2) Registrants + Web Visitors combining
  List 1 OR web visitor to the event page (no master-list gate — that gate is
  only required for regional/geographic contact filters). Always use this
  skill when the user provides an
  events.linuxfoundation.org URL and wants to build or prepare HubSpot lists,
  audience segments, or promotion lists for that event — even if they say things
  like "prep the lists", "set up audiences", "build the list for this event", or
  paste a KubeCon/CloudNativeCon/Open Source Summit URL.
---

# HubSpot Event List Builder

Build two HubSpot audience lists for any Linux Foundation event, starting from just the event URL.
The approach: query Snowflake for all past edition names, then clone the reference example list in HubSpot and replace the filters with the correct event values.

## Overview of output

**List 1 — Past Registrants**
Name: `[Brand] - [Event Name] - All Past Registrants`
Filter: OR across all past editions → Custom Event `[event_name]` synced from Snowflake

**List 2 — Registrants + Web Visitors**
Name: `[Brand] - [Event Name] - Registrants + Web Visitors`
Filter Group 1 (OR): Member of List 1
Filter Group 2 (OR): Web visitor to the event page URL (no master-list gate)

---

## Step 1 — Scrape the event page

Fetch the provided event URL using the web fetch tool.

Extract:
- **Event name** — the full title (e.g., "KubeCon + CloudNativeCon India")
- **Edition** — location and/or year (e.g., "India 2025", "North America 2024")
- **Event URL** — the exact URL (needed for web visitor filter in Step 4)

Derive the **brand key** by checking the URL slug against `references/brand-master-lists.md`.
Example: `kubecon-cloudnativecon-india` → brand key `cncf`.

Derive two **Snowflake search terms**:
- **Event term** — the core event name without location (e.g., `kubecon`)
- **Location term** — the country/region from the page (e.g., `india`, `europe`, `north america`)

Note the **current event year** (from the event date on the page) — this will be excluded from the Snowflake query.

Example: "KubeCon + CloudNativeCon India, June 2026" → event term `kubecon`, location term `india`, exclude year `2026`.

---

## Step 2 — Query Snowflake for past editions

Open Snowflake in Chrome (app.snowflake.com) and run:

```sql
SELECT DISTINCT EV.EVENT_NAME, EV.EVENT_ID
FROM ANALYTICS.Silver_Segment.EVENT_REGISTRATIONS AS EV
WHERE EV.EVENT_NAME ILIKE '%[event_term]%'
  AND EV.EVENT_NAME ILIKE '%[location_term]%'
  AND EV.EVENT_NAME NOT ILIKE '%[current_year]%'
ORDER BY EV.EVENT_NAME;
```

**Example for KubeCon + CloudNativeCon India 2026:**
```sql
SELECT DISTINCT EV.EVENT_NAME, EV.EVENT_ID
FROM ANALYTICS.Silver_Segment.EVENT_REGISTRATIONS AS EV
WHERE EV.EVENT_NAME ILIKE '%kubecon%'
  AND EV.EVENT_NAME ILIKE '%india%'
  AND EV.EVENT_NAME NOT ILIKE '%2026%'
ORDER BY EV.EVENT_NAME;
```

Collect the full list of distinct `EVENT_NAME` values. These exact strings are used verbatim as HubSpot filter values (the Snowflake → HubSpot sync preserves them), so copy them precisely.

If you cannot access Snowflake, ask the user to provide the past event name list manually.

---

## Step 3 — Clone reference list and build List 1: All Past Registrants

The reference example list lives at:
`https://app.hubspot.com/contacts/8112310/objectLists/26624/filters`

Open it first to confirm the correct custom event object name and property names used in the filters.

Then clone it:
1. Open the reference list → click the **⋮ menu → Clone**
2. Rename the clone: `[Brand] - [Event Name] - All Past Registrants`
   Example: `CNCF - KubeCon + CloudNativeCon India - All Past Registrants`

Now replace the filters in the cloned list. Delete any existing filter conditions and rebuild with one OR condition per past edition from Snowflake:
- Filter type: Custom event (same event object as in the reference list)
- Property: `event_name`
- Operator: is equal to
- Value: `[exact EVENT_NAME from Snowflake]`

All past editions are OR'd together in a single filter group. Save the list and note the new list ID.

---

## Step 4 — Build List 2: Registrants + Web Visitors

Create a second new **Contact-based** list in HubSpot (or clone any simple existing list as a starting point).

**List name**: `[Brand] - [Event Name] - Registrants + Web Visitors`
Example: `CNCF - KubeCon + CloudNativeCon India - Registrants + Web Visitors`

**Filter structure** — two filter groups joined by OR:

**Filter Group 1** (past registrants):
- Member of list: [List 1 ID from Step 3]

**Filter Group 2** (web visitors):
- Has visited page URL = `[the event URL from Step 1]`
  (Use HubSpot's "Visited URL" / "Page view" web activity filter, exact match or contains)
  No master-list gate — a page view alone qualifies. (The master-list gate is only
  required when building regional/geographic contact filters, which this skill doesn't build.)

Save the list and note the new list ID.

---

## Step 5 — Confirm and report

After both lists are saved, report:
- List 1 name + HubSpot list ID + count of filter conditions added
- List 2 name + HubSpot list ID + confirmed URL in Filter Group 2
- The full list of EVENT_NAME values that were added as filters

If anything looks off (filter values don't match expected naming, clone failed, etc.), flag it so the user can verify before lists go live.
