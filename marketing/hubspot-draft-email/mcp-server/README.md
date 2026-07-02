# HubSpot Draft Email — MCP Server

A FastAPI + FastMCP server for creating, validating, and managing HubSpot marketing email drafts.
Mirrors the structure of `hubspot-form-manager` with a full skill-aligned QA layer.

## Features

- **Full draft lifecycle** — create, update, QA check, schedule, delete
- **5-section QA suite** — sender, subscription, consent, content, sense check
- **UTM auto-tagging** — scans all links and applies corrected UTM URLs
- **Guardrails** — blocks drafts with critical issues; confirms before destructive actions
- **Web UI** — 3-tab browser interface (Compose, QA Review, Drafts)
- **MCP endpoint** — Claude connects via `http://localhost:8001/mcp/mcp`

## Setup

```bash
cd mcp-server
cp .env.example .env
# Fill in HUBSPOT_API_KEY in .env

pip install -e ".[dev]"
python server.py
```

Then open http://localhost:8001 — you'll be redirected to /setup if credentials aren't set.

## HubSpot Private App Scopes Required

| Scope | Purpose |
|---|---|
| `marketing-email` | Create/read/update/delete email drafts |
| `communication-preferences` | Read subscription types |
| `crm.lists.read` | Validate audience lists |
| `content` | Access email content |

## MCP Tools

| Tool | Description |
|---|---|
| `get_hubspot_portal` | Get portal ID and company name |
| `list_hubspot_subscription_types` | List subscription options (confirm with user before use) |
| `validate_audience_lists` | Health check on audience/suppression lists |
| `search_hubspot_lists` | Find lists by name |
| `run_email_qa` | Full 5-section QA — run before creating any draft |
| `create_email_draft` | Create a draft (blocked if QA verdict is BLOCKED) |
| `list_email_drafts` | Browse existing drafts |
| `get_email_draft` | Fetch full draft details |
| `update_email_draft` | Patch draft fields |
| `apply_utm_corrections` | Auto-tag all links with UTM parameters |
| `delete_email_draft` | Delete a draft (with confirmation) |
| `schedule_email_send` | Schedule a draft for send (with pre-schedule QA) |

## Guardrails

- `subscription_type_id` must be explicitly confirmed by the user
- `from_email` must be a brand domain (no Gmail/Yahoo/Hotmail)
- `reply_to` must not be a noreply@ address
- Email body must contain an unsubscribe link
- `run_email_qa` verdict must not be `BLOCKED` before calling `create_email_draft`
- Destructive actions (delete) always require explicit confirmation via `ctx.elicit()`
- Schedule always runs a pre-send QA check for unsubscribe link + subscription type

## Workflow (Claude follows this automatically via SKILL.md)

```
1. validate_audience_lists → check size, type, consent
2. list_hubspot_subscription_types → show user, confirm selection
3. run_email_qa → get verdict (READY / NEEDS_CHANGES / BLOCKED)
4. If BLOCKED → surface issues, do NOT create draft
5. create_email_draft → always DRAFT, never auto-send
6. apply_utm_corrections (if needed)
7. schedule_email_send (when user confirms)
```

## Tests

```bash
pytest tests/ -v
```

## Port

Default port: `8001` (avoids conflict with hubspot-form-manager on 8000).
Override with `PORT=XXXX` in `.env` or environment.
