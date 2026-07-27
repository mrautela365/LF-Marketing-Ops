# Survey Workflow — Standalone Asana Task Automation Service

A **separate microservice** that accepts **Asana task URLs only** and runs the complete email staging pipeline by orchestrating the `emailcreationskill` service backend.

## What It Does

1. **Fetches Asana Task Data** — extracts brief from task + subtasks + comments
2. **Looks Up Brand & HubSpot History** — finds previous emails, sender settings, suppression lists
3. **Fetches Google Doc Content** — extracts email body from linked Google Docs
4. **Runs Email Staging Workflow** — executes the full plan → clone → content pipeline
5. **Marks Task Complete** — automatically completes the Asana task upon success

## Architecture

### Service Structure

```
marketing/
├── emailcreationskill/          (Main email staging service)
│   └── backend/
│       ├── agent.py             (AI orchestration — reused)
│       ├── asana_tools.py        (Task extraction — reused)
│       ├── hubspot_tools.py      (Email ops — reused)
│       ├── content_tools.py      (Scraping, Google Doc — reused)
│       └── ...
│
└── survey_workflow/             (Standalone Asana automation service)
    ├── asana_workflow.py        (Orchestration layer)
    ├── cli.py                   (CLI entry point)
    ├── README.md                (This file)
    └── ...
```

### Key Design: Zero Code Duplication

Survey Workflow **imports and reuses** all logic from `emailcreationskill/backend`:
- `agent.py` — all AI orchestration (same `llm_gateway`, same models, same temperature=0)
- `asana_tools.py` — task extraction
- `content_tools.py` — URL scraping, Google Doc fetching
- `hubspot_tools.py` — email cloning, settings, content updates
- `event_brands.py` — brand mapping, location detection

**No duplicate code.** The survey workflow layer is thin — it wires existing tools together in a specific sequence.

## Configuration

Survey Workflow uses **all parent service configs** from `.env` (same file as `emailcreationskill`):

```bash
# Asana API (optional; falls back to MCP if not set)
ASANA_ACCESS_TOKEN=your_asana_token

# Claude AI backend (shared with emailcreationskill)
ANTHROPIC_API_KEY=your_key
CLAUDE_MODEL=claude-3-5-sonnet-20241022

# HubSpot (shared with emailcreationskill)
HUBSPOT_PORTAL_ID=8112310
HUBSPOT_PRIVATE_APP_TOKEN=your_token

# LiteLLM backend (optional)
LITELLM_BASE_URL=http://localhost:8000
LITELLM_API_KEY=your_key
```

## Usage

### Command Line

```bash
# Simple run
python survey_workflow/cli.py "https://app.asana.com/0/1234567890/1234567890" --verbose

# Dry run (simulate without task completion)
python survey_workflow/cli.py "https://app.asana.com/0/.../task/123" --dry-run --verbose
```

Output:
```
🚀 Starting Asana Survey Workflow Automation
   Task URL: https://app.asana.com/0/.../task/123

================================================================================
WORKFLOW RESULT
================================================================================
✅ SUCCESS
   Email ID: 12345678
   Email Name: 26Q3 - CNCF - KubeCon NA - Invite
   Draft URL: https://app.hubspot.com/...
   Asana Task: ✓ Marked as complete

⚠️  Warnings:
   • No sent emails found in HubSpot for brand 'CNCF'
```

### Python API

```python
import asyncio
from survey_workflow import run_asana_workflow

async def main():
    result = await run_asana_workflow(
        asana_url="https://app.asana.com/0/1234567890/1234567890",
        dry_run=False
    )
    print(f"Email ID: {result['email_id']}")
    print(f"Draft URL: {result['draft_url']}")
    print(f"Task complete: {result['completed_task']['success']}")

asyncio.run(main())
```

### Step-by-Step Control

```python
from survey_workflow import AsanaTaskWorkflow

workflow = AsanaTaskWorkflow(asana_url, dry_run=False)

# Step 1: Fetch task
await workflow.fetch_asana_task()
print(f"Task: {workflow.brief['task_name']}")

# Step 2: Look up brand and content
await workflow.lookup_brand_and_content()
print(f"Brand: {workflow.brand_history['brand_name']}")

# Step 3: Run email staging
result = await workflow.run_full_workflow()
print(f"Email ID: {result['email_id']}")

# Step 4: Mark complete
complete = await workflow.complete_asana_task()
```

## Asana Task Format

The workflow expects Asana tasks in this format:

```
Task Name: 26Q3 - CNCF - KubeCon NA - Invite

Task Notes:
[optional context]

Subtasks:
├── Event URL
│   Notes: https://events.linuxfoundation.org/kubecon-na-2026/
├── Content
│   Notes: Google Doc: https://docs.google.com/document/d/...
├── List Pull
│   Notes: Use KubeCon historical audience... [audience instructions]
└── [Any other subtasks]
```

The workflow **extracts from**:
- **Task name** — brand (from "YYQn - BRAND - ..." pattern)
- **Task notes** — audience instructions
- **Event URL subtask** — the event landing page
- **Content subtask** — Google Doc URL (where email body HTML comes from)
- **List Pull subtask** — segmentation/audience strategy instructions

## Return Value

```python
{
    "success": True/False,
    "email_id": "12345678",
    "email_name": "26Q3 - CNCF - KubeCon NA - Invite",
    "draft_url": "https://app.hubspot.com/...",
    "warnings": [
        "No sent emails found in HubSpot for brand 'CNCF'",
    ],
    "completed_task": {
        "success": True/False,
        "task_gid": "123456789",
        "message": "Task marked as complete in Asana"
    }
}
```

## Error Handling

If **any step fails**, the workflow:
1. **Logs the error** with full context
2. **Stores warnings** in the result
3. **Does NOT mark the task as complete** — only completes on full success
4. **Returns the partial result** — so you can inspect what succeeded/failed

## AI Logic (Identical to emailcreationskill)

All AI decisions use the same logic as the main email service:

1. **Plan phase** — Claude analyzes event details, detects stage, finds reference emails
2. **Clone selection** — AI picks the best source email (locale-aware)
3. **Content generation** — Claude mirrors reference email structure, learns tone, generates copy
4. **Safety gates** — no deletes, write locks on session email, deterministic temp=0

All AI calls route through `llm_gateway`, which:
- Pins model + temperature on every backend (SDK, API, CLI)
- Normalizes output shape
- Enforces tool safety

## Import Dependencies

```python
# Parent service (emailcreationskill)
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'emailcreationskill', 'backend'
))

import asana_tools      # from emailcreationskill
import agent            # from emailcreationskill
import content_tools    # from emailcreationskill
import hubspot_tools    # from emailcreationskill
import session_store    # from emailcreationskill
from config import ...  # from emailcreationskill
```

## Running as a Service

### FastAPI Integration

To integrate with the email staging UI or create an automation endpoint:

```python
from fastapi import FastAPI
from survey_workflow import run_asana_workflow

app = FastAPI()

@app.post("/api/survey-workflow")
async def survey(asana_url: str, dry_run: bool = False):
    """Run the Asana automation workflow."""
    return await run_asana_workflow(asana_url, dry_run=dry_run)
```

### Scheduled Tasks

Run Asana tasks automatically via cron:

```bash
# Run every morning at 8 AM
0 8 * * * python /path/to/survey_workflow/cli.py "$ASANA_URL"
```

### Cloud Functions / Lambda

```python
import asyncio
from survey_workflow import run_asana_workflow

def handler(event, context):
    asana_url = event.get("asana_url")
    result = asyncio.run(run_asana_workflow(asana_url))
    return result
```

## Testing

```bash
# Dry run (preview without marking task complete)
python survey_workflow/cli.py "<asana_url>" --dry-run --verbose

# Actual run (marks task complete)
python survey_workflow/cli.py "<asana_url>" --verbose
```

## Extending

To add new capabilities, **edit the parent service** (`emailcreationskill/backend`), not this module:

1. **New AI logic** — modify `agent.py` (both services inherit the change)
2. **New HubSpot operations** — extend `hubspot_tools.py`
3. **New Asana fields** — extend `asana_tools.extract_brief()`
4. **New task completion logic** — add to `asana_tools.py`, call from `complete_asana_task()`

## File Structure

```
survey_workflow/
├── __init__.py                 # Package exports
├── asana_workflow.py          # Core orchestration (AsanaTaskWorkflow class)
├── cli.py                     # Command-line runner
├── README.md                  # This file
└── requirements.txt           # Dependencies
```

## Architecture Diagram

```
Asana Task URL
    ↓
┌─────────────────────────────────────────────────┐
│ AsanaTaskWorkflow                               │
├─────────────────────────────────────────────────┤
│ 1. fetch_asana_task()                           │
│    → emailcreationskill/asana_tools             │
│ 2. lookup_brand_and_content()                   │
│    → emailcreationskill/content_tools           │
│    → emailcreationskill/hubspot_tools           │
│    → emailcreationskill/agent                   │
│ 3. run_full_workflow()                          │
│    → emailcreationskill/agent (plan/clone/content) │
│ 4. complete_asana_task()                        │
│    → emailcreationskill/asana_tools [WIP]       │
└─────────────────────────────────────────────────┘
    ↓
   ✓ Email staged + HubSpot draft
   ✓ Asana task marked complete
```

---

**Note:** This is a thin automation layer. All intelligence is in the parent service's AI logic. To modify email generation, adjust prompts in `emailcreationskill/backend/agent.py`, not here.
