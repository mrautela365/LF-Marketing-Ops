---
name: hubspot-form-manager
description: >
  HubSpot form management skill triggered by pasting an Asana task URL. Fetches
  the task, parses it for form actions — including creating new forms with
  autoresponder emails, deleting unused forms, or disabling/updating
  notifications — then executes each action in HubSpot via the browser.
  Use this skill whenever the user pastes an Asana link and the task is about
  managing HubSpot forms. Also trigger when the user says things like "handle
  this Asana task", "do this form cleanup", "process this HubSpot request",
  "build this form", "set up a signup form", or pastes any asana.com task URL
  where the task description involves forms — whether creating, deleting,
  updating, or configuring them.
---

# HubSpot Form Manager

You handle HubSpot form management requests that come in via Asana task links.
Your job is to read the task, understand exactly what needs to happen, confirm
any destructive actions with the user, and then carry them out in HubSpot.

## Step 1 — Extract the Asana task ID

Parse the task ID from the URL the user pasted. Asana URLs look like:
`https://app.asana.com/1/{workspace}/project/{project_id}/task/{task_id}`

The task ID is the last numeric segment (e.g. `1214761275486487`).

## Step 2 — Fetch the task

Call the Asana `get_task` tool with that task ID. Read the full `notes` field carefully.

## Step 3 — Identify the request type

Scan the notes and classify the task into one or more of these categories:

**FORM CREATION** — a new form needs to be built in HubSpot.
Signals: "Creating a new form", "new form", "set up a form", "livestream signup",
"signup form", "we need a form for", a reference form to clone from.

**FORMS TO DELETE** — forms that should be permanently removed from HubSpot.
Signals: "delete", "remove", "unused", "clean up", numbered list under a "DELETE" heading.

**NOTIFICATIONS TO DISABLE** — forms that should stay but have email notifications turned off.
Signals: "turn off notifications", "disable notifications", a list under a "NOTIFICATIONS" heading.

**OTHER UPDATES** — any other form setting changes (archiving, redirects, field changes).

Once classified, follow the relevant section(s) below. If the task mixes types
(e.g. create one form AND delete others), handle creation first, then deletions.

---

## FORM CREATION WORKFLOW

### FC-1 — Extract the form spec

From the task notes, collect:
- **Fields** (names, whether required or optional)
- **Submit button text**
- **Opt-in / subscription** the submitter should be enrolled in
- **Thank you message** copy (or reference form to copy it from)
- **From address** for the autoresponder email
- **Reference form** to clone structure/copy from (if mentioned)
- **Workflow enrollment** (which existing HubSpot workflow to enroll submitters)
- **Delivery requirements** — what links to send back to the requester
- **Notification recipients** (often "n/a" — no notifications)

⚠️ **Before moving on, check for ambiguity.** If any of the following are missing or unclear in the task notes, **stop and ask the user** — never assume a default or inherit from a reference form without explicit confirmation:

- **Subscription / opt-in type**: If the task doesn't name the exact subscription type, ask:
  > "Which subscription type should form submitters be opted into? Please confirm the exact subscription name in HubSpot (e.g. 'AAIF Newsletter', 'LF Events Updates')."

- **Brand / business unit association**: If it's unclear which HubSpot brand, business unit, or team this form belongs to, ask:
  > "Which brand or business unit should this form be associated with in HubSpot? (e.g. LF Events, AAIF, OpenSSF)"

- **Workflow enrollment**: If no workflow is named and it isn't obvious from context, ask:
  > "Should submitters be enrolled in a specific HubSpot workflow after submitting? If yes, what's the workflow name?"

- **From address**: If multiple from addresses are plausible and none is specified, ask before picking one.

Only continue to FC-2 once all ambiguous items are confirmed by the user.

### FC-2 — Look up the reference form (if one is named)

If the task references an existing form (e.g. "same setup as 26Q1 - LF Events - MCP NA 2026"):

1. Get the HubSpot portal ID via `get_organization_details`.
2. Navigate to `https://app.hubspot.com/forms/{portalId}` and search for the
   reference form by name.
3. Open it and note:
   - The thank you message copy
   - Any workflow/enrollment it triggers
   - The structure of its autoresponder email (subject line, body, from address)
   - The naming convention used (e.g. "26Q1 - LF Events - MCP NA 2026")

Use this to inform the new form — especially the thank you message and email
structure if they aren't spelled out in the task notes.

### FC-3 — Derive a name for the new form

Follow the same naming convention as the reference form. For LF Events forms
the pattern is typically:
`[Year+Quarter] - [Team] - [Event Name] [Year]`

Example: if the reference is `26Q1 - LF Events - MCP NA 2026`, and the new
event is MCP Dev Summit Mumbai 2026 in Q2:
→ `26Q2 - LF Events - MCP Mumbai 2026`

Confirm the proposed name with the user before creating if you're unsure.

### FC-4 — Create the form in HubSpot

1. Navigate to `https://app.hubspot.com/forms/{portalId}` → click **Create form**.
2. Choose **Standalone** (or the appropriate type — "Embed" if they want an embed code).
3. Set the form name per FC-3.
4. Add each required field from the spec. For standard fields (First Name, Last Name,
   Email) use the built-in HubSpot fields. For Country, use the built-in Country/Region
   field. For any custom fields, create or locate them as needed.
5. Mark each field as required or optional per the spec.
6. Set the submit button text.
7. Configure the **Thank You** step: select "Thank you message" and enter the copy
   (from the reference form if not specified directly).
8. Under **Options / Settings**, set notifications:
   - If the task says "n/a" or no notifications: remove all notification recipients.
   - Otherwise add the specified recipients.
9. Confirm the **opt-in / subscription** checkbox is mapped — look in the form
   settings or follow-up actions for the subscription opt-in property and set it
   to the correct subscription type. If you haven't already confirmed this with
   the user in FC-1, do so now before selecting anything. Never pick a subscription
   type by guessing or copying from the reference form without explicit confirmation.
10. Save / Publish the form.
11. Copy the **embed code** or **form name** — you'll need it for the deliverables.

### FC-5 — Locate or confirm the signup list

HubSpot automatically creates a contacts list for each form's submissions.
After creating the form:
1. Navigate to **Contacts → Lists** and search for the form name.
2. The auto-created list is usually named "[Form name] (HubSpot form submissions)".
3. Copy its direct URL from the browser address bar.

### FC-6 — Create the autoresponder email

If the task calls for an autoresponder (a transactional email sent immediately
when the form is submitted):

1. Navigate to **Marketing → Email → Create email**.
2. Choose **Automated** as the email type (not marketing/batch).
3. Set the email to **Transactional** in the settings (this bypasses subscription
   status — important for confirmation/livestream emails).
4. Subject line: use the reference email's subject as a template, updating the
   event name. If no reference, use something like:
   "You're registered — [Event Name]"
5. From address: use the address specified in the task (e.g. `events@aaif.io`).
   If that address isn't set up yet, fall back to the backup address noted in the
   task (e.g. `aaifevents@linuxfoundation.org`) and flag this to the user.
6. Body copy: use the reference email's body as a starting template, swapping
   in the new event name. If no reference, write a simple confirmation:
   "Thanks for signing up for [Event Name] — we'll send you the livestream link
   closer to the event."
7. **Publish** the email (even if content will be updated later — the requester
   needs to test it).
8. Copy the direct URL to this email from the browser.

### FC-7 — Enroll the form in the workflow (if specified)

If the task says to enroll submitters in an existing workflow:
1. Navigate to **Automation → Workflows** and find the named workflow
   (e.g. "Subscription - Agentic AI Foundation (AAIF)").
2. Open the workflow and add a trigger: "Contact submitted form" → select the
   new form.
3. Save and re-enable the workflow if it was paused.

If the workflow isn't named explicitly in the task, don't guess and don't copy
from a reference form without asking. Check whether you already confirmed this
in FC-1; if not, ask the user before proceeding:
> "Which HubSpot workflow (if any) should form submitters be enrolled in? Please confirm the exact workflow name."

Alternatively, if the autoresponder email should be the workflow trigger (common
for transactional setups): set the form's follow-up email in the form settings
to send the autoresponder automatically.

### FC-8 — Compile and deliver the outputs

After all steps are complete, show a clean delivery summary in chat:

```
✅ Form created — [Form Name]

📋 Form name:       [exact name as created]
📎 Embed code:      [paste embed snippet, or note where to find it]
📋 Signup list URL: [direct link to the form submissions list]
📧 Autoresponder:   [direct link to the published email in HubSpot]
📬 From address:    [the from address used — flag if fallback was used]
```

Then generate a **shareable update** (see Final Summary section below) the user
can paste directly into the Asana task comment or Slack.

---

## FORM DELETION WORKFLOW

### Step D1 — Parse the task into a delete plan

Scan the notes for forms that should be permanently removed. Signals: "delete",
"remove", "unused", "clean up", a numbered list under a "DELETE" heading.

### Step D2 — Show the action plan and get confirmation

Present a clear summary **before doing anything**:

```
📋 Action Plan — [Task Name]

🗑️  FORMS TO DELETE (N forms)
  1. [form name]
  2. [form name]
  ...

⚠️  Deleting forms is permanent and cannot be undone.
    Please confirm: should I proceed? (Yes / No / I'll tell you which to skip)
```

Wait for explicit confirmation before proceeding.

### Step D3 — Get the HubSpot portal ID

Call `get_organization_details` to get the portal ID.

### Step D4 — Execute deletions

For each form:
1. Navigate to `https://app.hubspot.com/forms/{portalId}`.
2. Search for the form by name using the search bar.
3. Hover over the form row → click **Actions → Delete**.
4. Confirm the deletion dialog.
5. If not found, mark as "not found / already deleted" and continue.
6. Report progress after each: "✅ Deleted: [form name]"

---

## DISABLE NOTIFICATIONS WORKFLOW

For each form where notifications should be turned off:
1. Navigate to `https://app.hubspot.com/forms/{portalId}`.
2. Search for the form → hover → click **Edit**.
3. In the form editor, click the **Options** tab (sometimes called Settings).
4. Scroll to **Send email notifications to** and remove all recipients, or
   uncheck the notification toggle if one exists.
5. Click **Update / Save**.
6. Report: "🔕 Notifications disabled: [form name]"

If the form editor UI looks different (HubSpot sometimes redesigns it), look
for "Notifications", "Email alerts", or "Send notification to" — the concept
is the same.

---

## Final Summary + Shareable Update

After all actions are complete, show two things:

### Internal progress summary (in chat)

Show a tick-list of everything completed, with ✅, ⚠️, or 🔕 as appropriate.

### Shareable update (ready to copy)

Generate a clean, professional update the user can paste into the Asana task
comment or a Slack channel. Keep it concise — one short paragraph plus bullet
points. Tone: matter-of-fact and complete. No emoji overload.

For a **form creation** task:

```
HubSpot form setup complete for [Event Name].

• Form name: [form name]
• Signup list: [URL]
• Autoresponder email: [URL] — published and ready to test
• From address: [address used]
• Submitters enrolled in: [workflow name]

Note: [any caveats — e.g. fallback from address used, content placeholder in email]
```

For a **deletion/cleanup** task:

```
Completed HubSpot form cleanup per [Requester]'s request.

• Deleted N unused forms (Alpha Omega, OpenSSF, PyTorch, DPDK, LF Energy)
• Disabled email notifications on N newsletter forms (ASWF, HPSF, PyTorch)
[• Any items skipped or not found: briefly note why]

All forms confirmed removed from project websites prior to cleanup. Done.
```

Then ask the user:
> "Want me to post this as a comment on the Asana task, or send it to a Slack channel?"

If they say yes to Asana: use the Asana `add_comment` tool with the task GID.
If they say yes to Slack: use the Slack MCP to post to the specified channel.
If they say both: do both.

---

## Edge cases

- **Reference form not found**: Let the user know and ask if they can share the
  thank you copy / email template directly.
- **From address not set up**: Use the fallback address from the task and
  clearly flag this in the delivery summary.
- **Duplicate form names**: For deletions, look at date prefixes or ask the user.
  Don't guess on deletions.
- **Form not found during deletion**: Mark as "not found" and continue.
- **Task has no clear form list**: Ask the user to clarify before doing anything.
- **Task is not a form request**: If after reading the task it's clearly not
  about HubSpot forms at all, let the user know and describe what the task
  actually asks for.
- **Mixed request** (create + delete + notifications): Handle creation first,
  then deletions, then notification changes.
- **Unclear brand, subscription, or workflow**: Always stop and ask the user before assigning any of these — even if a reference form is available. These settings have downstream effects on subscription compliance and workflow automation that are hard to undo. A quick confirmation question is always faster than unwinding a mistake.
