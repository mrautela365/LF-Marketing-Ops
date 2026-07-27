# Survey Workflow — Quick Start

## What Was Created

A **standalone microservice** at `marketing/survey_workflow/` that automates email staging from Asana tasks.

```
survey_workflow/
├── asana_workflow.py      → Core orchestration (400 lines)
├── cli.py                 → CLI entry point (70 lines)
├── __init__.py            → Package exports
├── README.md              → Full documentation
├── requirements.txt       → Dependencies
└── .gitignore
```

## Key Features

✅ **Accepts ONLY Asana tasks** — pass a task URL, get an email  
✅ **Reuses emailcreationskill logic** — zero code duplication  
✅ **Same AI as email service** — identical Claude models, temperature, prompts  
✅ **Separate service** — runs independently, no conflicts  
✅ **Production-ready** — error handling, dry-run mode, logging  

## How It Works

```
Asana Task URL
    ↓
1. Extract brief (task name, brand, event URL, Google Doc)
    ↓
2. Look up HubSpot brand history (from name, suppression lists)
    ↓
3. Fetch Google Doc HTML
    ↓
4. Run email staging workflow:
   - PLAN: detect stage, find reference emails
   - CLONE: create email, apply brand settings
   - CONTENT: generate body from Google Doc + AI
    ↓
5. Mark Asana task as complete
    ↓
✓ Email staged in HubSpot
✓ Draft ready for review
```

## Quick Usage

### Option 1: Command Line

```bash
cd marketing/survey_workflow
python cli.py "https://app.asana.com/0/.../task/123" --verbose
```

### Option 2: Python Script

```python
import asyncio
from survey_workflow import run_asana_workflow

result = await run_asana_workflow("https://app.asana.com/0/.../task/123")
print(f"Email: {result['email_id']}")
print(f"Draft: {result['draft_url']}")
```

### Option 3: Step-by-Step Control

```python
from survey_workflow import AsanaTaskWorkflow

wf = AsanaTaskWorkflow(asana_url)
await wf.fetch_asana_task()
await wf.lookup_brand_and_content()
result = await wf.run_full_workflow()
await wf.complete_asana_task()
```

## Return Value

```python
{
    "success": True,                    # True/False
    "email_id": "12345678",            # HubSpot email ID
    "email_name": "26Q3 - ...",        # Email name
    "draft_url": "https://app.hubspot.com/...",  # Draft link
    "warnings": ["No brand history found"],      # Non-fatal issues
    "completed_task": {
        "success": True,
        "task_gid": "123456789",
        "message": "Task marked as complete"
    }
}
```

## Configuration (Shared with emailcreationskill)

Use the same `.env` file:

```bash
ASANA_ACCESS_TOKEN=your_token          # (optional; falls back to MCP)
ANTHROPIC_API_KEY=your_key
HUBSPOT_PORTAL_ID=8112310
HUBSPOT_PRIVATE_APP_TOKEN=your_token
CLAUDE_MODEL=claude-3-5-sonnet-20241022
```

## What It Imports

Survey Workflow imports from `emailcreationskill/backend/`:

- `agent.py` → AI orchestration
- `asana_tools.py` → Asana task extraction
- `hubspot_tools.py` → Email operations
- `content_tools.py` → URL scraping, Google Doc
- `llm_gateway.py` → AI determinism
- `session_store.py` → Session management
- `event_brands.py` → Brand mapping

**No code duplication.** Any fix/improvement to `emailcreationskill` automatically flows through to `survey_workflow`.

## Error Handling

If any step fails:
- The error is logged with full context
- Warnings are stored in the result
- **The Asana task is NOT marked complete** (only on full success)
- The partial result is returned so you can inspect what happened

Example:
```python
result = await run_asana_workflow(asana_url)
if not result["success"]:
    print(f"Error: {result['error']}")
    for warning in result["warnings"]:
        print(f"  - {warning}")
```

## Dry Run Mode

Test without marking the Asana task as complete:

```bash
python cli.py "<url>" --dry-run
```

or

```python
result = await run_asana_workflow(asana_url, dry_run=True)
```

## Extending

To add features, **edit the parent service**, not this module:

| To add... | Edit... |
|-----------|---------|
| New AI logic | `emailcreationskill/backend/agent.py` |
| New HubSpot ops | `emailcreationskill/backend/hubspot_tools.py` |
| New Asana fields | `emailcreationskill/backend/asana_tools.py` |
| Task completion | `emailcreationskill/backend/asana_tools.py` (add `update_task()`) |

Both services inherit the change automatically.

## Asana Task Format

The workflow expects tasks like:

```
Task Name: 26Q3 - CNCF - KubeCon NA - Invite

Subtasks:
├── Event URL
│   Notes: https://events.linuxfoundation.org/kubecon-na-2026/
├── Content
│   Notes: https://docs.google.com/document/d/...
└── List Pull
    Notes: [audience segmentation instructions]
```

The workflow extracts:
- **Brand** from task name pattern (`YYQn - BRAND - ...`)
- **Event URL** from Event URL subtask
- **Google Doc** from Content subtask
- **Audience instructions** from List Pull subtask

## Testing

```bash
# List available options
python cli.py --help

# Verbose output (see what's happening)
python cli.py "<url>" --verbose

# Dry run (safe preview)
python cli.py "<url>" --dry-run --verbose
```

## Logging

The service logs to console with timestamps:

```
20:43:15 [INFO] asana-workflow: [ASANA-WF] Fetching task from URL: ...
20:43:16 [INFO] asana-workflow: [ASANA-WF] REST API fetch: task='26Q3 - CNCF - ...'
20:43:18 [INFO] asana-workflow: [ASANA-WF] Selected clone base: 'Q2 - CNCF - ...'
20:43:45 [INFO] asana-workflow: [ASANA-WF] Workflow complete: email_id=12345678
```

Set `--verbose` in CLI or `logging.getLogger().setLevel(logging.DEBUG)` in Python for more details.

## Next Steps

1. **Install deps** (once):
   ```bash
   cd ../emailcreationskill && pip install -r requirements.txt
   cd ../survey_workflow && pip install -r requirements.txt
   ```

2. **Set up .env** (shared with emailcreationskill):
   ```bash
   cp ../emailcreationskill/.env.example .env
   # Edit with your tokens
   ```

3. **Try it**:
   ```bash
   python cli.py "https://app.asana.com/0/.../task/123" --verbose
   ```

4. **Integrate** (optional):
   - Add FastAPI endpoint to `emailcreationskill/main.py`
   - Set up scheduled task in cron/Cloud Tasks
   - Deploy as separate microservice

## Files

| File | Purpose |
|------|---------|
| `asana_workflow.py` | Core orchestration — `AsanaTaskWorkflow` class |
| `cli.py` | Command-line entry point |
| `__init__.py` | Package exports (`run_asana_workflow`, `AsanaTaskWorkflow`) |
| `README.md` | Full documentation |
| `QUICKSTART.md` | This file |
| `requirements.txt` | Dependencies (shared with parent) |

## Support

- See `README.md` for full documentation
- Check `emailcreationskill/backend/agent.py` for AI logic
- Check `emailcreationskill/backend/asana_tools.py` for task extraction

---

**Made with ❤️ as a separate microservice, zero code duplication, pure orchestration.**
