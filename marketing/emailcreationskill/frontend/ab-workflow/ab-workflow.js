/**
 * HubSpot Workflow A/B Testing UI
 * Completely isolated - can be easily removed
 */

const API = "/api/ab-workflow";
let currentABTestId = null;
let abTestStatusInterval = null;

/**
 * Initialize A/B Workflow UI
 * Check if feature is enabled
 */
async function initABWorkflow() {
  try {
    const resp = await fetch(`${API}/enabled`);
    const data = await resp.json();

    if (data.enabled) {
      console.log("[AB-WF] Feature enabled");
      setupABWorkflowUI();
    }
  } catch (e) {
    console.warn("[AB-WF] Feature check failed:", e);
  }
}

/**
 * Setup A/B Workflow tab in UI
 */
function setupABWorkflowUI() {
  // This would be called when user clicks on "A/B Test Workflow" tab
  // Implementation depends on where this tab appears in the UI
  console.log("[AB-WF] UI setup complete");
}

/**
 * Step 1: User selects variant emails
 */
async function loadAvailableEmails() {
  try {
    const resp = await fetch(`${API}/ui/emails`);
    const data = await resp.json();

    // Populate dropdowns
    const variantASelect = document.getElementById("ab-variant-a-select");
    const variantBSelect = document.getElementById("ab-variant-b-select");

    if (variantASelect) {
      variantASelect.innerHTML = '<option value="">Select Variant A</option>';
      data.emails.forEach(email => {
        const option = document.createElement("option");
        option.value = email.id;
        option.textContent = email.name;
        option.dataset.subject = email.subject;
        variantASelect.appendChild(option);
      });
    }

    if (variantBSelect) {
      variantBSelect.innerHTML = '<option value="">Select Variant B</option>';
      data.emails.forEach(email => {
        const option = document.createElement("option");
        option.value = email.id;
        option.textContent = email.name;
        option.dataset.subject = email.subject;
        variantBSelect.appendChild(option);
      });
    }
  } catch (e) {
    showError("Failed to load emails:", e);
  }
}

/**
 * Step 2: User selects audience list
 */
async function loadAvailableLists() {
  try {
    const resp = await fetch(`${API}/ui/lists`);
    const data = await resp.json();

    const listSelect = document.getElementById("ab-audience-select");
    if (listSelect) {
      listSelect.innerHTML = '<option value="">Select Audience List</option>';
      data.lists.forEach(list => {
        const option = document.createElement("option");
        option.value = list.id;
        option.textContent = `${list.name} (${list.size} contacts)`;
        listSelect.appendChild(option);
      });
    }
  } catch (e) {
    showError("Failed to load lists:", e);
  }
}

/**
 * Create new A/B test
 */
async function createABTest() {
  const variantASelect = document.getElementById("ab-variant-a-select");
  const variantBSelect = document.getElementById("ab-variant-b-select");
  const listSelect = document.getElementById("ab-audience-select");
  const durationInput = document.getElementById("ab-duration-hours");
  const metricSelect = document.getElementById("ab-winner-metric");

  if (!variantASelect?.value || !variantBSelect?.value || !listSelect?.value) {
    alert("Please select both variants and audience");
    return;
  }

  try {
    const resp = await fetch(`${API}/create`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        variant_a_email_id: variantASelect.value,
        variant_a_email_name: variantASelect.options[variantASelect.selectedIndex].text,
        variant_b_email_id: variantBSelect.value,
        variant_b_email_name: variantBSelect.options[variantBSelect.selectedIndex].text,
        audience_list_id: listSelect.value,
        audience_list_name: listSelect.options[listSelect.selectedIndex].text,
        test_duration_hours: parseInt(durationInput?.value || 24),
        winner_metric: metricSelect?.value || "open_rate",
      }),
    });

    const data = await resp.json();
    if (!resp.ok) {
      showError("Failed to create A/B test:", data.detail);
      return;
    }

    currentABTestId = data.test_id;
    showStep("ab-step-review", data);
  } catch (e) {
    showError("Error creating A/B test:", e);
  }
}

/**
 * Launch A/B test
 */
async function launchABTest() {
  if (!currentABTestId) return;

  try {
    const resp = await fetch(`${API}/${currentABTestId}/launch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    const data = await resp.json();
    if (!resp.ok) {
      showError("Failed to launch A/B test:", data.detail);
      return;
    }

    // Switch to monitoring view
    showStep("ab-step-monitor");
    startMonitoringTest();
  } catch (e) {
    showError("Error launching A/B test:", e);
  }
}

/**
 * Monitor A/B test progress (poll every 5 seconds)
 */
function startMonitoringTest() {
  if (!currentABTestId) return;

  // Clear any existing interval
  if (abTestStatusInterval) {
    clearInterval(abTestStatusInterval);
  }

  // Update immediately
  updateTestStatus();

  // Then poll every 5 seconds
  abTestStatusInterval = setInterval(updateTestStatus, 5000);
}

/**
 * Fetch and display current test status
 */
async function updateTestStatus() {
  if (!currentABTestId) return;

  try {
    const resp = await fetch(`${API}/${currentABTestId}/status`);
    const data = await resp.json();

    displayTestStatus(data);

    // If test completed, stop polling
    if (data.status === "completed") {
      clearInterval(abTestStatusInterval);
      showStep("ab-step-results", data);
    }
  } catch (e) {
    console.error("[AB-WF] Status update failed:", e);
  }
}

/**
 * Display test status on dashboard
 */
function displayTestStatus(data) {
  const dashboard = document.getElementById("ab-monitoring-dashboard");
  if (!dashboard) return;

  if (data.status === "running") {
    const html = `
      <div class="ab-test-monitoring">
        <div class="ab-test-header">
          <h3>A/B Test Running</h3>
          <span class="ab-time-remaining">${data.time_remaining_hours}h remaining</span>
        </div>

        <div class="ab-test-variants">
          <div class="ab-variant">
            <h4>${data.variant_a.name}</h4>
            <div class="ab-stats">
              <div class="ab-stat">
                <span class="label">Opens:</span>
                <span class="value">${data.variant_a.opens}/${data.variant_a.sent}</span>
              </div>
              <div class="ab-stat">
                <span class="label">Open Rate:</span>
                <span class="value">${data.variant_a.open_rate}%</span>
              </div>
              <div class="ab-stat">
                <span class="label">Click Rate:</span>
                <span class="value">${data.variant_a.click_rate}%</span>
              </div>
            </div>
          </div>

          <div class="ab-variant">
            <h4>${data.variant_b.name}</h4>
            <div class="ab-stats">
              <div class="ab-stat">
                <span class="label">Opens:</span>
                <span class="value">${data.variant_b.opens}/${data.variant_b.sent}</span>
              </div>
              <div class="ab-stat">
                <span class="label">Open Rate:</span>
                <span class="value">${data.variant_b.open_rate}%</span>
              </div>
              <div class="ab-stat">
                <span class="label">Click Rate:</span>
                <span class="value">${data.variant_b.click_rate}%</span>
              </div>
            </div>
          </div>
        </div>

        <div class="ab-test-note">
          Test still in progress. Metrics update every 5 seconds.
        </div>
      </div>
    `;
    dashboard.innerHTML = html;
  }
}

/**
 * Display final test results
 */
function displayTestResults(data) {
  const resultsDiv = document.getElementById("ab-test-results");
  if (!resultsDiv) return;

  const html = `
    <div class="ab-test-complete">
      <div class="ab-winner-announcement">
        <h2>🎉 Test Complete!</h2>
        <p>Winner: <strong>${data.winner_name}</strong></p>
        <p>Confidence: <strong>${data.confidence}%</strong></p>
      </div>

      <table class="ab-results-table">
        <tr>
          <th>Metric</th>
          <th>${data.variant_a.name}</th>
          <th>${data.variant_b.name}</th>
        </tr>
        <tr>
          <td>Open Rate</td>
          <td>${data.variant_a_open_rate}%</td>
          <td>${data.variant_b_open_rate}%</td>
        </tr>
      </table>

      <div class="ab-actions">
        <button onclick="sendWinnerToAudience()" class="btn btn-success">
          Send Winner to Remaining Audience
        </button>
        <button onclick="createAnotherTest()" class="btn btn-outline">
          Run Another Test
        </button>
      </div>
    </div>
  `;
  resultsDiv.innerHTML = html;
}

/**
 * Send winning variant to remaining audience
 */
async function sendWinnerToAudience() {
  if (!currentABTestId) return;

  try {
    const resp = await fetch(`${API}/${currentABTestId}/send-winner`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    const data = await resp.json();
    if (!resp.ok) {
      showError("Failed to send winner:", data.detail);
      return;
    }

    alert(`✓ Winner sent to remaining ${data.recipients_count} contacts`);
  } catch (e) {
    showError("Error sending winner:", e);
  }
}

/**
 * Start a new A/B test
 */
function createAnotherTest() {
  currentABTestId = null;
  if (abTestStatusInterval) clearInterval(abTestStatusInterval);
  showStep("ab-step-select");
  loadAvailableEmails();
  loadAvailableLists();
}

/**
 * Show specific step in workflow
 */
function showStep(stepId, data = null) {
  // Hide all steps
  document.querySelectorAll("[id^='ab-step-']").forEach(el => {
    el.classList.add("hidden");
  });

  // Show selected step
  const step = document.getElementById(stepId);
  if (step) {
    step.classList.remove("hidden");
  }

  // Update step indicators
  updateStepIndicators(stepId);
}

/**
 * Update step indicators (1, 2, 3, 4)
 */
function updateStepIndicators(currentStep) {
  const steps = {
    "ab-step-select": 1,
    "ab-step-review": 2,
    "ab-step-monitor": 3,
    "ab-step-results": 4,
  };

  Object.entries(steps).forEach(([stepId, num]) => {
    const indicator = document.querySelector(`[data-step="${num}"]`);
    if (indicator) {
      indicator.classList.toggle("active", stepId === currentStep);
    }
  });
}

/**
 * View A/B test history
 */
async function loadABTestHistory() {
  try {
    const resp = await fetch(`${API}`);
    const data = await resp.json();

    const historyDiv = document.getElementById("ab-test-history");
    if (!historyDiv) return;

    let html = '<table class="ab-history-table"><tr>';
    html += '<th>Variant A</th><th>Variant B</th><th>Status</th><th>Winner</th><th>Date</th></tr>';

    data.tests.forEach(test => {
      html += `<tr>
        <td>${test.variant_a}</td>
        <td>${test.variant_b}</td>
        <td>${test.status}</td>
        <td>${test.winner || "-"}</td>
        <td>${new Date(test.created_at).toLocaleDateString()}</td>
      </tr>`;
    });

    html += '</table>';
    historyDiv.innerHTML = html;
  } catch (e) {
    console.error("[AB-WF] Failed to load history:", e);
  }
}

/**
 * Helper: Show error message
 */
function showError(title, error) {
  console.error(title, error);
  alert(`${title}\n${error.message || error}`);
}

// Initialize on page load
document.addEventListener("DOMContentLoaded", initABWorkflow);
