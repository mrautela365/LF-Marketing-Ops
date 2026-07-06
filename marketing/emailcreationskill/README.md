# Email Staging Service

FastAPI backend + static frontend that drafts and stages Linux Foundation marketing
emails in HubSpot, and builds the audience (segment) lists that back them. It looks up
brand send history, scrapes event pages for content, generates copy, clones/stages the
email in HubSpot, and assembles master audience lists (inclusion segments + suppression).

## Architecture

```
email_service/
├── backend/                 # FastAPI app + integration modules (Python 3.12)
│   ├── main.py              # FastAPI app + HTTP endpoints (~21 routes)
│   ├── agent.py             # Claude agent loop / tool orchestration
│   ├── models.py            # Pydantic request/response schemas
│   ├── config.py            # Loads env vars from .env (single source of config)
│   ├── session_store.py     # In-memory session state (per-process)
│   │
│   ├── hubspot_tools.py     # HubSpot API — marketing emails, send/suppression lists
│   ├── audience_tools.py    # Audience builder (plan → build) — Snowflake + HubSpot lists
│   ├── content_tools.py     # Event-page scraping + content extraction
│   ├── email_templates.py   # Email template rendering
│   ├── asana_tools.py       # Asana integration (briefs/tasks)
│   ├── stage_detector.py    # Detects the email's staging stage
│   ├── event_brands.py      # Brand / event-name mapping helpers
│   └── gen_email.js         # Node helper for email generation
│
├── frontend/                # Static UI (vanilla JS) — index.html, app.js, style.css
├── Dockerfile               # python:3.12-slim image
├── docker-compose.yml       # Runs the service on :8000, env_file=.env
├── requirements.txt
└── .env                     # Secrets (NOT committed — see .env.example)
```

## AI modes

`main.py` selects a mode at startup based on which credentials are present:

1. **LiteLLM proxy** — when `LITELLM_BASE_URL` + `LITELLM_API_KEY` are set (preferred).
2. **Anthropic API** — when `ANTHROPIC_API_KEY` is set.
3. **Claude Code** — CLI subprocess fallback when neither is configured.

## Configuration

Copy `.env.example` to `.env` and fill in values. Variables read by `config.py`:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | Direct Anthropic API mode + model id |
| `LITELLM_BASE_URL`, `LITELLM_API_KEY` | LiteLLM proxy mode (takes priority) |
| `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_PORTAL_ID` | HubSpot private-app token (Marketing Email + CRM Lists scopes) |
| `INTERNAL_API_TOKEN` | Shared secret for `/api/stage-from-brief` |
| `ASANA_ACCESS_TOKEN` | Asana integration (optional) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Google Docs content sources (optional) |
| `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PRIVATE_KEY`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_ROLE` | Snowflake (audience list building) |
| `ASSET_TAG` | Optional (default empty = no-op). When set (e.g. `psh-test`), appended as `" [psh-test]"` to the name of every new HubSpot asset this app creates — cloned emails and audience/suppression lists — so test runs can be found and bulk-deleted later. |

> **Never commit `.env`.** It holds live tokens and is covered by `.gitignore`.

## Running

### Docker (recommended)

```bash
docker compose up --build
```

Serves on http://localhost:8000 (UI at `/`, API under `/api/*`).

### Local (dev)

```bash
pip install -r requirements.txt
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## API surface

Endpoints are defined in `backend/main.py`. Key ones:

- `GET  /api/status` — current AI mode + HubSpot config flag
- `POST /api/plan` — build an email plan from an event URL
- `POST /api/generate-content`, `POST /api/content` — generate / fetch email content
- `POST /api/clone`, `POST /api/set-send-list` — clone & stage the HubSpot email
- `POST /api/audience-plan`, `POST /api/build-audience`, `POST /api/audience/run` — audience list builder
- `GET  /api/audience-stream/{job_id}` — SSE stream of a running audience build
- `POST /api/chat` — free-chat with the agent
- `POST /api/plan-from-asana`, `POST /api/stage-from-brief` — skill/Asana integrations

## Audience suppression model

When the audience builder assembles a **master list**, it does **not** inject every
suppression list into each inclusion group. Instead it creates one **Combined
Suppression** list (the OR of all suppression lists) and references that single list as
a `NOT_IN_LIST` exclusion in each inclusion group. This is because HubSpot's CRM v3
Lists API cannot write the native UI "Exclude contacts" segment block — it only
round-trips the inclusion `filterBranch`. See `BUILDING_PROMPT` STEP 5B/6 in
`backend/audience_tools.py`.
