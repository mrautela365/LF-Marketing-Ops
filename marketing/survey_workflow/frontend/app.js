const STAGE_ORDER = ["Content", "Provide List", "Staging", "Approval", "Launch", "Campaign Update"];

let currentBrief = null;
let overrides = {}; // {stageName: true/false} - local testing only, never sent to Asana
let contentOverride = ""; // manually pasted email content, used instead of the doc fetch when set
let contentLinks = []; // [{id, text, url, is_button}] - links the user wants AI to place in the pasted content
let contentLinkSeq = 0;

// ── Structured link rows for the content-override box ───────────────────────

function addContentLinkRow() {
  contentLinkSeq += 1;
  const id = `l${contentLinkSeq}`;
  contentLinks.push({ id, text: "", url: "", is_button: false });
  renderContentLinkRows();
}

function removeContentLinkRow(id) {
  contentLinks = contentLinks.filter((l) => l.id !== id);
  renderContentLinkRows();
}

function updateContentLinkField(id, field, value) {
  const link = contentLinks.find((l) => l.id === id);
  if (link) link[field] = value;
}

function renderContentLinkRows() {
  const box = document.getElementById("content-links-rows");
  if (!box) return;
  box.innerHTML = "";
  for (const link of contentLinks) {
    const row = document.createElement("div");
    row.className = "content-link-row";
    row.style.cssText = "display:flex;gap:8px;align-items:center;margin-bottom:6px;";
    row.innerHTML = `
      <input type="text" placeholder="Where should this link go? e.g. 'Register here'" style="flex:2;"
        value="${escapeHtml(link.text)}" data-field="text" />
      <input type="text" placeholder="https://…" style="flex:2;"
        value="${escapeHtml(link.url)}" data-field="url" />
      <label style="display:flex;align-items:center;gap:4px;white-space:nowrap;">
        <input type="checkbox" data-field="is_button" ${link.is_button ? "checked" : ""} /> Button
      </label>
      <button type="button" class="btn-secondary" data-action="remove">✕</button>
    `;
    row.querySelector('[data-field="text"]').addEventListener("input", (e) => updateContentLinkField(link.id, "text", e.target.value));
    row.querySelector('[data-field="url"]').addEventListener("input", (e) => updateContentLinkField(link.id, "url", e.target.value));
    row.querySelector('[data-field="is_button"]').addEventListener("change", (e) => updateContentLinkField(link.id, "is_button", e.target.checked));
    row.querySelector('[data-action="remove"]').addEventListener("click", () => removeContentLinkRow(link.id));
    box.appendChild(row);
  }
}

// ── Overrides panel ─────────────────────────────────────────────────────────

function toggleConfig() {
  document.getElementById("config-panel").classList.toggle("hidden");
}

function renderOverrideRows() {
  const box = document.getElementById("override-rows");
  box.innerHTML = "";
  for (const stage of STAGE_ORDER) {
    const val = overrides[stage]; // undefined | true | false
    const row = document.createElement("div");
    row.className = "override-row";
    row.innerHTML = `
      <span class="override-label">${stage}</span>
      <select data-stage="${stage}" onchange="onOverrideChange(this)">
        <option value="" ${val === undefined ? "selected" : ""}>Actual (from Asana)</option>
        <option value="true" ${val === true ? "selected" : ""}>Force: Completed</option>
        <option value="false" ${val === false ? "selected" : ""}>Force: Not completed</option>
      </select>
    `;
    box.appendChild(row);
  }
}

function onOverrideChange(sel) {
  const stage = sel.dataset.stage;
  if (sel.value === "") delete overrides[stage];
  else overrides[stage] = sel.value === "true";
}

function resetOverrides() {
  overrides = {};
  renderOverrideRows();
}

renderOverrideRows();

// ── Errors ───────────────────────────────────────────────────────────────

function showError(msg) {
  const box = document.getElementById("error-box");
  box.textContent = msg;
  box.classList.remove("hidden");
}
function clearError() {
  document.getElementById("error-box").classList.add("hidden");
}

// ── Tabs ─────────────────────────────────────────────────────────────────

function switchTab(name) {
  for (const t of ["planning", "staging", "launch", "campaign"]) {
    document.getElementById(`tab-${t}`).classList.toggle("active", t === name);
    document.getElementById(`panel-${t}`).classList.toggle("hidden", t !== name);
  }
  if (name === "staging") loadStagingPreview();
  if (name === "launch") renderLaunch();
  if (name === "campaign") renderCampaign();
}

// ── Brief ────────────────────────────────────────────────────────────────

function appendLog(msg) {
  const box = document.getElementById("brief-logs");
  const line = document.createElement("div");
  line.className = "log-line";
  line.textContent = msg;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

async function getBrief() {
  const url = document.getElementById("asana-url").value.trim();
  if (!url) { showError("Paste an Asana task URL first."); return; }

  clearError();
  const btn = document.getElementById("brief-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Fetching…';

  // Jump to the Staging tab and stream live backend progress there while we work.
  const logBox = document.getElementById("brief-logs");
  logBox.innerHTML = "";
  logBox.classList.remove("hidden");
  switchTab("staging");
  appendLog("Starting brief request…");

  try {
    const resp = await fetch("/api/brief-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ asana_url: url, overrides }),
    });
    if (!resp.ok || !resp.body) throw new Error(`Request failed (${resp.status})`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let brief = null;
    let streamError = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const payload = JSON.parse(line.slice(5).trim());
        if (payload.type === "log") appendLog(payload.message);
        else if (payload.type === "result") brief = payload.brief;
        else if (payload.type === "error") streamError = payload.message;
      }
    }

    if (streamError) throw new Error(streamError);
    if (!brief) throw new Error("No brief was returned.");

    currentBrief = brief;
    appendLog("Done — rendering Planning tab.");
    document.getElementById("planning-placeholder").classList.add("hidden");
    document.getElementById("task-name").classList.remove("hidden");
    renderPlanning(currentBrief);
    switchTab("planning");
  } catch (e) {
    appendLog(`Error: ${e.message}`);
    showError(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Get Brief";
  }
}

function stageByName(brief, name) {
  return (brief.stages || []).find(s => s.name === name) || {};
}

function renderPlanning(brief) {
  document.getElementById("task-name").textContent = brief.task_name || "Untitled task";

  const stageEl = document.getElementById("current-stage");
  stageEl.textContent = brief.current_stage;
  stageEl.className = "pill " + (brief.current_stage === "Done" ? "pill-done" : "pill-active");

  const overallEl = document.getElementById("overall-summary");
  if (brief.overall_summary) {
    overallEl.textContent = brief.overall_summary;
    overallEl.classList.remove("hidden");
  } else {
    overallEl.classList.add("hidden");
  }

  // Planning tab only shows the two gating stages, per the workflow rules.
  const rows = document.getElementById("planning-rows");
  rows.innerHTML = "";
  for (const name of ["Content", "Provide List", "Approval"]) {
    const s = stageByName(brief, name);
    const tr = document.createElement("tr");
    if (s.name === brief.current_stage) tr.classList.add("stage-current");
    tr.innerHTML = `
      <td>${s.name}${s.overridden ? ' <span class="override-tag">(overridden)</span>' : ""}</td>
      <td>${s.assignee || "—"}</td>
      <td><span class="status-dot ${s.completed ? "done" : "pending"}"></span>${s.completed ? "Done" : "Pending"}</td>
      <td>${s.due_on || "—"}</td>
      <td class="summary-cell">${s.summary || "—"}</td>
    `;
    rows.appendChild(tr);
  }

  const linksBox = document.getElementById("links-box");
  if (brief.content_doc_url || brief.hubspot_list_url) {
    linksBox.classList.remove("hidden");
    const docLink = document.getElementById("doc-link");
    docLink.href = brief.content_doc_url || "#";
    docLink.textContent = brief.content_doc_url || "not found yet";
    document.getElementById("doc-link-desc").textContent =
      brief.content_doc_description || (brief.content_doc_url ? "No description available yet." : "");
    const listLink = document.getElementById("list-link");
    listLink.href = brief.hubspot_list_url || "#";
    listLink.textContent = brief.hubspot_list_url || "not found yet";
    document.getElementById("list-link-desc").textContent =
      brief.hubspot_list_description || (brief.hubspot_list_url ? "No description available yet." : "");
    const workflowLink = document.getElementById("workflow-link");
    workflowLink.href = brief.hubspot_workflow_url || "#";
    workflowLink.textContent = brief.hubspot_workflow_url || "not found yet";
    document.getElementById("workflow-link-desc").textContent =
      brief.hubspot_workflow_description || (brief.hubspot_workflow_url ? "No description available yet." : "");
  } else {
    linksBox.classList.add("hidden");
  }

  const workflowInput = document.getElementById("workflow-url-input");
  if (workflowInput && !workflowInput.value.trim() && brief.hubspot_workflow_url) {
    workflowInput.value = brief.hubspot_workflow_url;
  }

  const gateMsg = document.getElementById("gate-message");
  const continueBtn = document.getElementById("continue-btn");
  if (brief.ready_to_build) {
    gateMsg.classList.add("hidden");
    continueBtn.classList.remove("hidden");
  } else {
    const waiting = [];
    if (!brief.content_done) waiting.push("Content");
    if (!brief.list_done) waiting.push("Provide List");
    gateMsg.textContent = `Dependent task${waiting.length > 1 ? "s are" : " is"} not completed: ${waiting.join(" & ")}. Staging is blocked until both are done.`;
    gateMsg.classList.remove("hidden");
    continueBtn.classList.add("hidden");
  }
}

// ── Staging ──────────────────────────────────────────────────────────────

async function loadStagingPreview() {
  if (!currentBrief) return;
  const url = document.getElementById("asana-url").value.trim();

  const logBox = document.getElementById("brief-logs");
  const locked = document.getElementById("staging-locked");
  const content = document.getElementById("staging-content");
  const existingBox = document.getElementById("staging-existing");
  const previewBox = document.getElementById("staging-preview-box");
  document.getElementById("build-results").innerHTML = "";
  document.getElementById("build-warnings").classList.add("hidden");

  if (!currentBrief.ready_to_build) {
    logBox.classList.add("hidden");
    locked.textContent = "Blocked: Content and/or Provide List are not completed yet. No staging action can be taken.";
    locked.classList.remove("hidden");
    content.classList.add("hidden");
    return;
  }

  locked.classList.add("hidden");
  content.classList.remove("hidden");
  existingBox.classList.add("hidden");
  previewBox.classList.add("hidden");
  document.getElementById("content-override-box").classList.add("hidden");

  logBox.innerHTML = "";
  logBox.classList.remove("hidden");
  appendLog("Analyzing content doc to decide draft count/splits (AI)…");

  try {
    const resp = await fetch("/api/staging-preview-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asana_url: url, overrides,
        content_override: contentOverride || null,
        content_links: contentOverride ? validContentLinks() : null,
      }),
    });
    if (!resp.ok || !resp.body) throw new Error(`Request failed (${resp.status})`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let data = null;
    let streamError = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const payload = JSON.parse(line.slice(5).trim());
        if (payload.type === "log") appendLog(payload.message);
        else if (payload.type === "result") data = payload;
        else if (payload.type === "error") streamError = payload.message;
      }
    }

    if (streamError) throw new Error(streamError);
    if (!data) throw new Error("No staging preview was returned.");
    appendLog("Done.");
    logBox.classList.add("hidden");

    if (data.gated) {
      locked.textContent = "Blocked: Content and/or Provide List are not completed yet.";
      locked.classList.remove("hidden");
      content.classList.add("hidden");
      return;
    }

    if (data.error) {
      existingBox.classList.remove("hidden");
      existingBox.innerHTML = `<div class="draft-result fail">${escapeHtml(data.error)}</div>`;
      previewBox.classList.add("hidden");
      document.getElementById("content-override-box").classList.toggle("hidden", !data.doc_fetch_failed);
      if (data.doc_fetch_failed && contentLinks.length === 0) addContentLinkRow();
      return;
    }

    if (data.already_completed) {
      existingBox.classList.remove("hidden");
      const links = data.email_links || [];
      existingBox.innerHTML = `
        <div class="gate-message" style="background:var(--green-50);color:var(--green-600)">
          Staging is already marked complete in Asana. Showing the email(s) built for it.
        </div>
        ${links.length
          ? links.map(l => `
              <div class="draft-result ok">
                <a href="${l.url || l}" target="_blank">${l.url || l}</a><br>
                <span class="summary-cell">${escapeHtml(l.description || "No description available for this link.")}</span>
              </div>`).join("")
          : '<div class="draft-result fail">No HubSpot email links found in the Staging subtask\'s comments.</div>'}
      `;
      previewBox.classList.add("hidden");
      return;
    }

    // Not yet built — show preview of what WILL be built.
    previewBox.classList.remove("hidden");
    const n = data.draft_count;
    const countMsg = document.getElementById("draft-count-msg");
    if (n > 1) {
      countMsg.textContent = `The content doc contains ${n} email drafts — these will be built as a multi-email workflow.`;
    } else {
      countMsg.textContent = `The content doc contains 1 email — no workflow needed, a single draft will be built.`;
    }

    const previewsEl = document.getElementById("draft-previews");
    previewsEl.innerHTML = (data.drafts || []).map(d => `
      <div class="draft-preview-card">
        <div class="draft-preview-title">Draft ${d.index}${d.heading ? `: ${escapeHtml(d.heading)}` : ""}</div>
        <div class="summary-cell" style="margin-bottom:8px">${escapeHtml(d.description || "No AI description available for this draft.")}</div>
        <div class="draft-preview-body">${escapeHtml(d.preview).slice(0, 4000)}</div>
      </div>
    `).join("");

    const buildBtn = document.getElementById("build-btn");
    buildBtn.textContent = n > 1 ? `Build ${n} Draft Emails (workflow)` : "Build Draft Email";
    buildBtn.disabled = false;
  } catch (e) {
    showError(e.message);
  }
}

function validContentLinks() {
  return contentLinks.filter((l) => l.text.trim() && l.url.trim());
}

// Keeps only real hyperlinks + basic text formatting from a rich paste (e.g. a
// Google Doc link that's an actual <a href>, not typed-out markdown) - strips
// scripts, event handlers, styles, and anything with a non-http(s) href so a
// malicious paste can't inject code or a javascript: link.
const CONTENT_PASTE_ALLOWED_TAGS = new Set(["A", "B", "STRONG", "I", "EM", "U", "BR", "P", "UL", "OL", "LI", "SPAN", "DIV"]);

function sanitizePastedHtml(dirtyHtml) {
  const doc = new DOMParser().parseFromString(dirtyHtml, "text/html");

  function clean(node) {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === Node.ELEMENT_NODE) {
        if (!CONTENT_PASTE_ALLOWED_TAGS.has(child.tagName)) {
          // Unwrap: keep its text/children, drop the tag itself.
          while (child.firstChild) node.insertBefore(child.firstChild, child);
          node.removeChild(child);
          continue;
        }
        for (const attr of Array.from(child.attributes)) {
          if (attr.name.toLowerCase() === "href") {
            if (!/^https?:\/\//i.test(attr.value)) child.removeAttribute("href");
          } else {
            child.removeAttribute(attr.name);
          }
        }
        clean(child);
      } else if (child.nodeType !== Node.TEXT_NODE) {
        node.removeChild(child);
      }
    }
  }
  clean(doc.body);
  return doc.body.innerHTML;
}

function retryWithPastedContent() {
  const box = document.getElementById("content-override-input");
  const html = sanitizePastedHtml(box.innerHTML).trim();
  if (!html) { showError("Paste some content first."); return; }
  const incomplete = contentLinks.some((l) => (l.text.trim() || l.url.trim()) && !(l.text.trim() && l.url.trim()));
  if (incomplete) { showError("Each link needs both a placement description and a URL — or remove the empty row."); return; }
  contentOverride = html;
  document.getElementById("content-override-box").classList.add("hidden");
  loadStagingPreview();
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s || "";
  return div.innerHTML;
}

async function buildDrafts() {
  const url = document.getElementById("asana-url").value.trim();
  const workflowUrl = (document.getElementById("workflow-url-input")?.value || "").trim();
  const btn = document.getElementById("build-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Building draft email(s)…';

  clearError();

  try {
    const resp = await fetch("/api/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asana_url: url, overrides,
        hubspot_workflow_url: workflowUrl || null,
        content_override: contentOverride || null,
        content_links: contentOverride ? validContentLinks() : null,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Build failed");

    renderBuildResult(data);
  } catch (e) {
    showError(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Build Draft Email(s)";
  }
}

function renderBuildResult(result) {
  const resultsEl = document.getElementById("build-results");
  const warningsEl = document.getElementById("build-warnings");
  resultsEl.innerHTML = "";

  if (result.gated) {
    resultsEl.innerHTML = `<div class="draft-result fail">Gated — waiting on: ${(result.waiting_on || []).join(", ")}</div>`;
  } else if (result.error) {
    resultsEl.innerHTML = `<div class="draft-result fail">${escapeHtml(result.error)}</div>`;
    document.getElementById("content-override-box").classList.toggle("hidden", !result.doc_fetch_failed);
    if (result.doc_fetch_failed && contentLinks.length === 0) addContentLinkRow();
  } else {
    for (const d of result.drafts || []) {
      const div = document.createElement("div");
      if (d.success) {
        div.className = "draft-result ok";
        div.innerHTML = `<strong>Draft ${d.draft_index}: ${d.email_name || "(unnamed)"}</strong><br>
          ${d.description ? `<span class="summary-cell">${escapeHtml(d.description)}</span><br>` : ""}
          <a href="${d.draft_url}" target="_blank">${d.draft_url}</a><br>
          Content applied: ${d.content_applied ? "yes" : "no"} · Validated: ${d.validation_passed ? "yes" : "no"}`;
      } else {
        div.className = "draft-result fail";
        div.innerHTML = `<strong>Draft ${d.draft_index} failed</strong><br>${d.error}`;
      }
      resultsEl.appendChild(div);
    }

    if (result.workflow) {
      const w = result.workflow;
      const div = document.createElement("div");
      if (w.success) {
        div.className = "draft-result ok";
        div.innerHTML = `<strong>Workflow cloned: ${escapeHtml(w.flow_name || "(unnamed)")}</strong><br>
          Cloned from ${escapeHtml(w.source_flow_name || w.source_flow_id || "")} ·
          ${w.send_email_count} email step(s) replaced${w.delay_date_count ? `, ${w.delay_date_count} delay date(s) updated from the doc` : ""}<br>
          <a href="${w.edit_url}" target="_blank">${w.edit_url}</a><br>
          <span class="summary-cell">Created disabled — review the steps in HubSpot, then enable it yourself when ready.</span>`;
      } else {
        div.className = "draft-result fail";
        div.innerHTML = `<strong>Workflow clone failed</strong><br>${escapeHtml(w.error || "")}`;
      }
      resultsEl.appendChild(div);
    }
  }

  if (result.warnings && result.warnings.length) {
    warningsEl.innerHTML = "<strong>Warnings:</strong><br>" + result.warnings.map(w => `• ${w}`).join("<br>");
    warningsEl.classList.remove("hidden");
  } else {
    warningsEl.classList.add("hidden");
  }
}

// ── Launch / Campaign Update (informational, read from current brief) ────

function renderStageInfoCard(stageName) {
  const s = stageByName(currentBrief, stageName);
  const reached = currentBrief.stages.findIndex(x => x.name === currentBrief.current_stage) >=
                  currentBrief.stages.findIndex(x => x.name === stageName) || currentBrief.current_stage === "Done";
  return `
    <div class="current-stage-row">
      <span class="label">Status:</span>
      <span class="pill ${s.completed ? "pill-done" : "pill-waiting"}">${s.completed ? "Completed" : "Pending"}</span>
      ${s.overridden ? '<span class="override-tag">(overridden)</span>' : ""}
    </div>
    <table class="stage-table">
      <tbody>
        <tr><td class="label">Assignee</td><td>${s.assignee || "—"}</td></tr>
        <tr><td class="label">Due</td><td>${s.due_on || "—"}</td></tr>
        <tr><td class="label">Summary</td><td class="summary-cell">${s.summary || "No comments yet."}</td></tr>
      </tbody>
    </table>
    ${!reached ? '<div class="gate-message">This stage hasn\'t been reached yet based on current progress.</div>' : ""}
  `;
}

function renderLaunch() {
  if (!currentBrief) return;
  document.getElementById("launch-body").innerHTML = renderStageInfoCard("Launch");
}

function renderCampaign() {
  if (!currentBrief) return;
  document.getElementById("campaign-body").innerHTML = renderStageInfoCard("Campaign Update");
}
