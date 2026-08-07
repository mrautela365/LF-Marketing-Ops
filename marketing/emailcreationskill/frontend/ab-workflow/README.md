# A/B Workflow Frontend

Frontend components for HubSpot Workflow A/B Testing feature.

## Files

- `ab-workflow.js` - Main UI logic and API calls
- `ab-workflow.css` - Styling and responsive design
- `README.md` - This file

## Integration

### 1. Add to index.html

Add the links in the `<head>`:

```html
<!-- A/B Workflow Feature -->
<link rel="stylesheet" href="/static/ab-workflow/ab-workflow.css?v=1" />
```

Add the script before closing `</body>`:

```html
<script src="/static/ab-workflow/ab-workflow.js?v=1"></script>
```

### 2. Add UI Tab

In the top-level tabs container:

```html
<div class="top-tabs">
  <div class="top-tab active" id="top-tab-campaign" onclick="switchTopTab('campaign')">Campaign Builder</div>
  <div class="top-tab" id="top-tab-ab-workflow" onclick="switchTopTab('ab-workflow')">A/B Test Workflow</div>
</div>
```

### 3. Add Flow Container

Create a new flow container for the A/B workflow (similar to `flow-event`):

```html
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
      <h2>Select Email Variants</h2>
      
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
      <h2>Review Test Configuration</h2>
      
      <div id="ab-review-summary" style="background: var(--gray-50); padding: 20px; border-radius: 8px; margin: 20px 0;">
        <!-- Populated by JavaScript -->
      </div>

      <div style="display: flex; gap: 12px;">
        <button onclick="showStep('ab-step-select')" class="btn btn-outline">← Back</button>
        <button onclick="launchABTest()" class="btn btn-success" style="flex: 1;">Launch Test →</button>
      </div>
    </div>
  </div>

  <!-- Step 3: Monitor Test -->
  <div id="ab-step-monitor" class="hidden">
    <div class="card">
      <h2>A/B Test in Progress</h2>
      <div id="ab-monitoring-dashboard">
        <!-- Populated by JavaScript with live stats -->
      </div>
    </div>
  </div>

  <!-- Step 4: Results -->
  <div id="ab-step-results" class="hidden">
    <div class="card">
      <h2>Test Results</h2>
      <div id="ab-test-results">
        <!-- Populated by JavaScript -->
      </div>
    </div>
  </div>

  <!-- Test History -->
  <div style="margin-top: 40px;">
    <div class="card">
      <h2>A/B Test History</h2>
      <button onclick="loadABTestHistory()" class="btn btn-outline">Load History</button>
      <div id="ab-test-history" style="margin-top: 20px;">
        <!-- Populated by JavaScript -->
      </div>
    </div>
  </div>

</div>
```

### 4. Add Tab Switcher Logic

Add this to your existing tab switching code:

```javascript
function switchTopTab(tabName) {
  // Hide all flows
  document.getElementById('flow-event').classList.add('hidden');
  document.getElementById('flow-audience-builder').classList.add('hidden');
  document.getElementById('flow-ab-workflow').classList.add('hidden');
  
  // Show selected flow
  if (tabName === 'campaign') {
    document.getElementById('flow-event').classList.remove('hidden');
  } else if (tabName === 'audience-builder') {
    document.getElementById('flow-audience-builder').classList.remove('hidden');
  } else if (tabName === 'ab-workflow') {
    document.getElementById('flow-ab-workflow').classList.remove('hidden');
    // Initialize the A/B workflow UI
    loadAvailableEmails();
    loadAvailableLists();
  }
}
```

## API Calls

The module makes these API calls (defined in `ab-workflow.js`):

```javascript
// Get enabled status
GET /api/ab-workflow/enabled

// Create test
POST /api/ab-workflow/create
{
  variant_a_email_id: "123",
  variant_a_email_name: "Email A",
  variant_b_email_id: "456",
  variant_b_email_name: "Email B",
  audience_list_id: "789",
  audience_list_name: "List Name",
  test_duration_hours: 24,
  winner_metric: "open_rate"
}

// Launch test
POST /api/ab-workflow/{test_id}/launch

// Get status (polls every 5 seconds)
GET /api/ab-workflow/{test_id}/status

// Complete test
POST /api/ab-workflow/{test_id}/complete

// List all tests
GET /api/ab-workflow

// Get available emails
GET /api/ab-workflow/ui/emails?name_contains=

// Get available lists
GET /api/ab-workflow/ui/lists?name_contains=
```

## Styling Classes

Main CSS classes available:

```css
.ab-step-indicators          /* Step progress bar */
.ab-step-indicator           /* Individual step */
.ab-step-indicator.active    /* Active step */
.ab-form-group               /* Form field container */
.ab-variant-grid             /* 2-column variant grid */
.ab-test-monitoring          /* Live monitoring dashboard */
.ab-test-variants            /* Variant comparison */
.ab-results-table            /* Results display */
.ab-history-table            /* Test history */
.btn-success                 /* Green action button */
.btn-outline                 /* Secondary button */
```

## User Workflow

1. **Step 1: Select Variants**
   - Choose Email A from dropdown
   - Choose Email B from dropdown
   - Select audience list
   - Configure duration & winner metric

2. **Step 2: Review & Launch**
   - Review test configuration
   - Click "Launch Test"

3. **Step 3: Monitor Test**
   - See live statistics
   - Track time remaining
   - Watch variant performance

4. **Step 4: Results**
   - See final winner
   - View confidence level
   - Send winner to remaining audience

5. **History**
   - View all past A/B tests
   - Compare different tests

## Responsive Design

The UI is responsive and works on:
- ✅ Desktop (1280px+)
- ✅ Tablet (768px-1280px)
- ✅ Mobile (375px-768px)

Grid layouts adapt automatically on smaller screens.

## Accessibility

- Semantic HTML structure
- Proper form labels
- Keyboard navigation support
- ARIA labels where needed

## Performance

- Lightweight CSS (no dependencies)
- Vanilla JavaScript (no jQuery/React)
- Efficient polling (5-second intervals)
- No unnecessary DOM updates
