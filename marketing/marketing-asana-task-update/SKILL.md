---
name: marketing-asana-task-update
description: >
  Generate a Marketing Ops Asana queue pulse — assignee workload breakdown, overdue alerts,
  automation readiness classification, and actionable follow-ups — then offer to execute tasks
  Claude can handle independently. For the team lead: full-team report. For anyone else: personal
  queue. Use this skill whenever someone asks to check their Asana queue, get a status update on
  tasks, see what's overdue, review the roadmap, run their queue, execute tasks, or asks "what's
  on my plate" / "status of the queue" / "asana task status" / "what's overdue" / "queue check" /
  "task report" / "marketing ops update" / "run my queue" / "what should I work on" / "next task" /
  "execute my tasks" / "help me knock out tasks". Also trigger when someone asks about a specific
  teammate's tasks in Asana. Even casual phrasing like "asana", "queue", "check tasks", "status",
  "anything overdue", "task update", "let's work", or "what's next" should trigger this skill.
---

# Marketing Ops Queue — Pulse & Execute

One skill, two modes. First it shows you the queue (pulse), then it helps you work through it
(execute). The pulse adapts to who's asking — `{teamLeadName}` sees the whole team, everyone else
sees their own plate.

---

## CONFIGURATION

Before using this skill, fill in the placeholders below for your team. These values shape the
scope rules, project lookups, and reassignment logic that follow.

```yaml
# Asana project
queue_project_name: "Marketing Ops Request Queue"
queue_project_gid: "{queueProjectGid}"

# The team lead — this person sees the full team view; everyone else sees personal view
team_lead_name: "{teamLeadName}"
team_lead_asana_gid: "{teamLeadAsanaGid}"

# Section GIDs for per-person queues within the main project
sections:
  - name: "{teammate1Name}"
    section_gid: "{teammate1SectionGid}"
  - name: "{teammate2Name}"
    section_gid: "{teammate2SectionGid}"
  - name: "{teammate3Name}"
    section_gid: "{teammate3SectionGid}"
  - name: "{teammate4Name}"
    section_gid: "{teammate4SectionGid}"
  - name: "New Request / Not Assigned"
    section_gid: "{unassignedSectionGid}"

# Auto-reassignment rules — "tasks assigned to A should auto-reassign to B"
auto_reassignments:
  - from: "{teamLeadName}"
    to: "{delegateName}"
```

---

## Phase 1: Determine Scope

Figure out who's asking and what they should see.

### Step 1.1: Identify the User

Use `get_me` to get the current Asana user. Then apply this rule:

| Who's asking | What they see |
|---|---|
| **`{teamLeadName}`** (or user says "full queue" / "team report" / "the queue") | All assignees, all sections — full team view |
| **Anyone else** (or user names a teammate: "my tasks", "[name]'s queue") | Only that person's tasks — personal view |

If the user explicitly overrides scope ("show me just [name]'s tasks" or "show me everything"),
follow their instruction regardless of who they are.

### Step 1.2: Set the Project

Default: **`{queueProjectName}`** (project GID from CONFIGURATION).

Use the section GIDs from the CONFIGURATION block above for per-teammate queues.

If the user names a different project, use `search_objects` (resource_type: project) to find it.

---

## Phase 2: Gather Data

Collect everything in parallel to keep wait times short.

1. **Project metadata** — `get_project` with `opt_fields`: `name,num_tasks,num_incomplete_tasks,
   sections,sections.name` to get task counts and section list.

2. **Open tasks** — For team view: `get_tasks` for each active section (skip "Templates" and
   "Completed" sections). For personal view: `get_tasks` for that person's section only.
   Include `opt_fields`: `name,assignee,assignee.name,due_on,due_at,completed,created_by,
   created_by.name,created_at,start_on,notes,custom_fields,memberships.section.name,permalink_url`.
   Paginate if needed (100 per page).

3. **Handle large results** — If the API returns data too large to process inline, use bash with
   `jq` to extract compact summaries:
   ```bash
   jq '[.data[] | select(.completed == false) | {gid, name, assignee: (.assignee.name // "Unassigned"), due_on, created_by: (.created_by.name // "Unknown"), created_at}]'
   ```

4. **Subtask drill-down** — For tasks that look like parent tasks (email campaigns with
   List Pull / Staging / Launch steps), call `get_task` with `include_subtasks: true`.

5. **Creator info** — The `created_by` field tells you who submitted the request. Always include it.

### API Limitations to Know

- `get_tasks` does not support both `project` and `assignee` filters at the same time. Fetch by
  section and filter in your analysis.
- `search_tasks_preview` returns counts but not task details. Use it for quick counts only.
- For large projects (100+ tasks), paginate using the `offset` token from `next_page`.

---

## Phase 3: Filter Into Buckets

Before building any tables, separate tasks into three buckets. This prevents templates and stale
items from drowning the real work.

**Bucket 1 — Active Work**: Has a due date OR was modified in the last 30 days. These are real
tasks and go into the main report.

**Bucket 2 — Templates & Placeholders**: Name contains "REPORT TITLE", "TITLE:", "[TEMPLATE]",
or follows a generic placeholder pattern with no project name or specific content. Flag separately.

**Bucket 3 — Stale / No Due Date**: No due date AND no recent activity. These need triage —
list them at the bottom with a recommendation (close, triage, or move to templates).

---

## Phase 4: Present the Pulse Report

Structure the output in this exact order. Use markdown tables throughout.

### 4a. Executive Summary

One-line pulse:

> **Marketing Ops Request Queue** — [date] — [X] active tasks, [Y] overdue, [Z] due this week | [T] templates, [S] stale

Then the assignee breakdown — this is the single most important table. It answers "who owns what"
at a glance:

| Assignee | Active Tasks | Overdue | Due This Week | Due Next Week | Stale/No Date |
|----------|-------------|---------|---------------|---------------|---------------|

For **personal view**, still show this table but with only one row (the person's). Add a note
about total queue size for context.

### 4b. Overdue Tasks

ALL overdue tasks sorted by most overdue first:

| # | Task | Assignee | Due Date | Days Overdue | Created By | Subtask Status |
|---|------|----------|----------|-------------|------------|----------------|

Rules:
- 🔴 critical overdue (>7 days), ⚠️ overdue (1-7 days), 🟡 due today
- "Subtask Status" = "X/Y done" if subtasks exist, "—" if not
- "Created By" = who submitted the request (the person expecting delivery)
- Link each task: `[Task name](permalink_url)`
- If all subtasks are done but parent is open: "✅ Close this — all subtasks done"

For **personal view**, show only that person's overdue tasks. But if running as `{teamLeadName}` (team view),
show all overdue tasks across all assignees.

### 4c. Per-Assignee Breakdown (team view only)

For each assignee, show their active tasks grouped by urgency:

**[Name]'s Active Tasks ([X] total)**

| # | Task | Due | Category | Automation | What Claude Needs From You |
|---|------|-----|----------|------------|---------------------------|

Sort within each table: overdue first, then due today, then this week, then next week.

For **personal view**, skip the "Per-Assignee" header — just show "Your Active Tasks" as a single
table in this same format.

### 4d. Roadmap — Timeline View

Show upcoming (non-overdue) work by time horizon:

**This Week** / **Next Week** / **Later (2+ weeks out)**

| Task | Assignee | Due | Category |
|------|----------|-----|----------|

### 4e. Subtask Detail

For any parent task with mixed subtask status (some done, some not), expand:

**[Parent Task Name]** (assigned to X, due Y)

| Subtask | Assignee | Due | Status |
|---------|----------|-----|--------|

Skip this if all subtasks are done or all are pending — the summary in the main tables covers it.

---

## Phase 5: Deep Classification — What Can Claude Do?

This is the core of the skill. For every active task, read the full details and classify what
Claude can handle independently versus what needs human input.

### Step 5.1: Read Every Task

You MUST call `get_task` on each active task to read its `notes` (description), custom fields,
and comments before classifying. A task named "Other: Other" might have a detailed description
that reveals it's actually a clear list build. Never classify based on the name alone.

### Step 5.2: Classify Work Category

Determine each task's category by reading the name, description, and custom fields. Apply these
rules in order — first match wins:

| If task name contains... | Category | Not this |
|---|---|---|
| "Spam", "Clear Spam" | Other / Admin | Not List Build |
| "Workflow", "Automation", "Tux Rewards" | Workflow / Automation | Not List Build |
| "Ongoing reporting", "Adhoc report", "Dashboard" | Reporting / Dashboard | Not List Build |
| "HubSpot access" | HubSpot Access | — |
| "Form creation", "Contact Form" | Form Creation | — |
| "Email", "Newsletter", "Promo", "Launch", "Staging" | Email Campaign | — |
| "List audience build", "Import" (standalone, not subtask of email) | List Build / Import | — |
| "Campaign building", "Tracked URLs" | Campaign Setup | — |
| "Migrate", "API" + technical context | Other / Admin | Not List Build |
| "REPORT TITLE", "TITLE:" | Template — exclude | Flag separately |

Also identify the **LF Project** each task belongs to. Sources in priority order:
1. "Retainer Projects (Mktg Ops or CS)" custom field
2. Task name prefix before the colon (e.g., "CNCF: HubSpot access" → CNCF)
3. Task description or parent task context

### Step 5.3: Assess Automation Level

For each task, classify how much Claude can do without human help:

| Level | Icon | When to assign |
|---|---|---|
| **Fully Automatable** | 🟢 | Task description has ALL needed info — Claude can start immediately. Only assign this if the description actually contains complete criteria, names, parameters. |
| **After Clarification** | 🟡 | Claude can do this but needs 1-2 specific answers first. The intent is clear but key details are missing. |
| **Claude-Assisted** | 🔵 | Human leads, Claude preps/QAs/drafts. Saves ~50% effort. Email staging, form design, workflow logic. |
| **HubSpot Workflow** | ⚡ | This should be a recurring automation, not a manual ticket. Spam cleanup, scheduled sends, recurring list refreshes. |
| **Manual Only** | 🔴 | Requires human in a UI or external coordination. Admin access provisioning, stakeholder approvals, vendor calls. |

**Quality gate — check before presenting:**
1. All five levels should appear in a typical queue. If 0% for ⚡ or 🔴, re-examine spam cleanup and access tasks.
2. No "Workflow" task classified as List Build.
3. No task marked 🟢 unless its description genuinely has all needed info.
4. Every follow-up question is unique to that specific task.

### Step 5.4: Generate "What Claude Needs From You"

This is the most actionable column. For each task, write what's specifically needed to unblock
Claude — tailored to the automation level:

- **🟢 tasks**: "**Ready to go** — I can [specific action] now, just say the word"
- **🟡 tasks**: "**Need:** [specific question based on what's missing from the description]"
- **🔵 tasks**: "**Claude can:** [specific prep]. **You handle:** [what requires human]"
- **⚡ tasks**: "**Recommend:** Set up a HubSpot workflow for [specific recurring pattern]"
- **🔴 tasks**: "**Manual:** [specific reason it can't be automated]"

Be concrete. Not "Claude can help" but "Claude can search HubSpot contacts by lifecycle stage
and create an active list" or "Claude can run the audience-qa skill to verify suppression."
Reference specific MCP tools or skills when possible.

For tasks with empty descriptions: "⚠️ No description provided — ask requester to fill in
request details before work can begin."

### Step 5.5: Present the Classification Summary

**Automation Summary**

| Level | Count | % |
|---|---|---|
| 🟢 Fully Automatable | X | Y% |
| 🟡 After Clarification | X | Y% |
| 🔵 Claude-Assisted | X | Y% |
| ⚡ HubSpot Workflow | X | Y% |
| 🔴 Manual Only | X | Y% |

Then a bottom-line paragraph:

> **Bottom line:** X tasks (Y%) can be started by Claude immediately. Another Z tasks (W%)
> are ready once a quick question is answered — here are the top 3 to ask first:
> 1. [Task name]: [specific question]
> 2. [Task name]: [specific question]
> 3. [Task name]: [specific question]

---

## Phase 6: Queue Health & Cleanup

### Templates in wrong section

| Task | Current Section | Recommendation |
|------|----------------|----------------|

### Stale tasks

| Task | Assignee | Created | Recommendation |
|------|----------|---------|----------------|

For each stale task, recommend: **Close** (obsolete), **Triage** (might be relevant, needs date),
or **Move to Templates** (reusable template).

### CLAUDE.md Violations

Check the user's CLAUDE.md rules and flag violations:
- Tasks assigned to `{teamLeadName}` that should be auto-reassigned per the `auto_reassignments` config
- Parent tasks reassigned but subtasks still on `{teamLeadName}`
- Unassigned subtasks on reassigned parents

---

## Phase 7: Recommendations & Transition to Execution

End the pulse with 3-5 actionable recommendations:

**Immediate Actions (Claude can do now):**
- List the 🟢 tasks and offer to start. Example: "I can build the OpenSSF reporting dashboard
  right now — want me to start?"

**Quick Wins (need one answer, then Claude takes over):**
- List the top 🟡 tasks with the follow-up question inline. Example: "For the OpenSearch list
  build, I just need: attendees? contributors? or newsletter subscribers? Then I'll build it."

**Operational Flags:**
- Overdue escalations, unassigned tasks, workload imbalances, cleanup opportunities.

Then ask:

> **"Want me to start on one of these? Pick a number, say 'recommend' for my top pick, or
> say 'done' if you just needed the report."**

---

## Phase 8: Execute (when the user picks a task)

If the user picks a task or says "recommend", shift into execution mode.

### Step 8.1: Deep-Read the Task

Fetch full details with `get_task` including subtasks, attachments, and full notes. Parse:
- **What** is being asked (segment, email, list pull, report, etc.)
- **Who** requested it (created_by — this person gets the completion message)
- **When** it's due
- **Specific parameters** (project names, date ranges, audience criteria)

Check the execution memory file (`references/execution-memory.json`) for similar past tasks.
If found, mention it: "I've done a similar task before — [name] on [date]. Applying what I
learned: [insight]."

### Step 8.2: Route by Task Type

Follow the appropriate playbook from `references/task-playbooks.md`:

| Task Type | Tools / Skills |
|---|---|
| HubSpot Segment | HubSpot MCP tools, hubspot-segment-creation skill |
| Email Campaign | HubSpot MCP tools, marketing-analyst skill |
| List Pull / Export | `search_crm_objects`, data export |
| Asana Management | `update_tasks`, `create_task_preview` |
| Research / Analysis | HubSpot + Asana queries, data aggregation |

For unknown or complex tasks, present what you understand and ask for guidance. Don't guess.

### Step 8.3: Execute with Checkpoints

For multi-step tasks, announce each step before doing it:

```
Step 1 of 3: Creating HubSpot active list with filter "Event Registered where project = KubeCon EU 2026"
-> Done. List created: "KubeCon EU 2026 — Event Registered" (ID: 1234). 3,847 contacts.

Step 2 of 3: Adding suppression filter for opted-out contacts
-> Done. 212 excluded. Final count: 3,635.

Step 3 of 3: Sanity check against previous KubeCon lists
-> Done. Previous list had 2,901 contacts. 25% growth looks reasonable.
```

If any step fails or produces unexpected results, **stop and tell the user** rather than
continuing.

### Step 8.4: Handle "Need More Info"

If the task is ambiguous or missing details:
1. Tell the user what's missing and why it matters
2. Offer two paths:
   - **Ask the requester** — Claude drafts an Asana comment asking for clarification
   - **Make an assumption** — Claude suggests a default and proceeds if approved

Never proceed with ambiguity without user approval.

---

## Phase 9: QA & Notify

### Step 9.1: QA Check

After execution, verify against the original request:

| Check | Status | Details |
|---|---|---|
| Did what was asked (scope) | ✅/❌ | ... |
| Parameters correct (filters, dates) | ✅/❌ | ... |
| Output size reasonable (sanity) | ✅/❌ | ... |
| No obvious errors | ✅/❌ | ... |

### Step 9.2: Draft Requester Message

Draft an Asana comment for the requester. Use templates from `references/message-templates.md`
for the right format. Two types:

**Task Completed:**
```
Hi [Requester],

This is done! Here's what was completed:
- [Brief summary]
- [Key details: list name, count, ID, etc.]

Let us know if you need adjustments.

— Marketing Ops
```

**Need More Information:**
```
Hi [Requester],

We're working on this but need a couple of details:
- [Specific question 1]
- [Specific question 2]

Once you confirm, we'll have this wrapped up.

— Marketing Ops
```

**Always show the draft to the user before posting.** Only call `add_comment` after approval.

### Step 9.3: Record and Loop

After confirmation, append an entry to `references/execution-memory.json` (read it first, then
append). Then ask:

> **"Task done! Want to tackle the next one, or are we good for today?"**

If done, show a brief session summary: tasks completed, tasks pending follow-up, learnings captured.

---

## Reference Files

Read these when needed — they contain detail too large for this file:

- **`references/execution-memory.json`** — Past task completions and learnings. Read at start of
  Phase 8 to check for similar tasks. Write at end of Phase 9.
- **`references/message-templates.md`** — Extended Asana comment templates for common scenarios.
  Read when drafting messages in Phase 9.
- **`references/task-playbooks.md`** — Step-by-step execution guides for segment creation, email
  campaigns, list pulls, reports. Read at start of Phase 8 to guide execution.

---

## Hard Rules

- **Always separate active from stale.** Templates and placeholders mixed with real work is the
  #1 noise problem in this queue.
- **Always check subtasks.** Parent might look fine but have overdue subtasks — or vice versa.
- **Always do the classification.** The "What Claude Needs From You" column transforms a passive
  report into an operational decision tool. Never skip it.
- **Read every task description.** Call `get_task` on each active task before classifying.
- **Never execute without user confirmation** at key decision points (starting, posting comments,
  marking complete).
- **Never auto-post Asana comments.** Always show draft, wait for approval.
- **Respect CLAUDE.md rules.** Flag auto-reassignment violations and subtask handling issues.
- **Fetch in parallel.** Don't make the user wait while you fetch tasks one at a time.
- **Note the timestamp.** Always state when the report was generated — Asana data changes fast.
