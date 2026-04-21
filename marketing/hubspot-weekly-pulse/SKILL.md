---
name: hubspot-weekly-pulse
description: >
  Generate a weekly HubSpot activity summary with trend comparisons, team productivity rankings,
  pipeline movement, segment growth, and email outreach performance across the full week. Trigger on:
  "weekly pulse", "HubSpot weekly", "weekly recap", "what happened this week in HubSpot", "weekly
  report", "HubSpot week in review", "weekly status", "this week's HubSpot activity", "end of week
  report", "Friday recap", "weekly roundup". Also trigger for "compare this week", "week over week",
  or asking about a specific person's weekly HubSpot output.
---

# HubSpot Weekly Pulse

Generate a weekly activity summary from HubSpot that shows the full picture of what the team
accomplished over the week, highlights trends compared to the previous week, and surfaces patterns
that a daily view would miss.

## When to Use

This skill covers a **full week** of HubSpot activity. Use it for end-of-week recaps, Monday
morning reviews of the prior week, or anytime someone asks "what happened this week." It is NOT
for creating records, sending emails, or managing campaigns.

## Step 1: Determine the Date Range

- Default: **Monday through today** of the current week (e.g., Mon Apr 6 – Fri Apr 10)
- "last week" — previous Monday through Sunday
- "week of April 1" — that specific Mon–Sun window
- Also calculate the **prior week range** for week-over-week comparison

Use UTC timestamps for all HubSpot API filters.

## Step 2: Authenticate and Verify Access

Call `get_user_details` to confirm the connected HubSpot account and the user's owner ID.

## Step 3: Pull CRM Activity for Both Weeks

Run queries for **this week** and **prior week** in parallel to enable comparison.
For each week, pull totals for:

### 3a. Contacts
- Object type: `contacts`, filter on `createdate`, just need `total` count for each week
- Pull top 10 for this week with properties: `firstname`, `lastname`, `email`, `createdate`

### 3b. Deals
- Object type: `deals`, filter on `createdate`
- Properties: `dealname`, `dealstage`, `amount`, `createdate`, `hubspot_owner_id`
- Pull all for this week (limit 200) — need full list for pipeline analysis and total dollar value
- For prior week, just need `total` count and sum of amounts

### 3c. Tickets
- Object type: `tickets`, filter on `hs_createdate`
- Total count for each week

### 3d. Tasks
- Object type: `TASK`, filter on `hs_createdate`
- Total count for each week
- Pull this week's tasks with `hubspot_owner_id` to show tasks by person

**Property name reminder:** Contacts and deals use `createdate`. Tickets, tasks, emails, and lists use `hs_createdate`.

## Step 4: Pull Audience & Segment Work

### 4a. New Segments This Week
- Object type: `OBJECT_LIST`, filter `hs_createdate` for this week's range
- Properties: `hs_list_name`, `hs_list_size`, `hs_createdate`, `hs_is_active_list`, `hs_created_by_user_id`
- Pull all (limit 200)
- Also pull prior week total for comparison

### 4b. Resolve Creators
- Same user ID vs owner ID workaround as the daily pulse
- Group by creator and show daily breakdown within the week

## Step 5: Pull Email Activity

### 5a. Sent Emails This Week
- Object type: `EMAIL`, filter `hs_createdate` for this week AND `hs_email_sent_count > 0`
- Properties: `hs_email_subject`, `hs_email_sent_count`, `hs_email_open_count`, `hs_email_open_rate`,
  `hs_email_click_count`, `hs_email_click_rate`, `hs_email_from_email`, `hs_email_status`, `hs_createdate`
- Paginate through ALL results
- Also pull prior week total for comparison

### 5b. Classify and Aggregate by Team
Use the same 5 team categories as the daily pulse:
- **BD & Memberships**, **Sponsorships**, **Education & Training**, **Community & Programs**, **Other / Ops**

For each team: senders count, total sent, opened, open rate, clicked, click rate, top 3-5 threads.

### 5c. Daily Send Volume
Break down total emails by day of the week (Mon–Fri) to show activity distribution.

## Step 6: Generate Weekly Insights

Go beyond alerts — surface **patterns and trends**:

### Week-over-Week Comparison
For each metric, show this week vs last week with directional arrow and percentage change:
- Contacts: ↑ 15% (228 vs 198)
- Deals: ↓ 8% (50 vs 54)
- etc.

### Top Performers
- Most active email sender (by volume)
- Highest open rate sender (min 5 emails)
- Most segments created

### Pipeline Highlights
- Largest deals created this week (top 5 by amount)
- Total new pipeline value
- Any denied or stalled deals

### Alerts (same thresholds as daily)
- 0% open rate senders (3+ emails across the week)
- Unnamed segments
- Empty segments
- Very large segments (>500K)

## Step 7: Present the Report

### Default: Conversational Tables in Chat
Present as clean markdown tables in six sections:

**Section 1: Week-over-Week Summary**
Table with columns: Metric | This Week | Last Week | Change
One row each for contacts, deals, deal value, tickets, tasks, segments created, emails sent, avg open rate.

**Section 2: CRM Highlights**
Top 5 deals by amount, any denied deals, notable new contacts (by company).

**Section 3: Audience & Segment Work**
Table with columns: Creator | Segments | Total Contacts | Key Segments
Grouped by creator across the whole week.

**Section 4: 1:1 Email Outreach Summary**
Same consolidated team format as the daily pulse:
Bold summary line, then 5-row team table, then flagged senders line.
Add a "Daily volume" line: e.g., "Mon: 22 | Tue: 35 | Wed: 28 | Thu: 31 | Fri: 31"

**Section 5: Top Performers**
Quick callouts — most active sender, highest open rate, most segments built.

**Section 6: Alerts & Flags**
Same format as daily: Severity | Type | Who/What | Detail | Action

### On Request: XLSX Export
If asked, generate multi-tab XLSX with: WoW Summary, Deals, Segments, Emails by Team, Alerts.

### Specific Person Queries
Filter everything to that person's activity for the week.

## Tips for Reliable Execution

- **Parallel queries are critical** — you're pulling 2 weeks of data across 6+ object types. Fire all independent queries at once.
- **Paginate aggressively** — weekly email totals can easily exceed 500. Pull all pages.
- **Deal amounts** — sum amounts for pipeline value. Handle null amounts as $0.
- **chatInsights** — use `"userIntent": "Weekly HubSpot activity report"` on the first call, then `"<unchanged>"`.
- **Owner/user ID resolution** — same approach as daily pulse. Batch-resolve owner IDs.
