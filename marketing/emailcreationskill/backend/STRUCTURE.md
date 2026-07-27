# Backend Code Structure

## Overview

The backend has been reorganized for better maintainability and separation of concerns.

```
backend/
├── core/                    # Agent orchestration & session management
│   ├── __init__.py         # Public API exports
│   ├── agent.py            # Main agent orchestration (plan, clone, content, chat turns)
│   └── session.py          # Session storage and management
│
├── services/               # Business logic & feature services
│   ├── __init__.py         # (Reserved for future service modules)
│   └── [Future services]   # email_service, content_service, audience_service, etc.
│
├── integrations/           # External API integrations
│   ├── __init__.py         # Public API exports
│   ├── hubspot.py          # HubSpot CRM API (email, contacts, lists, campaigns)
│   ├── asana.py            # Asana task management
│   └── utm.py              # UTM parameter building
│
├── templates/              # Email template definitions
│   ├── __init__.py         # Public API exports
│   ├── email_templates.py  # Standard email template library
│   └── ai_email_templates.py # AI-generated template definitions (by stage)
│
├── utils/                  # Shared utilities & helpers
│   ├── __init__.py         # Public API exports
│   ├── stage_detector.py   # Campaign stage detection
│   ├── event_brands.py     # Event brand lookup & management
│   └── content_tools.py    # Content fetching & parsing
│
├── llm/                    # LLM gateway & routing
│   ├── __init__.py         # Public API exports
│   └── gateway.py          # Unified LLM backend routing (Anthropic/LiteLLM/CLI)
│
├── main.py                 # FastAPI app factory & routes
├── models.py               # Pydantic request/response models
├── config.py               # Configuration & environment variables
└── STRUCTURE.md            # This file
```

---

## Module Descriptions

### `core/` — Agent Orchestration

**Purpose:** Central AI orchestration for the email staging workflow

**Key Components:**
- `agent.py` — Main agent logic
  - `plan_turn()` — Phase 1: Build email staging plan
  - `clone_turn()` — Phase 2: Clone email & apply settings
  - `content_turn()` — Phase 3: Generate or apply email content
  - `chat_turn()` — Free-form chat with Claude
  - `SYSTEM_PROMPT` — Shared system instructions
  - `TOOLS` — Agent tool definitions

- `session.py` — Session management
  - `session_store` — In-memory session persistence

---

### `integrations/` — External APIs

**Purpose:** Wrapper layer for third-party integrations

**Modules:**
- `hubspot.py` — HubSpot API client
  - Email operations: `clone_email()`, `update_email_settings()`, `update_email_content()`
  - List management: `search_lists()`, `set_email_send_list()`
  - Brand history: `lookup_brand_history()`, `search_emails_for_event()`
  - A/B testing: `create_ab_variation()`
  - Validation: `validate_staged_email()`

- `asana.py` — Asana integration
  - Task creation and updates

- `utm.py` — UTM parameter building
  - Build campaign UTM parameters
  - Apply to URLs

---

### `templates/` — Email Template Definitions

**Purpose:** Store and retrieve email templates

**Modules:**
- `email_templates.py` — Pre-defined email templates
  - Template library indexed by name/type
  - Reusable component definitions
  - Design patterns for different campaign types

- `ai_email_templates.py` — AI-generated templates by stage
  - Stage-specific templates (CFP Launch, Schedule Announcement, etc.)
  - Content generation prompts
  - Validation rules per stage
  - Placeholder filling

---

### `utils/` — Shared Utilities

**Purpose:** Reusable helper functions

**Modules:**
- `stage_detector.py` — Campaign stage detection
  - Detect marketing stage from dates
  - `detect_stage()` — Maps event date to stage
  - `MARKETING_JOURNEY` — Stage metadata & strategy

- `event_brands.py` — Event brand lookup
  - `lookup_event_brand()` — Get brand from event URL
  - `get_brand_events()` — List events for a brand
  - Location expansion & matching

- `content_tools.py` — Content fetching & parsing
  - `fetch_url()` — Extract content from URLs
  - `fetch_content()` — Convert content to HTML
  - `analyze_content()` — Parse email structure
  - HTML cleaning & validation

---

### `llm/` — LLM Gateway

**Purpose:** Unified LLM backend routing

**Modules:**
- `gateway.py` — Route all LLM calls through single interface
  - Supports Anthropic API, LiteLLM, or Claude CLI
  - Deterministic mode (temperature=0)
  - Consistent output across all backends
  - Tool use handling

---

### `main.py` — FastAPI Application

**Purpose:** HTTP API endpoints

**Structure:**
- App initialization
- CORS middleware
- Static file serving
- Route handlers:
  - `/api/plan` — Plan turn
  - `/api/clone` — Clone & settings turn
  - `/api/generate-content` — Generate email content
  - `/api/content` — A/B content turn
  - `/api/chat` — Free-form chat
  - `/api/set-send-list` — Configure send list
  - `/api/update-sections` — Update email sections
  - (And more...)

---

### `models.py` — Pydantic Models

**Purpose:** Request/response validation

**Models:**
- `PlanRequest`, `CloneRequest`, `ContentRequest`, `ChatRequest`
- `GenerateContentRequest`, `StagingBriefRequest`
- `AsanaPlanRequest`, `AudiencePlanRequest`
- (And more...)

---

### `config.py` — Configuration

**Purpose:** Environment & settings management

**Variables:**
- `ANTHROPIC_API_KEY` — Claude API key
- `HUBSPOT_PORTAL_ID` — HubSpot portal
- `LITELLM_BASE_URL`, `LITELLM_API_KEY` — LiteLLM config
- `ASANA_ACCESS_TOKEN` — Asana token
- `CLAUDE_MODEL` — Model selection

---

## Import Changes (Backward Compatible)

### Old Style (Still Works via Wrappers)
```python
import agent
from event_brands import lookup_event_brand
from hubspot_tools import clone_email
from stage_detector import detect_stage
```

### New Style (Recommended)
```python
from core import plan_turn, clone_turn, content_turn
from utils import detect_stage, lookup_event_brand
from integrations import clone_email, update_email_content
```

**Note:** Old imports still work! They're re-exported via wrapper files in the root `backend/` directory.

---

## Services (Reserved for Future)

The `services/` directory is reserved for business-logic services like:
- `EmailService` — High-level email operations
- `ContentService` — Content generation & analysis
- `AudienceService` — Audience management
- `EventService` — Event data & metadata

These will be added as the codebase scales.

---

## Adding New Modules

1. **Utility function?** → Add to `utils/`
2. **External API call?** → Add to `integrations/`
3. **Email template?** → Add to `templates/`
4. **Core orchestration logic?** → Add to `core/`
5. **Business logic service?** → Add to `services/`
6. **HTTP route?** → Add handler to `main.py`

---

## Testing

When running tests:
```bash
# All old imports still work
python -m pytest tests/

# No refactoring of test imports needed
```

---

## Migration Timeline

- **Phase 1 (Current):** Reorganized, wrappers in place, backward compatible
- **Phase 2:** Update imports in main.py to use new structure
- **Phase 3:** Remove wrapper files (optional, only after Phase 2)

---

## No Breaking Changes

✅ All existing imports work
✅ All existing code paths unchanged
✅ No API changes
✅ No logic changes
✅ Can gradually migrate imports over time

