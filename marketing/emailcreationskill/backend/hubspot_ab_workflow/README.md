# HubSpot Workflow A/B Testing Module

**Status:** Isolated Feature Module (Easy to Remove)

This module implements A/B testing using native HubSpot workflows. It's designed as a completely separate, pluggable feature that can be easily removed if needed.

## Architecture

### Isolation Design

The module is intentionally isolated:
- ✅ **No changes to existing code** - doesn't modify campaign builder or other modules
- ✅ **Separate database** - uses in-memory storage (can be swapped with real DB)
- ✅ **Separate API routes** - all endpoints under `/api/ab-workflow`
- ✅ **Separate UI** - new tab in frontend, no modifications to existing UI
- ✅ **Easy removal** - can be deleted without breaking anything

### Module Structure

```
backend/hubspot_ab_workflow/
├── __init__.py              # Package marker
├── models.py                # Data classes
├── hubspot_integration.py   # HubSpot API calls
├── workflow_manager.py      # Business logic
├── routes.py                # FastAPI endpoints
└── README.md               # This file

frontend/ab-workflow/
├── ab-workflow.js           # UI logic
├── ab-workflow.css          # Styling
└── README.md               # Frontend docs
```

## Integration Steps

### 1. Register Routes in main.py

Add these lines to `backend/main.py`:

```python
from hubspot_ab_workflow.routes import router as ab_workflow_router

app.include_router(ab_workflow_router)
```

### 2. Add UI Tab in index.html

Add a new top-level tab:

```html
<div class="top-tabs">
  <div class="top-tab" onclick="switchTopTab('campaign')">Campaign Builder</div>
  <div class="top-tab" onclick="switchTopTab('ab-workflow')">A/B Test Workflow</div>
</div>
```

### 3. Include UI Files

In `frontend/index.html`:

```html
<link rel="stylesheet" href="/static/ab-workflow/ab-workflow.css?v=1" />
<script src="/static/ab-workflow/ab-workflow.js?v=1"></script>
```

## API Endpoints

All endpoints are prefixed with `/api/ab-workflow`

### Core Workflow

```
POST   /create                    Create new A/B test (DRAFT state)
POST   /{test_id}/launch          Launch test (RUNNING state)
GET    /{test_id}/status          Get test status with live metrics
POST   /{test_id}/complete        Complete test (COMPLETED state)
GET    /{test_id}                 Get test details
POST   /{test_id}/archive         Archive old test
GET    /                          List all A/B tests
```

### UI Helper Endpoints

```
GET    /ui/emails?name_contains=  List available emails for variant selection
GET    /ui/lists?name_contains=   List available lists for audience selection
GET    /enabled                   Check if feature is enabled
```

## Feature Flags

To disable the feature without removing code:

### Option 1: Environment Variable

```python
# In routes.py
import os

FEATURE_ENABLED = os.getenv("AB_WORKFLOW_ENABLED", "true").lower() == "true"

@router.get("/enabled")
async def check_enabled():
    return {"enabled": FEATURE_ENABLED}
```

### Option 2: Configuration File

```python
# config.py
AB_WORKFLOW_ENABLED = True

# routes.py
from config import AB_WORKFLOW_ENABLED

if not AB_WORKFLOW_ENABLED:
    raise HTTPException(status_code=404)
```

## How to Remove (If Needed)

Completely removing this feature takes 3 steps:

1. **Remove routes registration** from `main.py`:
   ```python
   # DELETE: from hubspot_ab_workflow.routes import router as ab_workflow_router
   # DELETE: app.include_router(ab_workflow_router)
   ```

2. **Remove UI files**:
   ```bash
   rm -rf frontend/ab-workflow/
   rm -rf backend/hubspot_ab_workflow/
   ```

3. **Remove HTML tab** from `frontend/index.html`:
   ```html
   <!-- DELETE the A/B Test Workflow tab -->
   ```

That's it - everything else is unaffected!

## Testing

### Manual Testing

1. Start server: `python -m uvicorn main:app --reload`
2. Visit: `http://localhost:8001`
3. Click "A/B Test Workflow" tab
4. Create test with 2 different emails
5. Launch test
6. Monitor results
7. Complete test after duration

### Testing Locally (No HubSpot)

The module includes mock HubSpot API responses in `hubspot_integration.py`. To test without a real HubSpot account:

```python
# hubspot_integration.py returns mock data:
- Mock email list
- Mock list list
- Mock email stats (45% open rate vs 52%)
```

## Database (Future)

Currently uses in-memory storage (`_ab_tests` dict in `workflow_manager.py`).

To switch to persistent database:

1. Create `models.py` with SQLAlchemy tables
2. Update `workflow_manager.py` to use database instead of dict
3. Everything else stays the same - API and UI don't change

## Limitations (Current Version)

- ✋ **Mock HubSpot API** - doesn't actually create workflows in HubSpot yet
- ✋ **In-memory storage** - tests lost on server restart
- ✋ **Manual completion** - need to call `/complete` endpoint manually (in production: automatic after 24h)

## Future Enhancements

- [ ] Real HubSpot Workflow API integration
- [ ] Persistent database (PostgreSQL/SQLite)
- [ ] Automatic test completion via cron job
- [ ] Real statistical significance calculation (Chi-square test)
- [ ] Webhook support for HubSpot events
- [ ] Advanced analytics dashboard
- [ ] A/B test templates

## Support

For issues with this module:
1. Check logs in `[AB-WF]` prefixed messages
2. Verify HubSpot API token is set
3. Check if feature is enabled: `GET /api/ab-workflow/enabled`
