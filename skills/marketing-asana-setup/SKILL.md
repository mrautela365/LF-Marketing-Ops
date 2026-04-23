---
name: marketing-asana-setup
description: Set up a complete Asana workflow for a performance marketing team — personal queue project, section structure, recurring automated tasks, Slack intake pipeline, and manager visibility. Use this skill when a marketing person wants to set up Asana from scratch, automate their task management, stop manually entering recurring tasks, give their manager visibility into campaign work, or build a system where work flows in from Slack automatically. Trigger on phrases like "set up my Asana for marketing", "automate my task management", "I want recurring tasks in Asana", "help me organize my marketing work in Asana", or "I'm a one-person marketing team and want to automate my workflow".
---

# Marketing Asana Setup

This skill sets up a complete, low-maintenance Asana workflow for a performance marketer — especially useful for solo or small marketing teams who want to spend time on actual work, not on managing their task list.

The end state: tasks flow in automatically, recurring work gets created on schedule, a manager can see campaign work without being bothered with admin details, and the marketer gets a weekly digest without lifting a finger.

---

## Step 1: Understand Their Setup

Before building anything, gather this information. Most of it can come from the conversation — only ask for what's missing.

**Asana:**
- Do they already have a project, or are we creating one from scratch?
- Is there a shared/team project their manager uses? (This is for visibility — campaign tasks get multi-homed here)
- Who is their manager or key stakeholder in Asana?

**Slack:**
- Do they want a Slack-to-Asana pipeline? If yes, what channel should requests come from?
- Do they want a campaign intake form in Slack? (See `slack-workflow-intake` skill)
- Where should the weekly digest be sent? (DM or a channel)

**Recurring tasks:**
- What regular work happens on a schedule? Common examples:
  - Monthly billing/invoicing (first business day of month)
  - Monthly receipt uploads (last business day of month)
  - Weekly budget reviews (every Monday)
  - Monthly reporting
- Are there US federal holiday blackouts to respect?

**Platforms:**
- Which ad platforms do they use? This drives the subtask templates.

---

## Step 2: Create the Personal Queue Project

Create an Asana project for the marketer's personal work queue with these four sections:

| Section | Purpose |
|---|---|
| 📥 New / Inbox | Incoming tasks not yet started |
| 🔄 In Progress | Active campaign builds and ongoing work |
| ⏳ Upcoming | Scheduled work and future campaigns |
| ✅ Complete | Finished tasks |

Name the project something like "[Name]'s Performance Marketing Queue" or whatever feels natural to the user.

---

## Step 3: Configure Manager Visibility (Two-Project System)

If the user has a manager or stakeholder who needs visibility:

- **Campaign tasks** → add to both personal queue AND the shared/visibility project
- **Report tasks** → add to both personal queue AND the shared/visibility project
- **Admin tasks** → personal queue only (the manager doesn't need to see billing reminders)

This is called "multi-homing" — one task lives in two projects simultaneously. Neither person has to copy tasks or send updates; the manager just opens their project and sees everything relevant.

**Important note for Asana rules:** If the shared project has automation rules (e.g., auto-routing based on assignee), the rules may override the section placement from the API. The user may need to ask their Asana admin to add a rule: "When task is added AND assignee is [user] → move to [user's section]."

---

## Step 4: Set Up Recurring Tasks

For each recurring task the user identifies, create a scheduled Cowork automation (see `schedule` skill). The key patterns:

**Monthly task on a specific business day:**
```
Calculate the Nth business day of the month, skipping US federal holidays.
Create the task on that date at [time].
```

Common examples:
- Billing submission → 1st business day of month, 8am
- Receipt upload → last business day of month, 8am

**Weekly recurring tasks:**
```
Run every [weekday] at [time].
Skip if the day falls on a US federal holiday.
```

Common example:
- Campaign budget review → every Monday at 8am

For each recurring task, determine:
- Is it a CAMPAIGN, REPORT, or ADMIN task? (Affects which projects it lands in)
- What section should it go into? (Upcoming tasks → 📥 Inbox; active tasks → 🔄 In Progress)
- Does it need due dates? (Campaign tasks with real deadlines get them; admin tasks typically don't)

---

## Step 5: Set Up the Slack Pipeline (Optional)

If the user wants Slack-to-Asana automation, refer to the `slack-to-asana-pipeline` skill for the full setup. Summary:

- Choose a channel for ad-hoc task requests (e.g., #marketing-task-inbox)
- Pipeline runs 3x/day on weekdays (8am, 12pm, 5pm)
- Messages get categorized and turned into tasks automatically
- Confirmation posted back to Slack after each run

---

## Step 6: Set Up the Weekly Digest (Optional)

A Friday digest gives the user a quick summary of the week without having to open Asana. Set it up as a scheduled Cowork task:

- **Schedule:** Fridays at 4pm
- **Content:**
  - ✅ Tasks completed this week
  - 🔄 Tasks currently in progress
  - 📅 Tasks coming up next week
- **Delivery:** Slack DM to the user (more private than posting to a channel)

---

## Step 7: Confirm and Summarize

Once everything is set up, give the user a plain-English summary of what's running:

```
Here's what's now automated for you:

📋 Personal queue project: [Project Name]
   Sections: New/Inbox, In Progress, Upcoming, Complete

👀 Manager visibility: Campaign and report tasks also appear in [Shared Project]

🔁 Recurring tasks:
   - [Task name] — every [schedule]
   - [Task name] — every [schedule]

💬 Slack pipeline: Monitors #[channel] 3x/day → creates Asana tasks automatically

📊 Weekly digest: Fridays at 4pm → Slack DM

⚙️ Action items for you:
   - [Any manual steps the user still needs to do, e.g., Asana rule fixes, channel creation]
```

---

## Common Gotchas

**Asana automation rules override API section placement.** If the shared project has rules that route tasks automatically, those rules will fire when a task is added via API and may put the task in the wrong section. The fix requires an Asana admin to add a rule: "When task added AND assignee is [user] → move to [user's section]."

**Recurring tasks ≠ Asana's built-in recurring tasks.** Asana's native recurring tasks don't support business day logic or holiday skipping. Cowork scheduled tasks handle this properly.

**Don't set due dates on admin tasks.** Due dates on tasks like "upload receipts" create unnecessary clutter and make the board look like things are overdue when they're just routine. Reserve due dates for campaign launches and external deadlines.
