# HubSpot Form Manager — Complete Technical Documentation

> **Version:** 1.0.0 | **Python:** 3.11+ | **MCP SDK:** 1.6.0

---

## Table of Contents

1. [What This Is](#1-what-this-is)
2. [Architecture Overview](#2-architecture-overview)
3. [Project Structure](#3-project-structure)
4. [How to Run](#4-how-to-run)
5. [Credential Resolution](#5-credential-resolution)
6. [Library Layer (`src/lib/`)](#6-library-layer-srclib)
7. [Data Models (`src/models/`)](#7-data-models-srcmodels)
8. [MCP Tools (`src/mcp_tools/`)](#8-mcp-tools-srcmcp_tools)
9. [REST API Routes (`src/api_routes/`)](#9-rest-api-routes-srcapi_routes)
10. [Web UI (`public/`)](#10-web-ui-public)
11. [Request Flows — Step by Step](#11-request-flows--step-by-step)
12. [Brand & Confirmation Rules](#12-brand--confirmation-rules)
13. [HubSpot APIs Used](#13-hubspot-apis-used)
14. [Claude Code Integration](#14-claude-code-integration)
15. [Tests](#15-tests)
16. [Dependency Reference](#16-dependency-reference)

---

## 1. What This Is

This project converts the `SKILL.md` browser-automation workflow for managing HubSpot forms into a proper **Python MCP server** with a **web UI**.

### Before (SKILL.md)
- Claude reads a pasted Asana URL
- Claude manually navigates HubSpot in a browser via Chrome Extension MCP
- Confirmations are plain English messages in chat
- Only works where the Chrome Extension MCP is connected
- Each form creation takes minutes of browser navigation

### After (This MCP Server)
- Users fill in a web form directly in the browser — **no Asana URL required**
- Asana URL is optional, used only to pre-fill form fields as hints
- Server calls HubSpot REST APIs directly — seconds per operation
- Confirmations are enforced in code (`ctx.elicit()` for MCP, modal dialogs for web UI)
- Works in any Claude surface (Claude Code, Claude Desktop, claude.ai)
- Brand / subscription / workflow are **always confirmed** — never assumed

### Three Surfaces, One Server

```
http://localhost:8000/
│
├── GET  /             → Web UI (3-tab form manager)
├── GET  /setup        → Credential setup page
├── POST /mcp/mcp      → MCP StreamableHTTP endpoint (Claude Code)
├── GET  /api/*        → REST endpoints (called by the web UI)
└── GET  /health       → Health + config status check
```

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         server.py                               │
│                                                                 │
│  FastAPI app                    FastMCP server                  │
│  ┌──────────────────┐           ┌───────────────────┐           │
│  │ REST API routes  │           │  12 MCP tools     │           │
│  │ /api/hubspot/*   │           │  registered via   │           │
│  │ /api/asana/*     │           │  register(mcp)    │           │
│  │ /setup           │           │                   │           │
│  │ /health          │           │  Mounted at /mcp  │           │
│  │ / (web UI)       │           │  (StreamableHTTP) │           │
│  └────────┬─────────┘           └────────┬──────────┘           │
│           │                              │                      │
│           └──────────┬───────────────────┘                      │
│                      │ both use the same                        │
│                      ▼  underlying functions                    │
│  ┌───────────────────────────────────────────┐                  │
│  │  src/lib/                                 │                  │
│  │  hubspot_client.py  →  HubSpot REST API   │                  │
│  │  asana_client.py    →  Asana REST API     │                  │
│  │  naming.py          →  pure logic         │                  │
│  │  form_builder.py    →  pure logic         │                  │
│  │  credentials.py     →  env/file/setup     │                  │
│  └───────────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘

External APIs:
  HubSpot  →  api.hubapi.com
  Asana    →  app.asana.com/api/1.0
```

### Key Design Principle: No Duplicated Logic

The MCP tools and the REST API routes call the **same** underlying `src/lib/` functions. There is no duplication — change the HubSpot client once and both surfaces benefit.

---

## 3. Project Structure

```
mcp-server/
│
├── server.py                      Entry point — FastAPI + FastMCP wiring
├── pyproject.toml                 Dependencies and project metadata
├── .env.example                   Credential template to copy
├── README.md                      Quick-start guide
├── DOCUMENTATION.md               This file
│
├── src/
│   │
│   ├── lib/                       Core library — no FastAPI/MCP imports
│   │   ├── credentials.py         3-tier credential resolution
│   │   ├── hubspot_client.py      Async HubSpot HTTP client (auth + retry)
│   │   ├── asana_client.py        Async Asana HTTP client
│   │   ├── naming.py              Form naming convention logic (pure functions)
│   │   └── form_builder.py        Field spec → HubSpot fieldGroups mapper
│   │
│   ├── models/
│   │   └── hubspot.py             All Pydantic v2 request/response models
│   │
│   ├── mcp_tools/                 MCP tool definitions (registered in server.py)
│   │   ├── hubspot_account.py     get_hubspot_portal_id
│   │   ├── hubspot_forms.py       list / get / create / delete / update_notifications
│   │   ├── hubspot_marketing.py   subscription types / email / workflow / list
│   │   └── asana.py               get_asana_task / post_asana_comment
│   │
│   └── api_routes/                REST routes for the web UI
│       ├── hubspot.py             /api/hubspot/* endpoints
│       ├── asana.py               /api/asana/* endpoints
│       └── setup.py               /setup credential management page + endpoint
│
├── public/                        Web UI — served as static files, no build step
│   ├── index.html                 3-tab interface
│   ├── app.js                     All frontend logic (vanilla JS)
│   └── style.css                  Styling
│
└── tests/
    ├── test_naming.py             12 unit tests for naming.py
    └── test_form_builder.py       9 unit tests for form_builder.py
```

---

## 4. How to Run

### Step 1 — Install

```bash
cd mcp-server
pip install -e ".[dev]"
```

Requires **Python 3.11+**.

### Step 2 — Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:
```
HUBSPOT_API_KEY=pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ASANA_PAT=1/xxxx...          # optional — only needed for Asana pre-fill
PORT=8000
```

**Alternatively**, skip `.env` entirely — the server will redirect to `/setup` where you can enter credentials via the browser.

**HubSpot Private App scopes required:**
- `forms` — read + write
- `communication-preferences` — read (subscription types)
- `automation` — read + write (workflows)
- `crm.lists.read` — find submission lists
- `content` — create emails

### Step 3 — Start

```bash
python server.py
```

### Step 4 — Open

- **Web UI:** http://localhost:8000
- **Health check:** http://localhost:8000/health
- **Credential setup:** http://localhost:8000/setup

### Step 5 — Register with Claude Code

```bash
claude mcp add --transport http hubspot-form-manager http://localhost:8000/mcp/mcp --scope project
```

---

## 5. Credential Resolution

**File:** `src/lib/credentials.py`

The server resolves credentials at startup using a three-tier priority. No code changes are needed to switch between environments:

```
Priority 1  →  os.environ already set
               Covers: Claude Code MCP config "env" block, shell exports
               Action: Used silently, no file read needed

Priority 2  →  .env file in the mcp-server directory
               Covers: Developer local setup
               Action: python-dotenv loads it at module import time

Priority 3  →  Neither found
               Action: Server starts but marks itself "unconfigured"
                       GET / redirects to GET /setup
                       User enters keys in browser
                       POST /api/setup saves to .env and reloads os.environ
```

### Key Functions

| Function | Returns | Notes |
|---|---|---|
| `get_hubspot_api_key()` | `str \| None` | Returns the key or None |
| `get_asana_pat()` | `str \| None` | Returns the PAT or None |
| `is_hubspot_configured()` | `bool` | HubSpot key is present |
| `is_asana_configured()` | `bool` | Asana PAT is present |
| `is_fully_configured()` | `bool` | HubSpot required; Asana optional |
| `save_credentials(hs_key, asana_pat)` | `None` | Writes to .env, reloads os.environ |

### Claude Code MCP Config with Credentials

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

If `HUBSPOT_API_KEY` is already set in Claude Code's environment, it passes through automatically — no `.env` file needed.

---

## 6. Library Layer (`src/lib/`)

### 6.1 `hubspot_client.py` — HubSpot API Client

Async HTTP client for all HubSpot API calls.

**Base URL:** `https://api.hubapi.com`  
**Auth:** `Authorization: Bearer {HUBSPOT_API_KEY}` on every request  
**Retry:** Up to 3 retries on HTTP 429 (rate limit) with exponential backoff

```python
# Helper functions — use these throughout the codebase
await hs_get("/marketing/v3/forms/", params={"limit": 20})
await hs_post("/marketing/v3/forms/", json={...})
await hs_patch("/marketing/v3/forms/{id}", json={...})
await hs_delete("/marketing/v3/forms/{id}")
```

If `HUBSPOT_API_KEY` is not set, calling any of these raises `RuntimeError` with a message pointing to `/setup`.

### 6.2 `asana_client.py` — Asana API Client

Async HTTP client for Asana API calls.

**Base URL:** `https://app.asana.com/api/1.0`  
**Auth:** `Authorization: Bearer {ASANA_PAT}`

```python
# Extract GID from any Asana URL format
gid = extract_task_gid("https://app.asana.com/1/.../task/1214761275486487")
# → "1214761275486487"

# Also accepts bare GID
gid = extract_task_gid("1214761275486487")
# → "1214761275486487"

await asana_get(f"/tasks/{gid}", params={"opt_fields": "gid,name,notes"})
await asana_post(f"/tasks/{gid}/stories", json={"data": {"text": "..."}})
```

Supported Asana URL patterns:
- `https://app.asana.com/1/{workspace}/project/{project}/task/{task_id}`
- `https://app.asana.com/0/{project}/{task_id}`
- `https://app.asana.com/0/search/{task_id}`

### 6.3 `naming.py` — Form Naming Convention

Pure functions (no I/O) for LF Events naming convention:

**Pattern:** `[YYQ#] - [Team] - [Event Name] [Year]`  
**Example:** `26Q2 - LF Events - CloudNativeCon Europe 2026`

```python
# Parse an existing form name into parts
parse_name_parts("26Q1 - LF Events - MCP NA 2026")
# → {"quarter": "26Q1", "team": "LF Events", "event": "MCP NA", "year": "2026"}

# Derive a new name from a reference form
derive_form_name(
    reference_form_name="26Q1 - LF Events - MCP NA 2026",
    new_event_name="CloudNativeCon Europe",
    new_quarter="26Q2"
)
# → "26Q2 - LF Events - CloudNativeCon Europe 2026"

# Build from scratch (no reference form)
suggest_form_name("DockerCon 2026", "LF Events", "26Q2", "2026")
# → "26Q2 - LF Events - DockerCon 2026 2026"
```

Rules:
- Team segment is always preserved from the reference form
- Year is taken from: explicit override → reference form → inferred from quarter prefix (`26Q2` → `2026`)
- Invalid quarter format raises `ValueError`

### 6.4 `form_builder.py` — Field Group Builder

Converts the simplified field spec used by the web UI and MCP tools into the HubSpot v3 Forms API `fieldGroups` schema.

**Input (simplified):**
```python
[
  {"name": "First Name", "type": "text",  "required": True},
  {"name": "Email",      "type": "email", "required": True},
  {"name": "Country",    "type": "country","required": False},
  {"name": "Role",       "type": "select","required": False,
   "options": ["Engineer", "Manager", "Director"]}
]
```

**Output (HubSpot fieldGroups):**
```python
[{
  "groupType": "default_group",
  "richTextType": "text",
  "fields": [
    {"objectTypeId": "0-1", "name": "firstname", "label": "First Name",
     "fieldType": "single_line_text", "required": True},
    {"objectTypeId": "0-1", "name": "email", "label": "Email",
     "fieldType": "email", "required": True},
    {"objectTypeId": "0-1", "name": "country", "label": "Country",
     "fieldType": "dropdown", "required": False},
    {"objectTypeId": "0-1", "name": "role", "label": "Role",
     "fieldType": "dropdown", "required": False,
     "options": [{"label": "Engineer", "value": "engineer"}, ...]}
  ]
}]
```

**Built-in field name mappings** (maps label → HubSpot property name):

| Label | HubSpot property |
|---|---|
| First Name / firstname | `firstname` |
| Last Name / lastname | `lastname` |
| Email / Email Address | `email` |
| Phone / Phone Number | `phone` |
| Company | `company` |
| Country / Country/Region | `country` |
| Job Title / jobtitle | `jobtitle` |
| Website | `website` |
| Message | `message` |

Any other field label is slugified: `"Special Project Name"` → `"special_project_name"`

**Supported field types:**

| Input type | HubSpot fieldType |
|---|---|
| `text` | `single_line_text` |
| `email` | `email` |
| `phone` | `phone_number` |
| `textarea` | `multi_line_text` |
| `select` | `dropdown` |
| `checkbox` | `single_checkbox` |
| `number` | `number` |
| `country` | `dropdown` |
| `date` | `date` |
| unknown | `single_line_text` (fallback) |

---

## 7. Data Models (`src/models/`)

**File:** `src/models/hubspot.py`

All Pydantic v2 models used by both the REST API routes and as documentation for the MCP tool inputs.

### `FormField`
```python
class FormField(BaseModel):
    name: str               # Human label, e.g. "First Name"
    type: str = "text"      # text|email|phone|textarea|select|checkbox|number|country|date
    required: bool = False
    options: list[str] = [] # Only for select/dropdown fields
```

### `CreateFormRequest`
```python
class CreateFormRequest(BaseModel):
    name: str                        # Form name, e.g. "26Q2 - LF Events - ..."
    brand: str                       # REQUIRED — never assumed
    fields: list[FormField] = []
    submit_button_text: str = "Submit"
    thank_you_message: str = "Thank you for your submission."
    notification_emails: list[str] = []  # Empty = no notifications
    subscription_type_id: str            # REQUIRED — confirmed by user
    # Optional autoresponder
    autoresponder_subject: str | None = None
    autoresponder_from_name: str | None = None
    autoresponder_from_email: str | None = None
    autoresponder_body_html: str | None = None
    # Optional workflow
    workflow_name_query: str | None = None
```

### `DeleteFormsRequest`
```python
class DeleteFormsRequest(BaseModel):
    form_ids: list[str]        # HubSpot form GUIDs
    confirmed_names: list[str] # Matching names for confirmation display
```

### `ApiResponse` (standard response envelope)
```python
class ApiResponse(BaseModel):
    success: bool
    data: Any = None
    error: str | None = None
```

All REST endpoints return this envelope:
```json
{"success": true,  "data": {...}, "error": null}
{"success": false, "data": null,  "error": "error message"}
```

---

## 8. MCP Tools (`src/mcp_tools/`)

All tools are registered with the `FastMCP` instance in `server.py` via `register(mcp)` functions. The MCP endpoint is at `http://localhost:8000/mcp/mcp` (StreamableHTTP transport).

### 8.1 Account Tools — `hubspot_account.py`

#### `get_hubspot_portal_id`
- **Type:** Read-only
- **Inputs:** None
- **Returns:** `{portal_id, company_name, hub_domain}`
- **API:** `GET /account-info/v3/details`
- **Use for:** Building direct HubSpot deep-links, e.g. `https://app.hubspot.com/forms/{portalId}`

---

### 8.2 Form Tools — `hubspot_forms.py`

#### `list_hubspot_forms`
- **Type:** Read-only
- **Inputs:** `query: str = ""`, `limit: int = 20`
- **Returns:** `[{id, name, formType, createdAt, updatedAt}]`
- **API:** `GET /marketing/v3/forms/`
- **Use for:** Type-ahead search, finding reference forms, resolving names to IDs before deletion

#### `get_hubspot_form`
- **Type:** Read-only
- **Inputs:** `form_id: str`
- **Returns:** Full form object including `fieldGroups`, `configuration`, `legalConsentOptions`, `notificationEmails`
- **API:** `GET /marketing/v3/forms/{id}`
- **Use for:** Inspecting a reference form to copy thank-you message or email structure

#### `create_hubspot_form`
- **Type:** Write
- **Inputs:** `name, brand, fields[], submit_button_text, thank_you_message, notification_emails[], subscription_type_id, ctx`
- **Returns:** `{status, form_id, name, hubspot_url, brand}` on success; `{action_required, message}` if brand or subscription missing
- **API:** `POST /marketing/v3/forms/`
- **Confirmation:** Calls `ctx.elicit()` before creating — shows full summary to user
- **Safety rules:**
  - If `brand` is empty → returns `action_required: "confirm_brand"` instead of creating
  - If `subscription_type_id` is empty → returns `action_required: "confirm_subscription_type"`
  - Falls back to text prompt if host doesn't support `elicit()`

#### `delete_hubspot_forms`
- **Type:** Write (destructive)
- **Inputs:** `form_ids: list[str]`, `confirmed_names: list[str]`, `ctx`
- **Returns:** `[{form_id, name, status}]` where status is `"deleted"`, `"not_found"`, or `"error"`
- **API:** `DELETE /marketing/v3/forms/{id}` per form
- **Confirmation:** **Always** calls `ctx.elicit()` with "CANNOT be undone" message before touching any form
- **Error handling:** Per-form error capture — if one form fails, continues with others

#### `update_hubspot_form_notifications`
- **Type:** Write
- **Inputs:** `form_id: str`, `notification_emails: list[str]`
- **Returns:** `{form_id, notification_emails, status}`
- **API:** `PATCH /marketing/v3/forms/{id}`
- **Use for:** Pass empty list to disable all notifications

---

### 8.3 Marketing Tools — `hubspot_marketing.py`

#### `list_hubspot_subscription_types`
- **Type:** Read-only
- **Inputs:** None
- **Returns:** `[{id, name, description, isActive}]`
- **API:** `GET /communication-preferences/v3/definitions`
- **Critical use:** Call this BEFORE `create_hubspot_form` to show the user real subscription type names. The user must explicitly select one — never inherit from a reference form without confirmation.

#### `find_hubspot_form_submission_list`
- **Type:** Read-only
- **Inputs:** `form_name: str`
- **Returns:** `{list_id, name, list_url}` or `{list_id: null, note: "try again shortly"}`
- **API:** `GET /contacts/v1/lists/`
- **Note:** HubSpot auto-creates a list named `"[Form name] (HubSpot form submissions)"`. May take a few minutes after form creation to appear.

#### `create_hubspot_email`
- **Type:** Write
- **Inputs:** `name, subject, from_name, from_email, body_html, is_transactional: bool = True`
- **Returns:** `{email_id, name, subject, from_email, is_transactional, preview_url, status}`
- **API:** `POST /marketing/v3/emails/`
- **Note:** `is_transactional=True` bypasses subscription status — all form submitters receive it regardless of opt-in. Use this for confirmation/livestream emails.

#### `enroll_form_in_workflow`
- **Type:** Write
- **Inputs:** `workflow_name_query: str`, `form_id: str`, `ctx`
- **Returns:** `{workflow_id, workflow_name, form_id, status}` or `{action_required, message}`
- **API:** `GET /automation/v4/flows/` + `PATCH /automation/v4/flows/{id}/enrollmentCriteria`
- **Disambiguation:** If multiple workflows match the query, calls `ctx.elicit()` to ask the user to choose
- **Fallback:** If the PATCH API fails, returns a `manual_action_required` status with a direct HubSpot URL

---

### 8.4 Asana Tools — `asana.py`

#### `get_asana_task`
- **Type:** Read-only
- **Inputs:** `task_id: str` (URL or bare GID)
- **Returns:** `{gid, name, notes, assignee, completed, permalink_url, prefill}`
- **API:** `GET /tasks/{gid}?opt_fields=gid,name,notes,assignee.name,completed,permalink_url`
- **The `prefill` object:**
  ```json
  {
    "request_types": ["FORM_CREATION"],
    "form_name_hint": "26Q2 - LF Events - CloudNativeCon 2026",
    "from_address_hint": "events@aaif.io",
    "workflow_hint": "AAIF Newsletter Workflow",
    "brand_hint": "AAIF",
    "subscription_hint": "AAIF Newsletter",
    "hint_only": true,
    "note": "These are hints — brand and subscription MUST be confirmed by user"
  }
  ```
- **Request type classification** (heuristic, from task notes):
  - `FORM_CREATION` — keywords: "new form", "signup form", "set up a form", etc.
  - `FORMS_TO_DELETE` — keywords: "delete", "remove", "unused", "clean up"
  - `NOTIFICATIONS_TO_DISABLE` — keywords: "turn off notification", "disable notification"
  - `OTHER` — none of the above matched

#### `post_asana_comment`
- **Type:** Write
- **Inputs:** `task_id: str`, `text: str`
- **Returns:** `{story_gid, created_at, text_preview, status}`
- **API:** `POST /tasks/{gid}/stories`
- **Use for:** Posting the completion summary (form URL, signup list URL, email URL) back to the Asana task

---

## 9. REST API Routes (`src/api_routes/`)

These endpoints are called by the web UI. They use the same underlying `src/lib/` functions as the MCP tools.

### 9.1 HubSpot Routes — `/api/hubspot/`

| Method | Path | Request | Response |
|---|---|---|---|
| `GET` | `/api/hubspot/portal` | — | `{portal_id, company_name}` |
| `GET` | `/api/hubspot/forms/search?q=&limit=` | — | `[{id, name, formType}]` |
| `GET` | `/api/hubspot/forms/{form_id}` | — | Full form object |
| `GET` | `/api/hubspot/subscription-types` | — | `[{id, name, description}]` |
| `GET` | `/api/hubspot/workflows/search?q=` | — | `[{id, name}]` |
| `POST` | `/api/hubspot/forms/create` | `CreateFormRequest` | `{form_id, form_name, hubspot_form_url, email_preview_url, workflow_status}` |
| `POST` | `/api/hubspot/forms/delete` | `DeleteFormsRequest` | `[{form_id, name, status}]` |
| `PATCH` | `/api/hubspot/forms/notifications` | `UpdateNotificationsRequest` | `{form_id, notification_emails}` |

**Note on `POST /api/hubspot/forms/create`:**  
This is a composite operation. In one request it:
1. Creates the HubSpot form
2. Creates the autoresponder email (if `autoresponder_subject` is provided)
3. Enrolls in a workflow (if `workflow_name_query` is provided)

The web UI sends `confirmed: true` in the body after showing its own confirmation modal. The endpoint trusts this.

### 9.2 Asana Routes — `/api/asana/`

| Method | Path | Request | Response |
|---|---|---|---|
| `POST` | `/api/asana/task` | `{url: str}` | `{gid, name, notes, permalink_url, prefill}` |
| `POST` | `/api/asana/comment` | `{task_id, text}` | `{story_gid, created_at}` |

### 9.3 Setup Routes

| Method | Path | Returns |
|---|---|---|
| `GET` | `/setup` | HTML page with credential entry form |
| `POST` | `/api/setup` | `{success, data: {hubspot_configured, asana_configured}}` |

The setup page is an inline HTML string returned from the route (no template file needed). It shows masked existing credentials, a form for entering new ones, and a link back to the main UI once configured.

---

## 10. Web UI (`public/`)

Three files, no build step. Served as static files from the `public/` directory.

### 10.1 `index.html` — Structure

Three-tab layout:

```
┌──────────────────────────────────────────────────────────────┐
│  🧩 HubSpot Form Manager                    ⚙️ Settings      │
├──────────────────────────────────────────────────────────────┤
│  [➕ Create Form]  [🗑️ Delete Forms]  [🔕 Disable Notifications] │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  [Tab content — see below]                                  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Tab 1 — Create Form:**

```
┌─ Asana task URL (optional) ─────────────────────────────────┐
│ [https://app.asana.com/...          ] [Pre-fill]            │
│ ⚠️ These are suggestions — you must review and confirm       │
└─────────────────────────────────────────────────────────────┘

┌─ Form Details ──────────────────────────────────────────────┐
│ Brand / Business Unit *   [LF Events, AAIF, OpenSSF...]     │
│ Form Name *               [26Q2 - LF Events - ...]          │
│ Reference Form            [Search existing forms...]        │
│ Submit Button Text        [Submit]                          │
│ Thank-You Message         [Thank you for registering!]      │
└─────────────────────────────────────────────────────────────┘

┌─ Form Fields ───────────────────────────────────────────────┐
│ [First Name    ] [text   ] [☑ Required] [✕]                 │
│ [Last Name     ] [text   ] [☑ Required] [✕]                 │
│ [Email Address ] [email  ] [☑ Required] [✕]                 │
│ [Company       ] [text   ] [☐ Required] [✕]                 │
│ [+ Add Field]                                               │
└─────────────────────────────────────────────────────────────┘

┌─ Subscription & Notifications ──────────────────────────────┐
│ Subscription Type *  [▼ Select subscription type...]        │
│ Notification Emails  [leave blank for no notifications]     │
└─────────────────────────────────────────────────────────────┘

┌─ Autoresponder Email (optional) ────────────────────────────┐
│ Subject     [You're registered — CloudNativeCon 2026]       │
│ From Name   [LF Events]                                     │
│ From Email  [events@aaif.io]                                │
│ Body        [HTML or plain text...]                         │
└─────────────────────────────────────────────────────────────┘

┌─ Workflow Enrollment (optional) ────────────────────────────┐
│ Workflow    [Search workflows by name... e.g. AAIF]         │
└─────────────────────────────────────────────────────────────┘

[Create Form]  [Reset]

✅ Form created successfully!
📋 Form name: 26Q2 - LF Events - CloudNativeCon Europe 2026
🔗 HubSpot URL: https://app.hubspot.com/forms/...
📧 Autoresponder: https://app.hubspot.com/email/...
```

**Tab 2 — Delete Forms:**

```
┌─ Search Forms to Delete ────────────────────────────────────┐
│ [search by name...] [Search]                                │
│                                                             │
│ ☐ 26Q1 - LF Events - MCP NA 2026          abc123           │
│ ☐ 25Q4 - OpenSSF - Summit 2025            def456           │
│ ☑ 25Q3 - AAIF - DevSummit 2025            ghi789   ←selected│
└─────────────────────────────────────────────────────────────┘

┌─ Confirm Deletion ──────────────────────────────────────────┐
│ ⚠️ ☐ I understand that deleting these forms is permanent    │
│     and cannot be undone.                                   │
│                                                             │
│ [🗑️ Delete Selected Forms]   1 form(s) selected             │
└─────────────────────────────────────────────────────────────┘
```

**Tab 3 — Disable Notifications:**
```
┌─ Search Forms ──────────────────────────────────────────────┐
│ [search by name...] [Search]                                │
│ ☑ LF Events Newsletter Form 2026                            │
│ ☐ AAIF Signup Form                                          │
└─────────────────────────────────────────────────────────────┘

[🔕 Disable Notifications on Selected]   1 form(s) selected
```

### 10.2 `app.js` — Frontend Logic

Key functions and features:

| Feature | How it works |
|---|---|
| Tab switching | `data-tab` attribute on buttons → shows/hides `.tab-content` divs |
| Autocomplete | `setupAutocomplete()` helper: debounced input → `fetch /api/*` → dropdown list |
| Reference form search | Searches `/api/hubspot/forms/search`, on select fetches full form to copy thank-you message |
| Workflow search | Searches `/api/hubspot/workflows/search`, stores selected `workflow-id` and `workflow-name` |
| Field builder | `addField()` adds a row; `getFields()` collects all rows into array |
| Subscription dropdown | Loaded from `/api/hubspot/subscription-types` on page load |
| Asana pre-fill | `POST /api/asana/task` → populates fields as suggestions + shows warning banner |
| Confirmation modal | `openModal(title, body)` returns a Promise → resolves `true`/`false` |
| Create form | Validates required fields → modal → `POST /api/hubspot/forms/create` → shows result |
| Delete forms | Search → checklist → confirm checkbox → modal → `POST /api/hubspot/forms/delete` |
| Disable notifications | Search → checklist → `PATCH /api/hubspot/forms/notifications` in loop |

### 10.3 `style.css` — Design Tokens

```css
--primary: #ff7a59    /* HubSpot orange */
--success: #00bda5    /* Teal */
--danger:  #f2545b    /* Red */
--warning: #f5c26b    /* Amber */
--text:    #2d3748    /* Dark slate */
--border:  #e2e8f0    /* Light gray */
```

---

## 11. Request Flows — Step by Step

### Flow A: Create Form via Web UI

```
1. User opens http://localhost:8000
   └─ server.py GET / → FileResponse(public/index.html)

2. Page loads — app.js calls:
   └─ GET /api/hubspot/subscription-types
      └─ hubspot.py → hs_get("/communication-preferences/v3/definitions")
      └─ Populates <select id="subscription-type"> dropdown

3. [Optional] User pastes Asana URL:
   └─ POST /api/asana/task  {"url": "https://app.asana.com/..."}
      └─ asana_routes.py → asana_client.extract_task_gid() → asana_get("/tasks/{gid}")
      └─ Returns prefill hints (brand_hint, form_name_hint, etc.)
      └─ app.js populates fields + shows ⚠️ banner "these are suggestions"

4. User fills Brand, Form Name, Fields, Subscription Type, etc.

5. User clicks [Create Form]
   └─ app.js validates required fields (brand, name, subscription, at least one field)
   └─ app.js opens confirmation modal with full summary
   └─ User clicks Confirm in modal

6. POST /api/hubspot/forms/create  {name, brand, fields, subscription_type_id, ...}
   └─ hubspot.py route:
      a. build_field_groups(fields)          ← form_builder.py
      b. POST /marketing/v3/forms/           ← hs_post()
      c. [if autoresponder] POST /marketing/v3/emails/
      d. [if workflow] GET /automation/v4/flows/ → PATCH .../enrollmentCriteria
   └─ Returns {form_id, form_name, hubspot_form_url, email_preview_url, workflow_status}

7. app.js shows ✅ result with clickable HubSpot links
```

### Flow B: Create Form via Claude Code (MCP)

```
1. User: "Create a signup form for CloudNativeCon Europe 2026 Q2 — it's for AAIF"

2. Claude calls get_hubspot_portal_id()
   └─ Returns {portal_id: 12345678, company_name: "Linux Foundation"}

3. Claude calls list_hubspot_subscription_types()
   └─ Returns [{id:"1", name:"AAIF Newsletter"}, {id:"2", name:"LF Events Updates"}, ...]
   └─ Claude presents these to the user: "Which subscription type?"

4. User: "AAIF Newsletter"

5. Claude calls create_hubspot_form(
     name="26Q2 - AAIF - CloudNativeCon Europe 2026",
     brand="AAIF",
     fields=[{name:"First Name", type:"text", required:True}, ...],
     subscription_type_id="1",
     ...
     ctx=context
   )
   └─ hubspot_forms.py:
      a. brand check → brand is "AAIF" ✓
      b. subscription check → "1" ✓
      c. ctx.elicit() → user sees native confirmation dialog
      d. User approves
      e. POST /marketing/v3/forms/
   └─ Returns {status:"created", form_id:"abc123", name:"26Q2 - AAIF - ...", hubspot_url:...}

6. Claude: "✅ Form created — 26Q2 - AAIF - CloudNativeCon Europe 2026
   HubSpot URL: https://app.hubspot.com/forms/.../editor/abc123"
```

### Flow C: Delete Forms via Web UI

```
1. User clicks "🗑️ Delete Forms" tab

2. User types "25Q3" in search box → clicks Search
   └─ GET /api/hubspot/forms/search?q=25Q3
   └─ Returns matching forms → displayed as checklist

3. User checks the forms to delete

4. User checks "I understand this is permanent"
   └─ app.js: enables [Delete Selected] button only when checkbox is checked

5. User clicks [Delete Selected]
   └─ app.js opens confirmation modal: "PERMANENTLY DELETE N form(s)? This CANNOT be undone."

6. User clicks Confirm in modal

7. POST /api/hubspot/forms/delete  {form_ids:[...], confirmed_names:[...]}
   └─ hubspot.py: DELETE /marketing/v3/forms/{id} for each form
   └─ Returns [{name:"...", status:"deleted"}, ...]

8. app.js shows:
   ✅ Deleted: 25Q3 - AAIF - DevSummit 2025
   ✅ Deleted: 25Q3 - LF Events - CloudNativeCon NA 2025
```

### Flow D: Asana Pre-fill (Optional)

```
1. User pastes: https://app.asana.com/1/.../task/1214761275486487

2. POST /api/asana/task  {"url": "..."}
   └─ asana_client.extract_task_gid("https://...") → "1214761275486487"
   └─ GET https://app.asana.com/api/1.0/tasks/1214761275486487
      ?opt_fields=gid,name,notes,assignee.name,completed,permalink_url
   └─ Parse notes with heuristics:
      - _classify_request_type(notes) → ["FORM_CREATION"]
      - _extract_hint(notes, r"from[:\s]+email") → "events@aaif.io"
      - _extract_hint(notes, r"brand[:\s]+...") → "AAIF"
   └─ Returns {gid, name, notes, prefill: {hint_only: true, ...}}

3. app.js receives response:
   - Sets form-name input = form_name_hint (if found)
   - Sets ar-from-email = from_address_hint (if found)
   - Sets workflow-search = workflow_hint (if found)
   - Sets brand = brand_hint (if found)
   - Shows warning banner: "⚠️ These are suggestions — review and confirm all fields"

4. User reviews all pre-filled values, edits as needed, then submits normally
   The hints NEVER auto-submit — user must actively confirm each value
```

---

## 12. Brand & Confirmation Rules

These are **enforced in code** — not just documentation:

### Rule 1: Brand is always required

```python
# In create_hubspot_form MCP tool:
if not brand:
    return {
        "action_required": "confirm_brand",
        "message": "Which brand or business unit should this form be associated with? "
                   "(e.g. LF Events, AAIF, OpenSSF, CNCF). "
                   "Please confirm, then call create_hubspot_form again."
    }

# In POST /api/hubspot/forms/create REST route:
if not req.brand:
    return ApiResponse(success=False, error="Brand/business unit is required.")
```

### Rule 2: Subscription type is always required

```python
if not subscription_type_id:
    return {
        "action_required": "confirm_subscription_type",
        "message": "Use list_hubspot_subscription_types to show the user the available options, "
                   "then call create_hubspot_form again with subscription_type_id confirmed."
    }
```

### Rule 3: Deletion always confirms

```python
# In delete_hubspot_forms MCP tool — ctx.elicit() is ALWAYS called:
result = await ctx.elicit(
    message=f"Permanently delete {len(form_ids)} form(s)?\n{display}\nThis CANNOT be undone.",
    schema={"type":"object","properties":{"proceed":{"type":"boolean"}},"required":["proceed"]}
)
if result.action != "accept" or not result.data.get("proceed"):
    return [{"status":"cancelled","message":"Deletion cancelled by user."}]
```

### Rule 4: Workflow ambiguity asks the user

```python
# In enroll_form_in_workflow — if multiple matches:
result = await ctx.elicit(
    message=f"Multiple workflows match '{query}':\n{options_text}\nWhich one?",
    schema={"type":"object","properties":{"choice":{"type":"integer"}},"required":["choice"]}
)
```

### Rule 5: Asana hints are never auto-submitted

```python
# In asana.py get_asana_task and api_routes/asana.py:
prefill = {
    "brand_hint": ...,
    "subscription_hint": ...,
    "hint_only": True,         # ← always set
    "note": "brand and subscription MUST be confirmed by user"
}
```

---

## 13. HubSpot APIs Used

| Operation | Method | Endpoint |
|---|---|---|
| Get portal info | `GET` | `/account-info/v3/details` |
| List forms | `GET` | `/marketing/v3/forms/` |
| Get form | `GET` | `/marketing/v3/forms/{formId}` |
| Create form | `POST` | `/marketing/v3/forms/` |
| Update form | `PATCH` | `/marketing/v3/forms/{formId}` |
| Delete form | `DELETE` | `/marketing/v3/forms/{formId}` |
| Subscription types | `GET` | `/communication-preferences/v3/definitions` |
| Contacts lists | `GET` | `/contacts/v1/lists/` |
| Create email | `POST` | `/marketing/v3/emails/` |
| List workflows | `GET` | `/automation/v4/flows/` |
| Update workflow triggers | `PATCH` | `/automation/v4/flows/{flowId}/enrollmentCriteria` |

**Asana APIs:**

| Operation | Method | Endpoint |
|---|---|---|
| Get task | `GET` | `https://app.asana.com/api/1.0/tasks/{task_id}` |
| Post comment | `POST` | `https://app.asana.com/api/1.0/tasks/{task_id}/stories` |

---

## 14. Claude Code Integration

### MCP Endpoint

```
http://localhost:8000/mcp/mcp
```

Why `/mcp/mcp`? The `streamable_http_app()` from the MCP SDK creates an internal sub-app with a `/mcp` route. When mounted at `/mcp` in FastAPI, the full path becomes `/mcp/mcp`.

### Register with Claude Code

```bash
claude mcp add --transport http hubspot-form-manager http://localhost:8000/mcp/mcp --scope project
```

### Settings file entry

**Project-scoped** (`.claude/settings.json` in your project):
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

**With credentials passed from Claude Code's environment** (if `HUBSPOT_API_KEY` is already set):
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

### Verify tools are registered

```bash
npx @modelcontextprotocol/inspector \
  --cli http://localhost:8000/mcp/mcp \
  --transport http \
  --method tools/list
```

Expected output: 12 tools listed.

### How Claude should use the tools — recommended sequence

**For form creation:**
```
1. get_hubspot_portal_id()                   ← get portal ID for deep links
2. list_hubspot_subscription_types()         ← show user real names to choose from
3. [user confirms brand and subscription]
4. [optional] list_hubspot_forms(query="...") ← find reference form
5. [optional] get_hubspot_form(form_id="...")  ← read thank-you message
6. create_hubspot_form(name, brand, fields, subscription_type_id, ...)
7. find_hubspot_form_submission_list(form_name) ← get signup list URL
8. [optional] post_asana_comment(task_id, text) ← post delivery summary
```

**For deletion:**
```
1. list_hubspot_forms(query="...")   ← find forms, get IDs
2. delete_hubspot_forms(form_ids, confirmed_names)  ← elicit() fires here
```

---

## 15. Tests

**Run tests:**
```bash
pytest tests/ -v
```

**Result: 21 passed ✅**

### `tests/test_naming.py` — 12 tests

| Test class | Tests |
|---|---|
| `TestParseNameParts` | Standard LF Events name, AAIF name, non-standard name fallback, extra whitespace handling |
| `TestDeriveFormName` | Basic derivation, different team, explicit year override, year inferred from quarter, invalid quarter raises ValueError, team spacing preserved |
| `TestSuggestFormName` | Basic name from scratch, invalid quarter format |

### `tests/test_form_builder.py` — 9 tests

| Test | What it checks |
|---|---|
| `test_empty_fields_returns_empty` | Empty input → empty output |
| `test_single_email_field` | email type → `fieldType: "email"`, `name: "email"` |
| `test_builtin_first_name_mapping` | "First Name" → property name `firstname` |
| `test_builtin_last_name_mapping` | "Last Name" → `lastname`, required=False |
| `test_country_field_maps_to_dropdown` | country type → `fieldType: "dropdown"` |
| `test_multiple_fields_in_single_group` | 4 fields → 1 group with 4 fields |
| `test_select_field_with_options` | Options mapped with slugified values |
| `test_custom_field_is_slugified` | "Special Project Name" → `special_project_name` |
| `test_unknown_type_defaults_to_text` | Unknown type → `single_line_text` |

---

## 16. Dependency Reference

```toml
# Core runtime
mcp[cli]>=1.9.0           # FastMCP, StreamableHTTP transport, elicit()
fastapi>=0.115.0          # Web framework, REST API routing
uvicorn[standard]>=0.30.0 # ASGI server
httpx>=0.27.0             # Async HTTP client for HubSpot + Asana APIs
pydantic>=2.7.0           # Data validation, request/response models
python-dotenv>=1.0.0      # .env file loading
jinja2>=3.1.0             # Templating (available, not currently used)
aiofiles>=23.0.0          # Async file serving

# Dev / test
pytest>=8.0.0             # Test runner
pytest-asyncio>=0.23.0    # Async test support
ruff>=0.4.0               # Linter + formatter
```

**Note on mcp version:** The project targets `mcp[cli]>=1.9.0` in `pyproject.toml`. The installed version at time of development was **1.6.0**. The code is compatible with 1.6.0 with these adaptations:
- `@mcp.tool()` decorator uses only `name` and `description` parameters (no `annotations`)
- `mcp.streamable_http_app()` is used (not `http_app()`)
- `mcp.session_manager.run()` is called in the FastAPI lifespan context manager to initialize the StreamableHTTP session manager's task group

---

*Generated for HubSpot Form Manager MCP Server v1.0.0*
