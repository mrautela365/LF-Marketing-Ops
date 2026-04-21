---
name: segment-weekly-pulse
description: >
  Generate a weekly Twilio Segment activity summary: total work done across the week by each team member, trends, workstream progress, and week-over-week comparisons. Trigger on: "segment weekly pulse", "weekly segment report", "what happened this week in Segment", "end of week segment status", "weekly recap", "segment week in review", "weekly progress", or "run the weekly pulse".
---

# Twilio Segment Weekly Pulse

Generate a weekly activity summary for the Linux Foundation Marketing Ops Twilio Segment
workspace. While the daily pulse captures individual actions, the weekly pulse zooms out
to show patterns, productivity trends, workstream momentum, and the overall arc of the
week — giving the ops lead a complete picture of how the team moved.

---

## Step 1: Determine the Reporting Week

Default to the **current week** (Monday through today). If the user says "last week",
use the previous Monday–Friday. If they specify a date range, use that.

Always state the exact date range at the top of the report.

---

## Step 2: Pull the Segment Audit Trail for the Full Week

### 2a. Navigate to the Audit Trail

Open: `https://app.segment.com/linuxfoundation/settings/audit-trail`

Workspace: **Linux Foundation Marketing Ops** at namespace `/linuxfoundation/`.

### 2b. Collect All Events for the Week

The audit trail shows events newest-first, ~25 per page. For a full week you'll likely
need to paginate multiple times using the **"Older Events"** button. Keep collecting
until you've passed the Monday start of the reporting week.

This is the most time-intensive step — be thorough. A week can have 50–100+ events.

### 2c. Timestamp Handling

Convert all UTC timestamps to Pacific Time (PT/PDT). Group events by day for the
day-by-day breakdown.

---

## Step 3: Analyze and Aggregate

### 3a. Known Team Members

| Name | Email | Primary Workstream |
|------|-------|--------------------|
| **Shiv Inde** | sinde@contractor.linuxfoundation.org | Audience builds, HubSpot upsert mappings, event audiences |
| **Prasad Shetty** | pshetty@contractor.linuxfoundation.org | Audience builds, rETL models, linked audiences |
| **Liz Cart** (shows as "Liz") | lcart@contractor.linuxfoundation.org | Attribution pipeline, ad platform conversions, conversion tracking |
| **Misha Rautela** | mrautela@linuxfoundation.org | Ops lead |

### 3b. Event Categories

Same as daily pulse:

| Category | Event Types |
|----------|------------|
| **Audience Management** | Audience created, modified, deleted |
| **Destination Config** | Destination created, modified, enabled, disabled |
| **Destination Mappings** | Destination mapping created, modified, enabled, disabled |
| **Reverse ETL** | Reverse etl model created, modified, deleted |
| **Source Config** | Source created, modified, enabled, disabled |
| **Access & Admin** | User management, workspace settings |

---

## Step 4: Present the Weekly Pulse

### 4a. Header

```
## Segment Weekly Pulse — Week of [Month Day–Day, Year]
**Workspace:** Linux Foundation Marketing Ops
**Period:** [Monday date] – [Friday/today date] (Pacific Time)
**Total actions:** [X] by [Y] team members across [Z] days
```

### 4b. Week at a Glance

A 3-4 sentence narrative of the week's story — what moved, what's new, what's the
overall trajectory:

> This was a productive week focused on two fronts: Liz stood up the full attribution
> pipeline (connecting both Web-Prod and Snowflake to the Attribution App), while Prasad
> continued audience building with 8 new audiences including the education benefit segment.
> Shiv focused on HubSpot mappings, connecting 4 audiences to upsert destinations.
> Total: 47 actions across 5 days.

### 4c. Team Member Weekly Scoreboard

| Team Member | Mon | Tue | Wed | Thu | Fri | Week Total | Top Category |
|-------------|-----|-----|-----|-----|-----|------------|-------------|
| Liz Cart | 5 | 0 | 3 | 3 | 0 | 11 | Destinations (8) |
| Prasad Shetty | 0 | 6 | 8 | 5 | 2 | 21 | Audiences (14) |
| Shiv Inde | 3 | 4 | 2 | 0 | 3 | 12 | Mappings (7) |
| Misha Rautela | 0 | 0 | 0 | 0 | 0 | 0 | — |
| **Total** | **8** | **10** | **13** | **8** | **5** | **44** | |

### 4d. Category Breakdown for the Week

| Category | Mon | Tue | Wed | Thu | Fri | Total | % of Week |
|----------|-----|-----|-----|-----|-----|-------|-----------|
| Audiences | 2 | 4 | 6 | 3 | 1 | 16 | 36% |
| Destinations | 3 | 0 | 3 | 3 | 0 | 9 | 20% |
| Mappings | 2 | 4 | 2 | 0 | 3 | 11 | 25% |
| rETL | 1 | 2 | 2 | 2 | 1 | 8 | 18% |
| Other | 0 | 0 | 0 | 0 | 0 | 0 | 0% |

### 4e. Day-by-Day Highlights

For each day that had activity, provide a 1-2 line summary of the key work:

| Day | Highlights |
|-----|-----------|
| **Mon 04/07** | Liz configured ad platform conversion mappings (Google, LinkedIn, Reddit, Bing). Shiv modified OSFF London enrollment audience. |
| **Tue 04/08** | Shiv updated HubSpot upsert mapping. Prasad started education benefit audience work. |
| **Wed 04/09** | Liz created Web-Prod → Attribution App destination. Prasad rebuilt education benefit audience (deleted v1, created v2 with new rETL model). |
| **Thu 04/10** | Liz created and enabled Snowflake → Attribution App destination (351 events, 100% delivery). |
| **Fri 04/11** | [pending or report what happened] |

### 4f. Workstream Progress — Week in Review

This is the strategic view. For each major workstream, summarize where it started the
week and where it ended:

| Workstream | Owner | Start of Week | End of Week | Status |
|------------|-------|--------------|-------------|--------|
| Attribution Pipeline | Liz | No attribution destinations existed | Both Web-Prod and Snowflake connected to Attribution App, Snowflake delivering events | 🟢 Major progress |
| Ad Platform Conversions | Liz | Conversion destinations existed but mappings incomplete | Google, LinkedIn, Reddit, Bing all mapped to Event Registered | 🟢 Completed this week |
| Audience Builds | Shiv/Prasad | Ongoing | 3 new audiences created, education benefit segment rebuilt | 🟢 Active |
| CommunitySeg Migration | Team | Gap analysis complete | No migration-specific work this week | 🟡 Stalled |

Use these status indicators:
- 🟢 **Major progress** — meaningful advancement this week
- 🟢 **Active** — routine ongoing work continued
- 🟡 **Slow/Stalled** — little or no progress
- 🔴 **Blocked** — something is preventing progress
- ✅ **Completed** — workstream finished this week

### 4g. Notable Events & Flags

Bullet the most important things the ops lead should know:

- **New infrastructure stood up** — list any new sources, destinations, or integrations
  that didn't exist at the start of the week
- **Deletions this week** — anything removed (with who deleted it and when)
- **Rebuild patterns** — create-delete-recreate sequences that suggest iteration or
  troubleshooting
- **Inactive days** — days where specific team members had zero activity (could indicate
  PTO, focus on other systems, or blockers)
- **Highest-volume day** — which day had the most activity and why

### 4h. Week-over-Week Comparison (if data available)

If you have access to the previous week's data (from conversation history or by
paginating further back in the audit trail), include a comparison:

| Metric | This Week | Last Week | Change |
|--------|-----------|-----------|--------|
| Total actions | 44 | 32 | +38% |
| Active team members | 3 | 2 | +1 |
| Audiences created | 5 | 3 | +2 |
| New destinations | 2 | 0 | +2 |

If previous week data isn't available, skip this section and note: "Week-over-week
comparison will be available starting next week."

---

## Step 5: Recommendations for Next Week

End with 3-5 forward-looking items based on the week's patterns:

- **What to continue** — workstreams with good momentum
- **What to unblock** — stalled items that need attention
- **What to verify** — new infrastructure that should be validated (e.g., "Confirm
  Web-Prod Attribution destination is receiving data")
- **What to plan** — upcoming work visible from the trajectory

---

## Important Notes

- **Pagination is critical.** A full week will span many audit trail pages. Don't stop
  after the first page — keep clicking "Older Events" until you've covered the full week.
- **Timestamps in Pacific Time.** Always convert UTC → PT for display.
- **The weekly pulse is about patterns, not individual events.** The daily pulse lists
  every action. The weekly pulse should aggregate and tell the story of the week.
- **Connect to business outcomes.** When possible, explain why workstream progress
  matters — e.g., "Attribution pipeline completion means we can now measure which ad
  channels drive registrations."
- **Don't fabricate week-over-week data.** If you don't have last week's numbers, say so.
