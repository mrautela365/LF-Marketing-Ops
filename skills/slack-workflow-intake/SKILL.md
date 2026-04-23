---
name: slack-workflow-intake
description: Read structured form submissions from a Slack Workflow Builder form and create rich, detailed Asana tasks from them. Use this skill when a team is using a Slack intake form to submit requests, when Workflow Builder form submissions need to become Asana tasks, or when setting up a request intake pipeline where people fill out a structured form in Slack. Trigger on phrases like "set up a Slack intake form", "turn form submissions into Asana tasks", "process requests from our Slack form", "people submit requests via Slack and I want them in Asana", or "build a campaign request form in Slack". Also use when the user wants to replicate an existing form (e.g., Asana form, Google Form, Typeform) as a Slack Workflow Builder form.
---

# Slack Workflow Intake → Asana

This skill handles two related things:
1. **Reading** structured Slack Workflow Builder form submissions and creating Asana tasks from them
2. **Building** a Slack Workflow Builder form to replace or replicate an existing intake form

---

## Part A: Processing Form Submissions

### How Workflow Builder Messages Work

When someone submits a Slack Workflow Builder form, the workflow posts a bot message to a channel. The format varies depending on how the workflow's "Send a message" step was configured, but a common pattern is:

```
*Field Label*
Field value
*Another Field*
Another value
```

Each field label appears on its own line in bold (surrounded by `*`), with the value on the next line. Blank optional fields still appear with an empty line below them.

**Identifying form submissions:** Messages from Workflow Builder come from a bot user, not a human. Use the bot's user ID to distinguish form submissions from human comments in the same channel. Find the bot ID by reading the channel and looking at the message sender — it will look like `BXXXXXXXXX`.

### Parsing Logic

To extract field values:
1. Split the message into lines
2. Find lines that match the pattern `*Label*` (bold text with no colon)
3. Read the next non-empty line as the value
4. If a field is blank, treat the value as "N/A" or skip it in the task description

### Task Creation

**Task title:** Combine the most identifying fields — typically `[Project] — [Request/Campaign Name]`

**Task description:** Format all form fields into a clean, readable Asana description. Group related fields together. Don't include fields that are blank/N/A unless they're important.

**Section placement:**
- Form submissions are almost always campaign or project requests → place in the "In Progress" section of the personal queue
- Multi-home to the visibility/manager project if applicable

**Due date:** If the form includes a date field (start date, run dates, deadline), parse the start date and use it as the due date.

**Subtasks:** Add a generic campaign checklist since the form usually doesn't specify a platform:
- [ ] Creative brief & objectives confirmed
- [ ] Assets received
- [ ] Campaign built and targeting configured
- [ ] Tracking/UTM parameters set up
- [ ] Launch
- [ ] 48-hour performance check-in

**Confirmation:** After creating the task, post a confirmation to the channel:
```
✅ Campaign request received and added to Asana! Task created: [Task Title]
```

---

## Part B: Building the Slack Form

If the user wants to create a Slack Workflow Builder form (either from scratch or to replicate an existing form), follow these steps.

### Step 1: Understand the Fields

If replicating an existing form (Asana form, Google Form, etc.):
- Try to read the form directly if a URL is available
- If the form is JavaScript-rendered (like Asana forms), use Claude in Chrome to navigate to it and read the page
- Extract: field labels, field types (text, dropdown, date, etc.), dropdown options, required/optional status, and help text

If building from scratch, ask the user what information they need to collect.

### Step 2: Map Fields to Slack Workflow Builder Types

Slack Workflow Builder supports these field types:
| Asana/Generic Type | Slack Equivalent |
|---|---|
| Short text | Short answer |
| Long text / paragraph | Long answer |
| Dropdown / select | Select from a list |
| Date | Short answer (date pickers aren't available in all plans) |
| Number | Short answer |
| Email | Short answer |
| File upload | ❌ Not supported — tell requestors to share links or post files in the thread |

### Step 3: Write the Setup Instructions

Provide step-by-step instructions for the user to build the form in Slack Workflow Builder. Structure them as:

1. **Open Workflow Builder** — Workspace name → Tools → Workflow Builder → New Workflow
2. **Set the trigger** — "From a link in Slack" creates a shareable shortcut button
3. **Step 1: Collect information** — Add each field in order with the exact label, type, options (for dropdowns), and required/optional setting
4. **Step 2: Send a message** — Configure the message template that gets posted to the channel. This is what the pipeline reads, so design it carefully:
   - Use `*Field Label*` on its own line, with the variable insertion below it
   - Insert each form field using Workflow Builder's variable insertion (looks like `{{Step 1 > Field Label}}`)
5. **Publish and share** — Copy the workflow link and pin it in the channel

### Step 4: Design the Message Template Carefully

The message template in Step 2 of the workflow determines what gets posted to the channel — and what the pipeline parses. The pipeline will look for `*Label*` followed by the value on the next line. Design the template to match:

```
*Request Type*
{{Step 1 > Request Type}}
*Project*
{{Step 1 > Project}}
*Contact Name*
{{Step 1 > Contact Name}}
...and so on for each field
```

If the user later changes the field labels in the form, remind them the message template labels also need to match — those are what the pipeline reads, not the form labels.

### Step 5: Update the Pipeline

Once the form and channel are set up, update the Slack pipeline (see `slack-to-asana-pipeline` skill) to:
- Monitor the new channel
- Identify messages from the Workflow Builder bot by its bot ID (`BXXXXXXXXX`)
- Parse using the label-per-line format
- Skip human comments in the same channel

---

## Common Issues

**Form is JavaScript-rendered and can't be read by web fetch.** Use Claude in Chrome to navigate to the form URL and extract field information. Use `get_page_text` first, then JavaScript execution to click dropdowns and reveal their options.

**Blank fields still appear in the message.** This is expected — Workflow Builder always includes all fields in the message even when empty. The parser should handle blank values gracefully.

**Bot messages get skipped by the pipeline.** If the pipeline is set to skip all bot messages, it won't catch form submissions. Make sure the pipeline explicitly whitelists the Workflow Builder bot ID rather than blocking all bots.

**Field labels changed after setup.** If the user edits field labels in Workflow Builder, the message template variables update automatically — but any hardcoded label names in the pipeline need updating too.
