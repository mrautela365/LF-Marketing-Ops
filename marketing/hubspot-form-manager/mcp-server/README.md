# HubSpot Form Manager — MCP Server + Web UI

A Python MCP server that replaces the `SKILL.md` browser-automation workflow with direct HubSpot API calls, exposed both as MCP tools (for Claude Code) and a web UI (for direct browser use).

## What it does

- **Create HubSpot forms** — fields, subscription type, autoresponder email, workflow enrollment
- **Delete forms** — with mandatory confirmation dialogs
- **Disable notifications** — turn off email alerts on any form
- **Asana pre-fill** (optional) — paste an Asana task URL to auto-populate form fields

All brand, subscription type, and workflow selections are always confirmed explicitly — never assumed.

---

## Quick Start

### 1. Install dependencies

```bash
cd mcp-server
pip install -e ".[dev]"
```

Requires Python 3.11+.

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:
```
HUBSPOT_API_KEY=pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ASANA_PAT=1/xxxxxxxxxxxxxxxxxxxx  # optional
PORT=8000
```

**HubSpot private app scopes needed:**
- `forms` (read + write)
- `communication-preferences` (read)
- `automation` (read + write)
- `crm.lists.read`
- `content` (for email creation)

**Alternatively**, if credentials are not set in `.env`, the server will redirect to `http://localhost:8000/setup` where you can enter them via the browser.

### 3. Start the server

```bash
python server.py
```

Or with uvicorn directly:
```bash
uvicorn server:app --reload --port 8000
```

### 4. Open the web UI

Navigate to **http://localhost:8000**

If credentials are not configured, you'll be redirected to the setup page first.

---

## Register with Claude Code

Once the server is running, add it as an MCP server:

```bash
claude mcp add --transport http hubspot-form-manager http://localhost:8000/mcp/mcp --scope project
```

Or manually add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "hubspot-form-manager": {
      "type": "http",
      "url": "http://localhost:8000/mcp/mcp"
    }
  }
}
```

For team use with credentials passed from Claude Code's environment:

```json
{
  "mcpServers": {
    "hubspot-form-manager": {
      "type": "http",
      "url": "http://localhost:8000/mcp/mcp",
      "env": {
        "HUBSPOT_API_KEY": "${HUBSPOT_API_KEY}",
        "ASANA_PAT": "${ASANA_PAT}"
      }
    }
  }
}
```

---

## Available MCP Tools

| Tool | Read/Write | Description |
|---|---|---|
| `get_hubspot_portal_id` | Read | Get portal ID and company name |
| `list_hubspot_forms` | Read | Search forms by name fragment |
| `get_hubspot_form` | Read | Get full form details |
| `list_hubspot_subscription_types` | Read | List all active subscription types |
| `find_hubspot_form_submission_list` | Read | Find the auto-created submissions list |
| `create_hubspot_form` | Write | Create a form (requires brand + subscription confirmation) |
| `delete_hubspot_forms` | Write ⚠️ | Permanently delete forms (requires `elicitInput` confirmation) |
| `update_hubspot_form_notifications` | Write | Enable/disable notification emails |
| `create_hubspot_email` | Write | Create a transactional autoresponder email |
| `enroll_form_in_workflow` | Write | Add a form-submission trigger to a workflow |
| `get_asana_task` | Read | Fetch Asana task for web form pre-fill |
| `post_asana_comment` | Write | Post completion summary to Asana task |

---

## Run Tests

```bash
pytest tests/test_naming.py tests/test_form_builder.py -v
```

These tests require no API credentials — pure unit tests.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web UI (redirects to `/setup` if unconfigured) |
| `GET` | `/setup` | Credential setup page |
| `POST` | `/api/setup` | Save credentials |
| `GET` | `/health` | Health + config status |
| `POST` | `/mcp/mcp` | MCP StreamableHTTP endpoint |
| `GET` | `/api/hubspot/portal` | Portal ID |
| `GET` | `/api/hubspot/forms/search?q=` | Form search |
| `GET` | `/api/hubspot/subscription-types` | Subscription types |
| `GET` | `/api/hubspot/workflows/search?q=` | Workflow search |
| `POST` | `/api/hubspot/forms/create` | Create form (+ email + workflow) |
| `POST` | `/api/hubspot/forms/delete` | Delete forms |
| `PATCH` | `/api/hubspot/forms/notifications` | Update notifications |
| `POST` | `/api/asana/task` | Fetch Asana task for pre-fill |
| `POST` | `/api/asana/comment` | Post Asana comment |

---

## Project Structure

```
mcp-server/
  server.py              ← FastAPI + FastMCP entry point
  src/
    mcp_tools/           ← MCP tool definitions
    api_routes/          ← REST routes for web UI
    lib/                 ← HTTP clients, naming, form builder, credentials
    models/              ← Pydantic models
  public/                ← Web UI (HTML + CSS + JS, no build step)
  tests/                 ← Unit tests
```

---

## Verify MCP Tools

```bash
npx @modelcontextprotocol/inspector \
  --cli http://localhost:8000/mcp/mcp \
  --transport http \
  --method tools/list
```
