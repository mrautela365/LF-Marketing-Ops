# Onboarding: Email Staging Service

Hand this doc to Claude along with the repo URL and branch:

> Repo: https://github.com/mrautela365/LF-Marketing-Ops/tree/vinay/skills
> Path within repo: `marketing/emailcreationskill`

Claude should be able to clone, configure, and run the app locally from the steps below.

## What this is

FastAPI backend + static vanilla-JS frontend that drafts and stages Linux Foundation
marketing emails in HubSpot, and builds the audience (segment) lists that back them.

## 1. Clone

```bash
git clone --branch vinay/skills https://github.com/mrautela365/LF-Marketing-Ops.git
cd LF-Marketing-Ops/marketing/emailcreationskill
```

## 2. Python environment (Python 3.12)

```bash
python -m venv .venv
```

Activate it:
- Windows PowerShell: `.venv\Scripts\Activate.ps1`
- macOS/Linux: `source .venv/bin/activate`

Install dependencies:

```bash
pip install -r requirements.txt
```

## 3. Configure secrets — create `.env`

Create a file named `.env` in this directory (`marketing/emailcreationskill/.env`) —
**never commit it**, it's already covered by `.gitignore`. Use this template and fill
in the placeholders:

```env
# ── AI mode (pick ONE — checked in this priority order) ─────────────────────
# 1. LiteLLM proxy (preferred if set)
LITELLM_BASE_URL=
LITELLM_API_KEY=

# 2. Direct Anthropic API (used if LiteLLM vars above are empty)
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-6

# 3. If both above are empty, the app falls back to the Claude Code CLI
#    subprocess — no extra vars needed for that mode.

# ── HubSpot (required — Marketing Email + CRM Lists scopes) ────────────────
HUBSPOT_ACCESS_TOKEN=
HUBSPOT_PORTAL_ID=8112310

# ── Internal API auth ───────────────────────────────────────────────────────
# Shared secret for POST /api/stage-from-brief. Leave blank for local dev
# (the endpoint will warn but still accept calls).
INTERNAL_API_TOKEN=

# ── Asana integration (optional) ────────────────────────────────────────────
ASANA_ACCESS_TOKEN=

# ── Google Docs content sources (optional) ──────────────────────────────────
GOOGLE_SERVICE_ACCOUNT_FILE=

# ── Snowflake (required for audience list building) ─────────────────────────
SNOWFLAKE_ACCOUNT=
SNOWFLAKE_USER=
# PEM-formatted private key — paste as a single line with \n for line breaks
SNOWFLAKE_PRIVATE_KEY=
SNOWFLAKE_DATABASE=ANALYTICS
SNOWFLAKE_SCHEMA=Silver_Segment
SNOWFLAKE_WAREHOUSE=
SNOWFLAKE_ROLE=

# ── Dev/test convenience (optional) ─────────────────────────────────────────
# When set (e.g. "psh-test"), appended as " [psh-test]" to the name of every
# HubSpot asset this app creates (cloned emails, audience/suppression lists),
# so test runs are easy to find and bulk-delete later. Leave blank in prod.
ASSET_TAG=
```

| Variable | Purpose | Required? |
|---|---|---|
| `LITELLM_BASE_URL`, `LITELLM_API_KEY` | LiteLLM proxy mode (takes priority over direct Anthropic) | One of LiteLLM or Anthropic |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | Direct Anthropic API mode + model id | One of LiteLLM or Anthropic |
| `HUBSPOT_ACCESS_TOKEN` | HubSpot private-app token (Marketing Email + CRM Lists scopes) | Yes |
| `HUBSPOT_PORTAL_ID` | HubSpot portal ID | Yes (default provided) |
| `INTERNAL_API_TOKEN` | Shared secret for `/api/stage-from-brief` | No (dev-only fallback) |
| `ASANA_ACCESS_TOKEN` | Asana integration | No |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Google Docs content sources | No |
| `SNOWFLAKE_*` | Audience list building (Snowflake query access) | Yes, for audience features |
| `ASSET_TAG` | Tags test-created HubSpot assets for easy bulk cleanup | No |

Where to get each value:
- **HubSpot**: a private app token from the LF HubSpot portal (Settings → Integrations →
  Private Apps), scoped to Marketing Email + CRM Lists.
- **Anthropic / LiteLLM**: ask whoever manages the team's AI provider credentials.
- **Snowflake**: ask the data team for a service-account key with read access to the
  `ANALYTICS.Silver_Segment` schema (or whatever schema your org uses).
- **Asana / Google service account**: optional — only needed if you use those integrations.

## 4. Run it

**Local (dev, auto-reload):**

```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Or via Docker** (equivalent, no local Python install needed):

```bash
docker compose up --build
```

Either way, open **http://localhost:8000** — UI at `/`, API under `/api/*`.

## 5. Verify it's working

- `GET http://localhost:8000/api/status` should return the active AI mode and whether
  HubSpot config is present.
- Load `http://localhost:8000/` in a browser — you should see the campaign builder UI.

## Reference

Full architecture notes, API surface, and the audience-suppression model are documented
in [README.md](README.md) in this same directory.
