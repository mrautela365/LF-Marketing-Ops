---
name: slack-to-asana-pipeline
description: Monitor a Slack channel for task requests and automatically create Asana tasks from them. Use this skill whenever the user wants to turn Slack messages into Asana tasks, set up a Slack-to-Asana automation, process a backlog of unread Slack requests, or build a task intake pipeline from Slack. Also trigger when the user says things like "check my Slack for tasks", "pick up requests from Slack", "turn that Slack message into a task", or "monitor a channel for work items". Works for any team or project type — not just marketing.
---
# Slack-to-Asana Pipeline

This skill reads messages from a Slack channel and creates Asana tasks from them — handling categorization, section placement, multi-homing for visibility, and posting a confirmation back to Slack. It's designed to eliminate manual Asana entry for teams that communicate work through Slack.

---

## Before You Start — Gather Configuration

You need the following from the user before doing anything else. Ask for anything that isn't already clear from the conversation:

| Config Item | How to Find It |
|---|---|
| Slack channel ID | Open channel → click channel name → scroll to bottom of About tab |
| Asana project GID | Open project in Asana → copy the number from the URL |
| Section GIDs for task placement | Open project → navigate to section → copy number from URL |
| Visibility project GID (optional) | Only needed if tasks should appear in a second project (e.g., for a manager) |
| Assignee | Who should tasks be assigned to? Default to the user. |

---

## Task Categorization

Classify each message into one of three categories. Use the keywords as a guide, but apply judgment for ambiguous cases.

**CAMPAIGN** — Any message about launching, building, or revising paid media or advertising campaigns. Look for: campaign, launch, ads, advertising, paid, promoted, sponsorship, platform names (Google Ads, LinkedIn, Meta, Reddit, Twitter/X, YouTube, Feathr, Brave, etc.)

**REPORT** — Any message about tracking results, pulling data, or creating performance summaries. Look for: report, analytics, performance, metrics, data, dashboard, recap, review, results, attribution

**ADMIN** — Everything else: process tasks, meetings, invoices, billing, receipts, documentation, coordination

If the category is genuinely unclear, ask the user or default to ADMIN.

---

## Task Creation Rules

### Title
Write a clean, professional task title from the message content. Don't copy the person's exact casual phrasing — paraphrase it into something that reads well in a task list. Avoid robotic formality too; aim for how a competent colleague would write it.

**Example:**
- Raw message: "hey can someone look at the google ads budget its running out before end of month"
- Task title: "Google Ads — mid-month budget review and pacing adjustment"

### Section Placement
Use what the user tells you. Common setups:
- CAMPAIGN → "In Progress" section (active builds)
- REPORT → "Inbox" or "To Do" section
- ADMIN → "Inbox" section

### Multi-homing (Visibility Projects)
If the user has a visibility project (e.g., a manager-facing board), add CAMPAIGN and REPORT tasks there too. Do NOT add ADMIN tasks to visibility projects — those are personal work queue items.

Use Asana's `add_project` on the task after creation to multi-home it.

### Due Dates
Only set a due date if a specific date is explicitly mentioned in the message. Don't invent due dates.

### Subtasks
Add platform-specific subtasks for CAMPAIGN tasks if the platform is mentioned. Keep them simple — the goal is a checklist, not a project plan. If no platform is specified, use a generic campaign checklist:
- [ ] Creative brief & objectives confirmed
- [ ] Assets received
- [ ] Campaign built and targeting configured
- [ ] Tracking/UTM parameters set up
- [ ] Launch
- [ ] 48-hour performance check-in

---

## Deduplication

Before creating a task, scan the message for any signs it's already been processed:
- Skip messages that start with "✅" (pipeline confirmation)
- Skip messages from bot users (unless they're structured form submissions — see slack-workflow-intake skill)
- Skip system/channel messages (joins, topic changes, etc.)

If you're running on a schedule, read messages from the past N hours (typically 4) so you don't reprocess old messages.

---

## Confirmation Message

After processing all messages, post a single confirmation back to the Slack channel:

```
✅ Added [N] task(s) to Asana: [Task Name 1], [Task Name 2], ...
```

If nothing was processed (no new messages), post nothing. The confirmation message itself starts with "✅" so it won't be picked up on the next run.

---

## Scheduling This Pipeline

If the user wants this to run automatically, create a scheduled Cowork task (see the `schedule` skill). A typical setup:

- **Frequency:** 3x per day on weekdays — 8am, 12pm, 5pm
- **Cron:** `0 8,12,17 * * 1-5`
- **Time window:** Read messages from the past 4 hours

For once-a-day setups, 8am works well — it catches everything from the previous afternoon and evening.

---

## Error Handling

- If Slack rate-limits the request, skip this run and wait for the next one
- If an Asana task creation fails, continue with the remaining messages — don't skip the confirmation for the ones that succeeded
- If a message can't be categorized, log it as ADMIN rather than failing
