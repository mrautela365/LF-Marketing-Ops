# Task Playbooks — Marketing Ops Execution

Step-by-step execution guides for common Marketing Ops task types. Claude reads this file
at the start of Phase 8 to guide execution of the selected task.

---

## Playbook: HubSpot Segment / List Creation

**Trigger phrases in task name:** "segment", "list", "audience", "pull contacts", "create list"

**Steps:**

1. **Parse requirements** — Extract from task description:
   - List type: Active (dynamic) or Static
   - Filter criteria (event name, property filters, date ranges)
   - Suppression/exclusion needs (opt-outs, previous sends, competitors)

2. **Verify properties exist** — Use `search_properties` to confirm the HubSpot properties
   referenced in the filters actually exist. Common gotcha: property names change or have
   different internal names than display names.

3. **Create the list** — Use `manage_crm_objects` or follow the hubspot-segment-creation
   skill for UI-guided creation via browser tools if MCP doesn't support list creation directly.

4. **Apply suppression** — If the requester wants opt-outs excluded (they almost always do),
   add a suppression filter for contacts with `hs_email_optout = true` or similar.

5. **Verify count** — Check the contact count. Compare to similar past segments if available
   in execution memory. Flag if count is 0, surprisingly low, or surprisingly high.

6. **Name the list** — Follow naming convention: `[Event/Project] — [Filter Description] — [Date]`
   Example: `KubeCon EU 2026 — Event Registered — Apr 2026`

**Common issues:**
- Property "pe_project_name" vs "project_name" — always verify the exact internal name
- Custom events (Event Registered, Education Enrolled) require specific filter syntax
- Active lists refresh periodically; static lists are frozen at creation time

---

## Playbook: Email Campaign Setup

**Trigger phrases:** "email", "send", "campaign", "newsletter", "blast", "outreach"

**Steps:**

1. **Parse requirements** — Extract:
   - Subject line (or request one if not provided)
   - Audience / send list (name or ID)
   - Send date/time (or "ASAP" / "draft only")
   - Sender name and email
   - Content (may be in the task description, an attachment, or "use the template")

2. **Check audience readiness** — Is the audience list created? What's the contact count?
   If the list doesn't exist yet, create it first (see Segment playbook above).

3. **Set up the email** — Use HubSpot MCP tools or follow the marketing-analyst skill.
   Configure: sender, subject, audience, schedule.

4. **Compliance check** — Verify:
   - Suppression list applied (opt-outs excluded)
   - Unsubscribe link present in template
   - For EU audiences: GDPR consent signal confirmed
   - For CA audiences: CASL compliance verified

5. **Schedule or save as draft** — Per requester's instructions. If scheduling, confirm
   the exact date/time and timezone.

**Common issues:**
- Sending without suppression = compliance risk. Always verify.
- Wrong audience attached — double-check list name matches request
- Timezone confusion — always confirm "10 AM ET" vs "10 AM PT"

---

## Playbook: List Pull / Data Export

**Trigger phrases:** "export", "pull data", "get contacts", "download list", "CSV"

**Steps:**

1. **Parse requirements** — Extract:
   - What data is needed (contact list, engagement data, event registrations)
   - Filter criteria
   - Output format (CSV, in-HubSpot list, summary)
   - Columns needed (email, name, company, custom fields)

2. **Query HubSpot** — Use `search_crm_objects` with appropriate filters.
   For large result sets, paginate and aggregate.

3. **Format output** — Per requester's needs. If CSV is requested, generate
   it locally and provide a download link. If in-HubSpot, create a static list.

4. **Verify completeness** — Check that the result count matches expectations.
   Cross-reference with any counts mentioned in the task description.

**Common issues:**
- HubSpot API has a 10,000 result limit per search — paginate for larger sets
- "All contacts" is rarely what they actually want — clarify filters
- PII handling — don't expose sensitive data unnecessarily

---

## Playbook: Asana Task Management

**Trigger phrases:** "reassign", "update task", "move to", "change due date", "add subtask"

**Steps:**

1. **Parse the action** — What specifically needs to change?
   - Reassignment: new assignee
   - Status update: new section or custom field value
   - Due date change: new date
   - Subtask creation: subtask details

2. **Execute via Asana MCP** — Use `update_tasks` for field changes.
   Use `create_task_preview` for subtask creation.

3. **Check the `auto_reassignments` config** in SKILL.md — Some reassignment patterns are
   governed by rules (e.g., team-lead-to-delegate auto-reassignment). Apply these automatically.

4. **Verify** — Re-fetch the task to confirm changes stuck.

**Common issues:**
- Subtask reassignment — when reassigning a parent, always check and reassign subtasks too
- Section moves require specific section GIDs — reference the known section list

---

## Playbook: Research / Analysis Request

**Trigger phrases:** "report on", "analyze", "how many", "what's the status of", "metrics"

**Steps:**

1. **Parse the question** — What specific data or insight is being requested?

2. **Identify data sources** — HubSpot (contacts, deals, emails), Asana (tasks, projects),
   or external data.

3. **Query and aggregate** — Pull the data, compute metrics, identify trends.

4. **Summarize findings** — Present in a clear, concise format. Use tables for
   comparative data. Include both the answer and the methodology.

5. **Suggest next steps** — Based on the findings, what should the requester do?

**Common issues:**
- Vague requests ("how's the campaign going?") — clarify which campaign and which metrics
- Date range ambiguity — always confirm the time period
- Comparing apples to oranges — make sure comparison baselines match
