# HubSpot Workflow A/B Testing - Integration Guide

This guide explains how to integrate the new A/B Testing Workflow feature into your existing system.

## Quick Summary

A completely **isolated, optional feature** has been created for A/B testing using HubSpot workflows. It requires minimal integration work and can be easily removed if needed.

## What Was Built

```
✅ Backend Module      → backend/hubspot_ab_workflow/
✅ Frontend UI        → frontend/ab-workflow/
✅ API Endpoints      → /api/ab-workflow/*
✅ Documentation      → README files in each directory
```

## Integration Steps (5 minutes)

### Step 1: Register Backend Routes

Edit: `backend/main.py`

Add after the existing imports:

```python
# A/B Workflow Feature (Optional - can be removed)
from hubspot_ab_workflow.routes import router as ab_workflow_router
```

Then add this line after all other `app.include_router()` calls:

```python
# Optional A/B Workflow feature
app.include_router(ab_workflow_router)
```

**Full example:**
```python
# At the top with other imports
from hubspot_ab_workflow.routes import router as ab_workflow_router

# In the app setup section
app.include_router(ab_workflow_router)  # A/B Workflow feature
```

### Step 2: Add Frontend Assets

Copy these files to the static directory:

```
frontend/ab-workflow/ab-workflow.js  → static/ab-workflow/ab-workflow.js
frontend/ab-workflow/ab-workflow.css → static/ab-workflow/ab-workflow.css
```

### Step 3: Update HTML (index.html)

**Add CSS Link** in `<head>` section:

```html
<link rel="stylesheet" href="/static/ab-workflow/ab-workflow.css?v=1" />
```

**Add JavaScript** before closing `</body>`:

```html
<script src="/static/ab-workflow/ab-workflow.js?v=1"></script>
```

**Add Tab** in the top-level tabs container (find where "Campaign Builder" and "Audience Builder" tabs are):

```html
<div class="top-tabs">
  <div class="top-tab active" id="top-tab-campaign" onclick="switchTopTab('campaign')">Campaign Builder</div>
  <div class="top-tab" id="top-tab-audience-builder" onclick="switchTopTab('audience-builder')">Audience Builder</div>
  <!-- ADD THIS NEW TAB: -->
  <div class="top-tab" id="top-tab-ab-workflow" onclick="switchTopTab('ab-workflow')">A/B Test Workflow</div>
</div>
```

**Add Main Flow Container** (add after the existing `flow-event` and `flow-audience-builder` divs):

```html
<!-- ════════════════════════════════════════════════════════════════════
     HubSpot Workflow A/B Testing Feature (Optional - can be removed)
     ════════════════════════════════════════════════════════════════════ -->
<div id="flow-ab-workflow" class="hidden">

  <!-- Step Indicators -->
  <div class="ab-step-indicators">
    <div class="ab-step-indicator active" data-step="1">
      <div class="ab-step-indicator-number">1</div>
      <span>Select Variants</span>
    </div>
    <div class="ab-step-indicator" data-step="2">
      <div class="ab-step-indicator-number">2</div>
      <span>Review & Launch</span>
    </div>
    <div class="ab-step-indicator" data-step="3">
      <div class="ab-step-indicator-number">3</div>
      <span>Monitor Test</span>
    </div>
    <div class="ab-step-indicator" data-step="4">
      <div class="ab-step-indicator-number">4</div>
      <span>Results</span>
    </div>
  </div>

  <!-- Step 1: Select Variants -->
  <div id="ab-step-select">
    <div class="card">
      <div class="card-title">Create A/B Test</div>
      <div class="card-desc">Select two email variants to test and launch the A/B test workflow</div>
      
      <div class="ab-variant-grid">
        <div class="ab-variant-column">
          <h3>📧 Variant A</h3>
          <div class="ab-form-group">
            <label>Email</label>
            <select id="ab-variant-a-select">
              <option value="">Loading emails...</option>
            </select>
          </div>
        </div>

        <div class="ab-variant-column">
          <h3>📧 Variant B</h3>
          <div class="ab-form-group">
            <label>Email</label>
            <select id="ab-variant-b-select">
              <option value="">Loading emails...</option>
            </select>
          </div>
        </div>
      </div>

      <div class="ab-form-group">
        <label>📋 Test Audience</label>
        <select id="ab-audience-select">
          <option value="">Loading lists...</option>
        </select>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
        <div class="ab-form-group">
          <label>⏱️ Test Duration (hours)</label>
          <input id="ab-duration-hours" type="number" value="24" min="1" max="168">
        </div>

        <div class="ab-form-group">
          <label>🏆 Winner Metric</label>
          <select id="ab-winner-metric">
            <option value="open_rate">Open Rate</option>
            <option value="click_rate">Click Rate</option>
            <option value="conversion_rate">Conversion Rate</option>
          </select>
        </div>
      </div>

      <button onclick="createABTest()" class="btn btn-primary" style="width: 100%; margin-top: 20px;">
        Next: Review & Launch →
      </button>
    </div>
  </div>

  <!-- Step 2: Review & Launch -->
  <div id="ab-step-review" class="hidden">
    <div class="card">
      <div class="card-title">Review Test Configuration</div>
      <div id="ab-review-summary" style="background: var(--gray-50); padding: 20px; border-radius: 8px; margin: 20px 0;"></div>
      <div style="display: flex; gap: 12px;">
        <button onclick="showStep('ab-step-select')" class="btn btn-outline">← Back</button>
        <button onclick="launchABTest()" class="btn btn-success" style="flex: 1;">Launch Test →</button>
      </div>
    </div>
  </div>

  <!-- Step 3: Monitor Test -->
  <div id="ab-step-monitor" class="hidden">
    <div class="card">
      <div class="card-title">A/B Test in Progress</div>
      <div id="ab-monitoring-dashboard"></div>
    </div>
  </div>

  <!-- Step 4: Results -->
  <div id="ab-step-results" class="hidden">
    <div class="card">
      <div class="card-title">Test Results</div>
      <div id="ab-test-results"></div>
    </div>
  </div>

  <!-- Test History -->
  <div style="margin-top: 40px;">
    <div class="card">
      <div class="card-title">A/B Test History</div>
      <button onclick="loadABTestHistory()" class="btn btn-outline">Load History</button>
      <div id="ab-test-history" style="margin-top: 20px;"></div>
    </div>
  </div>

</div>
```

### Step 4: Update Tab Switching Logic

Find your existing `switchTopTab()` function and update it to include the A/B workflow:

**Before:**
```javascript
function switchTopTab(tabName) {
  document.getElementById('flow-event').classList.add('hidden');
  document.getElementById('flow-audience-builder').classList.add('hidden');
  
  if (tabName === 'campaign') {
    document.getElementById('flow-event').classList.remove('hidden');
  } else if (tabName === 'audience-builder') {
    document.getElementById('flow-audience-builder').classList.remove('hidden');
  }
}
```

**After:**
```javascript
function switchTopTab(tabName) {
  document.getElementById('flow-event').classList.add('hidden');
  document.getElementById('flow-audience-builder').classList.add('hidden');
  document.getElementById('flow-ab-workflow').classList.add('hidden');
  
  if (tabName === 'campaign') {
    document.getElementById('flow-event').classList.remove('hidden');
  } else if (tabName === 'audience-builder') {
    document.getElementById('flow-audience-builder').classList.remove('hidden');
  } else if (tabName === 'ab-workflow') {
    document.getElementById('flow-ab-workflow').classList.remove('hidden');
    loadAvailableEmails();
    loadAvailableLists();
  }
}
```

## Testing Integration

1. **Start the server:**
   ```bash
   cd backend
   python -m uvicorn main:app --reload
   ```

2. **Check feature is enabled:**
   ```bash
   curl http://localhost:8001/api/ab-workflow/enabled
   # Should return: {"enabled": true, "feature": "hubspot-workflow-ab-testing"}
   ```

3. **Open UI:**
   - Navigate to http://localhost:8001
   - Click "A/B Test Workflow" tab
   - Should see variant selection form

## What Features Are Available?

### User Actions

✅ **Create A/B Test**
- Select Variant A email
- Select Variant B email
- Select audience list
- Configure test duration (1-168 hours)
- Choose winner metric (Open Rate, Click Rate, Conversion)

✅ **Launch Test**
- Sends Variant A to 50% of audience
- Sends Variant B to 50% of audience
- Holds back remaining 50% for winner send

✅ **Monitor Test**
- Live statistics update every 5 seconds
- Track opens, clicks for both variants
- See time remaining
- View which variant is currently winning

✅ **Complete Test**
- After duration expires, test auto-completes
- System determines statistical winner
- Display confidence level

✅ **Send Winner**
- Send winning variant to remaining audience
- Complete the campaign

✅ **View History**
- See all past A/B tests
- Filter by status (draft, running, completed)
- Compare different tests

## Disabling the Feature (If Needed)

To disable A/B workflow without removing code:

**Option 1: Comment out the route registration**

In `main.py`:
```python
# (Optional) Disable A/B Workflow feature
# app.include_router(ab_workflow_router)
```

**Option 2: Use feature flag**

Add to `config.py`:
```python
AB_WORKFLOW_ENABLED = False  # Set to True to enable
```

In `routes.py`:
```python
from config import AB_WORKFLOW_ENABLED

if not AB_WORKFLOW_ENABLED:
    # Return 404 for all endpoints
    raise HTTPException(status_code=404)
```

## Complete Removal (If Needed)

If you want to completely remove the feature:

1. **Delete backend module:**
   ```bash
   rm -rf backend/hubspot_ab_workflow/
   ```

2. **Delete frontend module:**
   ```bash
   rm -rf frontend/ab-workflow/
   ```

3. **Remove from main.py:**
   - Delete the import line
   - Delete the include_router line

4. **Remove from index.html:**
   - Delete the CSS link
   - Delete the JavaScript link
   - Delete the A/B Workflow tab
   - Delete the flow-ab-workflow div

**That's it!** No other files are affected.

## File Summary

| File | Location | Purpose |
|------|----------|---------|
| `__init__.py` | backend/hubspot_ab_workflow/ | Package marker |
| `models.py` | backend/hubspot_ab_workflow/ | Data classes for A/B tests |
| `hubspot_integration.py` | backend/hubspot_ab_workflow/ | HubSpot API calls |
| `workflow_manager.py` | backend/hubspot_ab_workflow/ | Business logic |
| `routes.py` | backend/hubspot_ab_workflow/ | FastAPI endpoints |
| `ab-workflow.js` | frontend/ab-workflow/ | UI logic |
| `ab-workflow.css` | frontend/ab-workflow/ | Styling |
| `README.md` | backend/hubspot_ab_workflow/ | Backend docs |
| `README.md` | frontend/ab-workflow/ | Frontend docs |
| This file | Root | Integration guide |

## Next Steps

1. ✅ **Integrate** - Follow the 4 steps above
2. ⏳ **Test** - Create a test with mock data
3. 🔌 **Connect HubSpot** - Update `hubspot_integration.py` to call real HubSpot API
4. 💾 **Add Database** - Replace in-memory storage with real DB
5. 🤖 **Automate** - Add cron job to auto-complete tests after duration

## Support

- Backend issues: Check `backend/hubspot_ab_workflow/README.md`
- Frontend issues: Check `frontend/ab-workflow/README.md`
- Integration issues: Reference this file
