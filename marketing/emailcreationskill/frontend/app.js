const API = "/api";
let sessionId = null;
let _generatedHtml = "";
let _emailId = null;          // HubSpot email id of the cloned draft (set at implementation)
let _draftUrl = "";           // HubSpot draft URL of the cloned email
let _masterListId = "";       // master audience list id produced by the build step
let _sections = [];           // editable email content blocks (removable on Email Preview)
let _subLists = [];           // lists rolled into the master audience (built or selected)
let _audiencePlanText       = "";     // Phase 1 segment plan, captured for review before any list is created
let _audiencePlanEventUrl   = "";     // event_url the plan was generated for
let _audiencePlanStandalone = false;  // true when planned without a campaign session

let _activeAudienceFlow      = "event";  // "event" | "custom" — which tab's plan the shared Approve/Discard buttons act on
let _customAudienceRequest   = "";       // free-text request the custom plan was generated for
let _customAudiencePlanText  = "";       // Phase 1 segment plan for the Custom Request flow

let _extraFilters = [];  // user-added filters from the plan-review screen: {property, operator, value}

let _audienceQA           = "";    // accumulated Q&A text across replanning rounds — appended to future plan/build prompts
let _pendingQuestions      = null;  // structured questions[] awaiting a user answer (blocks Approve until cleared)
let _pendingQuestionsFlow  = "";    // "event" | "custom" — which flow's re-plan to call on submit
let _pendingQuestionsScope = "step3"; // which screen's DOM ids the pending questions were rendered into

// Element-id lookup so the Custom Audience flow (runCustomAudienceBuild, approveCustomAudiencePlan,
// renderAudienceQuestions, etc.) can be re-hosted verbatim in the Audience Builder tab's "Build From
// Scratch" section without duplicating logic — every scoped function takes a `scope` param (default
// "step3" = today's exact ids, so Step 3's existing behavior is completely unchanged) and looks up its
// DOM ids here instead of hardcoding them. "builder" ids that have no counterpart in the Audience
// Builder markup (e.g. startImplBtn — that screen never clones an email) map to "" and getElementById("")
// safely returns null, which every caller already guards against.
const _AUD_UI_SCOPES = {
  step3: {
    requestInput:     "custom_audience_request",
    urlStatus:        "custom-audience-url-status",
    buildBtn:         "custom-build-btn",
    statusBadge:      "audience-status-badge",
    ticker:           "audience-ticker",
    statusEl:         "audience-status",
    planActions:      "audience-plan-actions",
    approveBtn:       "approve-plan-btn",
    startImplBtn:     "start-impl-btn",
    questionsWrap:    "audience-questions",
    submitAnswersBtn: "submit-answers-btn",
    sublistsWrap:     "audience-sublists-wrap",
    sublists:         "audience-sublists",
  },
  builder: {
    requestInput:     "ab-custom-request",
    urlStatus:        "ab-custom-status",
    buildBtn:         "ab-custom-build-btn",
    statusBadge:      "ab-custom-status-badge",
    ticker:           "ab-custom-ticker",
    statusEl:         "ab-custom-result",
    planActions:      "ab-custom-plan-actions",
    approveBtn:       "ab-custom-approve-btn",
    startImplBtn:     "",
    questionsWrap:    "ab-custom-questions",
    submitAnswersBtn: "ab-submit-answers-btn",
    sublistsWrap:     "ab-custom-sublists-wrap",
    sublists:         "ab-custom-sublists",
  },
};

// ── Top-level screen switcher: Campaign Builder wizard vs. Audience Builder tab ──

function switchTopTab(tab) {
  const campaignScreen = document.getElementById("flow-event");
  const builderScreen  = document.getElementById("flow-audience-builder");
  const campaignPill   = document.getElementById("top-tab-campaign");
  const builderPill    = document.getElementById("top-tab-audience-builder");
  if (campaignScreen) campaignScreen.classList.toggle("hidden", tab !== "campaign");
  if (builderScreen)  builderScreen.classList.toggle("hidden", tab !== "audience-builder");
  if (campaignPill) campaignPill.classList.toggle("active", tab === "campaign");
  if (builderPill)  builderPill.classList.toggle("active", tab === "audience-builder");
}

// ── Step navigation ──────────────────────────────────────────────────────────

function showStep(n) {
  document.querySelectorAll(".step-panel").forEach(p => p.classList.add("hidden"));
  const panel = document.getElementById(`step-${n}`);
  if (panel) panel.classList.remove("hidden");

  document.querySelectorAll(".step").forEach((el, i) => {
    const num = i + 1;
    el.classList.remove("active", "done");
    if (num < n) el.classList.add("done");
    if (num === n) el.classList.add("active");
  });

  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ── Loading / error helpers ─────────────────────────────────────────────────

function setLoading(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = `<div class="loading"><div class="spinner"></div>${msg}</div>`;
  el.classList.remove("hidden");
}

function clearStatus(id) {
  const el = document.getElementById(id);
  if (el) { el.innerHTML = ""; el.classList.add("hidden"); }
}

function showError(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = `<div class="error-box">⚠️ ${escapeHtml(msg)}</div>`;
  el.classList.remove("hidden");
}

// ── Claude message renderer ──────────────────────────────────────────────────

function renderMessage(containerId, text) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = `
    <div class="claude-message">
      <div class="claude-label">📋 Campaign Builder</div>
      ${markdownToHtml(text)}
    </div>`;
  el.classList.remove("hidden");
}

function appendMessage(containerId, text) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const div = document.createElement("div");
  div.className = "claude-message";
  div.innerHTML = `<div class="claude-label">📋 Campaign Builder</div>${markdownToHtml(text)}`;
  el.appendChild(div);
  el.classList.remove("hidden");
}

function markdownToHtml(text) {
  let html = escapeHtml(text);

  // Bold & italic
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+?)\*/g, "<em>$1</em>");

  // Inline code
  html = html.replace(/`([^`]+?)`/g, "<code>$1</code>");

  // Headers
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h3>$1</h3>");

  // Tables
  html = _renderTables(html);

  // Checkboxes (before bullets)
  html = html.replace(/^- \[x\] (.+)$/gim, "<li class='done'>✅ $1</li>");
  html = html.replace(/^- \[ \] (.+)$/gim, "<li class='todo'>☐ $1</li>");

  // Unordered bullets
  html = html.replace(/^[-•] (.+)$/gm, "<li>$1</li>");

  // Ordered list items  ← NEW: handles "1. item", "2. item" etc.
  html = html.replace(/^\d+\. (.+)$/gm, "<oli>$1</oli>");

  // Wrap consecutive <li> into <ul>
  html = html.replace(/(<li[^>]*>[\s\S]*?<\/li>\n?)+/g, m => `<ul>${m}</ul>`);

  // Wrap consecutive <oli> into <ol>  ← NEW
  html = html.replace(/(<oli>[\s\S]*?<\/oli>\n?)+/g, m => {
    const items = m.replace(/<oli>([\s\S]*?)<\/oli>/g, "<li>$1</li>");
    return `<ol>${items}</ol>`;
  });

  // Split into paragraph blocks and wrap
  html = html.split(/\n{2,}/).map(p => {
    p = p.trim();
    if (!p) return "";
    if (/^<(h3|ul|ol|table|li)/.test(p)) return p;
    // Single newlines within a paragraph → <br>
    return `<p>${p.replace(/\n/g, "<br>")}</p>`;
  }).filter(Boolean).join("\n");

  return html;
}

function _renderTables(html) {
  const lines = html.split("\n");
  const out = [];
  let inTable = false;
  let headerDone = false;
  for (const line of lines) {
    if (line.startsWith("|") && line.endsWith("|")) {
      if (!inTable) { out.push("<table>"); inTable = true; headerDone = false; }
      if (/^\|[-\s|]+\|$/.test(line)) { headerDone = true; continue; }
      const cells = line.slice(1, -1).split("|").map(c => c.trim());
      const tag = !headerDone ? "th" : "td";
      out.push(`<tr>${cells.map(c => `<${tag}>${c}</${tag}>`).join("")}</tr>`);
    } else {
      if (inTable) { out.push("</table>"); inTable = false; }
      out.push(line);
    }
  }
  if (inTable) out.push("</table>");
  return out.join("\n");
}

function escapeHtml(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showDraftLink(containerId, url) {
  const el = document.getElementById(containerId);
  if (!el || !url) return;
  el.innerHTML = `
    <div class="draft-link-box">
      <span class="icon">✅</span>
      <div>
        <strong>Email staged as DRAFT</strong><br>
        <a href="${url}" target="_blank">${url}</a>
      </div>
    </div>`;
  el.classList.remove("hidden");
}

// ── Step 1: Generate plan ────────────────────────────────────────────────────

const FUNNEL_COLORS = {
  "TOFU":      "#16a34a",
  "MOFU":      "#d97706",
  "BOFU":      "#dc2626",
  "FOLLOW-UP": "#7c3aed",
};

const STAGE_ICONS = {
  "TOFU":      "📢",
  "MOFU":      "🎯",
  "BOFU":      "🔥",
  "FOLLOW-UP": "💌",
};

// ── Live brief helpers (real-time backend narration) ─────────────────────────
let _briefES = null;

function _newToken() {
  return "tok-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}
function resetBrief() {
  const log = document.getElementById("brief-log");
  if (log) log.innerHTML = "";
  const card = document.getElementById("brief-card");
  if (card) card.classList.remove("hidden");
}
function appendBrief(text) {
  const log = document.getElementById("brief-log");
  if (!log) return;
  const line = document.createElement("div");
  line.className = "brief-line";
  line.textContent = text;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}
function setBriefStatus(state) {
  const el = document.getElementById("brief-status");
  if (!el) return;
  if (state === "running") { el.textContent = "● live"; el.style.color = "var(--blue)"; }
  else if (state === "done") { el.textContent = "✓ done"; el.style.color = "#16a34a"; }
  else if (state === "error") { el.textContent = "⚠ error"; el.style.color = "#dc2626"; }
}
function closeBriefStream() { if (_briefES) { try { _briefES.close(); } catch (_) {} _briefES = null; } }

function openBriefStream(token, { onPlanDone } = {}) {
  closeBriefStream();
  _briefES = new EventSource(`${API}/progress/${encodeURIComponent(token)}`);
  _briefES.onmessage = (e) => {
    let m; try { m = JSON.parse(e.data); } catch { return; }
    if (m.type === "heartbeat") return;
    if (m.type === "brief") {
      appendBrief(m.text);
      if (m.error) setBriefStatus("error");
    } else if (m.type === "plan_done") {
      if (onPlanDone) onPlanDone(m.result);
    } else if (m.type === "error") {
      appendBrief("⚠️ " + (m.text || "error"));
      setBriefStatus("error");
    }
  };
  _briefES.onerror = () => { /* EventSource auto-reconnects; ignore transient drops */ };
}

function renderStageBadge(stage) {
  const badge = document.getElementById("stage-badge");
  if (!badge) return;
  if (stage && stage.name && stage.name !== "Unknown") {
    badge.style.background = FUNNEL_COLORS[stage.funnel] || "#6b7280";
    const iconEl = document.getElementById("stage-icon");
    const nameEl = document.getElementById("stage-name-label");
    const funnelEl = document.getElementById("stage-funnel-label");
    const daysEl = document.getElementById("stage-days-label");
    if (iconEl)   iconEl.textContent   = STAGE_ICONS[stage.funnel] || "📅";
    if (nameEl)   nameEl.textContent   = stage.name;
    if (funnelEl) funnelEl.textContent = `· ${stage.funnel}`;
    if (daysEl && stage.days_to_event != null) {
      const d = stage.days_to_event;
      daysEl.textContent = d > 0 ? `(${d}d to event)` : d === 0 ? "(today!)" : `(${Math.abs(d)}d post-event)`;
    }
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }
}

function renderSourceChip(source) {
  const chip = document.getElementById("source-email-chip");
  const nameEl = document.getElementById("source-email-name");
  if (!chip) return;
  if (source && source.name) {
    if (nameEl) nameEl.textContent = source.name;
    chip.style.display = "flex";
    chip.classList.remove("hidden");
  } else {
    chip.style.display = "none";
  }
}

function renderUtmChip(utm) {
  const chip = document.getElementById("utm-chip");
  if (!chip) return;
  if (!utm || !utm.utm_campaign) {
    chip.style.display = "none";
    return;
  }
  const isRealCampaign = utm.source === "hubspot_campaign";
  chip.style.background = isRealCampaign ? "var(--green-light)" : "var(--blue-light)";
  chip.style.border = isRealCampaign ? "1px solid #86efac" : "1px solid #c7d2fe";

  const sourceLabel = document.getElementById("utm-source-label");
  const nameEl      = document.getElementById("utm-campaign-name");
  const campaignEl  = document.getElementById("utm-campaign-value");
  const utmSourceEl = document.getElementById("utm-source-value");
  const utmMediumEl = document.getElementById("utm-medium-value");

  if (sourceLabel) sourceLabel.textContent = isRealCampaign ? "HubSpot Campaign:" : "Auto-generated UTM:";
  if (nameEl)       nameEl.textContent     = utm.campaign_name ? `(${utm.campaign_name})` : "";
  if (campaignEl)   campaignEl.textContent = utm.utm_campaign;
  if (utmSourceEl)  utmSourceEl.textContent = utm.utm_source || "email";
  if (utmMediumEl)  utmMediumEl.textContent = utm.utm_medium || "";

  chip.style.display = "flex";
  chip.classList.remove("hidden");
}

async function generatePlan() {
  const url = document.getElementById("event_url").value.trim();
  const extraContext = document.getElementById("extra_context").value.trim();
  const emailType = document.getElementById("email_type").value;

  if (!url) {
    showError("step1-status", "Please enter an event or campaign URL.");
    return;
  }
  if (!url.startsWith("http")) {
    showError("step1-status", "Please enter a valid URL starting with http:// or https://");
    return;
  }

  // Immediately advance to Email Preview; the backend work streams in below.
  clearStatus("step1-status");
  const token = _newToken();
  showStep(2);
  resetBrief();
  setBriefStatus("running");
  appendBrief("🚀 Starting campaign brief…");
  try { renderMessage("plan-message", "_Building your campaign plan…_"); } catch (_) {}
  try { _setContentLoading(true); } catch (_) {}

  openBriefStream(token, {
    onPlanDone: (result) => {
      if (!result) return;
      sessionId = result.session_id;
      try { renderMessage("plan-message", result.message); } catch (_) {}
      try { renderStageBadge(result.stage); } catch (_) {}
      try { renderSourceChip(result.source_email); } catch (_) {}
      try { renderUtmChip(result.utm); } catch (_) {}
      // Draft the email content next — streams into the same brief, returns sections.
      generateEmailContent(sessionId, "", token).finally(() => {
        setBriefStatus("done");
        closeBriefStream();
      });
    },
  });

  try {
    const resp = await fetch(`${API}/plan-start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, extra_context: extraContext || null, email_type: emailType || null, progress_token: token }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Failed to start campaign brief");
  } catch (err) {
    appendBrief("⚠️ " + err.message);
    setBriefStatus("error");
    closeBriefStream();
  }
}

// ── Content generation helpers ───────────────────────────────────────────────

function _setContentLoading(loading) {
  const audBtn    = document.getElementById("build-audience-btn");
  const updateBtn = document.getElementById("update-btn");
  const badge     = document.getElementById("content-status-badge");
  const subjEl    = document.getElementById("subject-display");
  const prevEl    = document.getElementById("preview-display");
  const frame     = document.getElementById("email-preview-frame");

  if (loading) {
    if (audBtn)    { audBtn.disabled = true; audBtn.textContent = "⏳ Drafting content…"; }
    if (updateBtn) updateBtn.disabled = true;
    if (badge)  badge.textContent  = "⏳ Drafting…";
    if (subjEl) subjEl.textContent = "⏳ Drafting…";
    if (prevEl) prevEl.textContent = "⏳ Drafting…";
    if (frame)  frame.srcdoc = `<html><body style="margin:48px 40px;font-family:Arial,sans-serif;color:#555;text-align:center">
      <div style="font-size:36px;margin-bottom:14px">⏳</div>
      <div style="font-size:15px;font-weight:600;margin-bottom:8px">Drafting email content…</div>
      <div style="font-size:13px;color:#888">Using the official LF Events stage template<br>to write a personalised email. Takes ~60 seconds.</div>
    </body></html>`;
  }
}

function _applyGeneratedContent(data) {
  const audBtn     = document.getElementById("build-audience-btn");
  const updateBtn  = document.getElementById("update-btn");
  const badge      = document.getElementById("content-status-badge");
  const subjEl     = document.getElementById("subject-display");
  const prevEl     = document.getElementById("preview-display");
  const frame      = document.getElementById("email-preview-frame");

  // Fill display elements
  if (data.generated_subject) {
    subjEl.textContent = data.generated_subject;
    document.getElementById("subject").value = data.generated_subject;
  }
  if (data.generated_preview) {
    prevEl.textContent = data.generated_preview;
    document.getElementById("preview_text").value = data.generated_preview;
  }

  _generatedHtml = data.generated_html || "";
  if (_generatedHtml) frame.srcdoc = _generatedHtml;

  // Removable content sections
  _sections = Array.isArray(data.sections) ? data.sections : [];
  renderSections();

  badge.textContent = "✅ Ready";
  badge.style.color = "#16a34a";
  if (audBtn)    { audBtn.disabled = false; audBtn.textContent = "Continue to Audience Preview →"; }
  if (updateBtn) updateBtn.disabled = false;
}

async function generateEmailContent(sid, changeRequest = "", token = "") {
  try {
    const body = { session_id: sid };
    if (changeRequest) body.change_request = changeRequest;
    if (token) body.progress_token = token;

    const resp = await fetch(`${API}/generate-content`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Content generation failed");

    _applyGeneratedContent(data);
    clearStatus("change-status");

  } catch (err) {
    const frame     = document.getElementById("email-preview-frame");
    const badge     = document.getElementById("content-status-badge");
    const audBtn    = document.getElementById("build-audience-btn");
    const updateBtn = document.getElementById("update-btn");

    frame.srcdoc = `<html><body style="margin:48px 40px;font-family:Arial,sans-serif;color:#c00;font-size:13px">
      <strong>⚠️ Content drafting failed:</strong> ${escapeHtml(err.message)}<br><br>
      Use the "Refine Content" box to try again, or continue to audience.</body></html>`;
    badge.textContent      = "⚠️ Drafting failed";
    badge.style.color      = "#dc2626";
    if (audBtn)    { audBtn.disabled = false; audBtn.textContent = "Continue to Audience Preview →"; }
    if (updateBtn) updateBtn.disabled = false;
    showError("change-status", err.message);
  }
}

// ── Request changes (regenerate content with user instructions) ───────────────

async function requestContentChanges() {
  const input      = document.getElementById("change-request-input");
  const changeText = input.value.trim();
  if (!changeText) return;
  if (!sessionId)  return;

  const token = _newToken();
  resetBrief();
  setBriefStatus("running");
  appendBrief("🔄 Refining the email content…");
  setLoading("change-status", "Refining the content…");
  _setContentLoading(true);

  openBriefStream(token, {});
  await generateEmailContent(sessionId, changeText, token);
  setBriefStatus("done");
  closeBriefStream();
  // Keep the change request text so user can iterate
}

// ── Removable email content sections ──────────────────────────────────────────

const _TRASH_SVG = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>';

function renderSections() {
  const wrap = document.getElementById("sections-editor");
  if (!wrap) return;
  if (!_sections.length) { wrap.innerHTML = ""; return; }

  wrap.innerHTML = _sections.map((sec, i) => {
    const isBtn = sec.type === "button";
    const label = isBtn ? "Button" : "Text block";
    const body  = isBtn
      ? `<div class="section-btn-chip">${escapeHtml(sec.text || "Button")}</div>`
      : `<div class="section-html">${sec.html || ""}</div>`;
    return `
      <div class="section-row">
        <div class="section-meta">
          <span class="section-tag">${label}</span>
        </div>
        <div class="section-body">${body}</div>
        <button class="section-remove" title="Remove this section" onclick="removeSection(${i})">${_TRASH_SVG}</button>
      </div>`;
  }).join("");
}

async function removeSection(index) {
  if (index < 0 || index >= _sections.length) return;
  _sections.splice(index, 1);
  renderSections();
  // Rebuild the live preview + persist the trimmed sections for the clone.
  try {
    const resp = await fetch(`${API}/update-sections`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, sections: _sections }),
    });
    const data = await resp.json();
    if (resp.ok && data.generated_html) {
      _generatedHtml = data.generated_html;
      const frame = document.getElementById("email-preview-frame");
      if (frame) frame.srcdoc = _generatedHtml;
    }
  } catch (_) { /* preview will catch up on next change */ }
}

// ── Step 2 → 3: Build the campaign ───────────────────────────────────────────
// Submit ONLY clones the email. The send list is attached later:
//  • audience path  → after the segmented list is built (runAudienceBuild)
//  • email-only path → immediately if a list was manually picked

// ── Step 2 → 3: advance to Audience Preview (no auto-build) ─────────────────
function goToAudience() {
  showStep(3);
  resetAudienceUI();
  updateAudienceUrlPrompt();
}

// Audience Preview pill is always clickable — jumps straight to Step 3 without
// resetting any build/selection already in progress, regardless of Step 1/2 status.
function goToAudienceTab() {
  showStep(3);
  updateAudienceUrlPrompt();
}

// Switch between the "Event Audience" (event URL) and "Custom Audience" (free text)
// tabs. Purely a UI toggle — never clears in-progress plan/ticker state, so
// switching tabs and back doesn't silently discard work in either flow.
function switchAudienceTab(tab) {
  _activeAudienceFlow = tab;
  const eventPanel  = document.getElementById("audience-flow-event");
  const customPanel = document.getElementById("audience-flow-custom");
  const eventBtn    = document.getElementById("audience-tab-event");
  const customBtn   = document.getElementById("audience-tab-custom");
  if (eventPanel)  eventPanel.classList.toggle("hidden", tab !== "event");
  if (customPanel) customPanel.classList.toggle("hidden", tab !== "custom");
  if (eventBtn)  { eventBtn.classList.toggle("btn-primary", tab === "event");   eventBtn.classList.toggle("btn-outline", tab !== "event"); }
  if (customBtn) { customBtn.classList.toggle("btn-primary", tab === "custom"); customBtn.classList.toggle("btn-outline", tab !== "custom"); }
}

// Show the "paste a URL" prompt whenever no event page has been scraped yet
// (no campaign session — e.g. Audience Preview was opened without Step 1/2).
function updateAudienceUrlPrompt() {
  const prompt = document.getElementById("audience-url-prompt");
  if (!prompt) return;
  if (sessionId) {
    prompt.classList.add("hidden");
    return;
  }
  const urlInput = document.getElementById("audience_event_url");
  const step1Url = (document.getElementById("event_url") || {}).value || "";
  if (urlInput && !urlInput.value) urlInput.value = step1Url;
  prompt.classList.remove("hidden");
}

function submitAudienceUrl() {
  const urlInput = document.getElementById("audience_event_url");
  const url = ((urlInput && urlInput.value) || "").trim();
  if (!url || !url.startsWith("http")) {
    showError("audience-url-status", "Please enter a valid URL starting with http:// or https://");
    return;
  }
  clearStatus("audience-url-status");
  document.getElementById("audience-url-prompt").classList.add("hidden");
  runAudienceBuild(url);
}

// Reset the Audience Preview tab to its initial "choose an option" state.
function resetAudienceUI() {
  _masterListId = "";
  _subLists = [];
  _audiencePlanText = "";
  _audiencePlanEventUrl = "";
  _audiencePlanStandalone = false;
  _customAudienceRequest = "";
  _customAudiencePlanText = "";
  _extraFilters = [];
  _audienceQA = "";
  clearAudienceQuestions("step3");
  renderExtraFilters();
  switchAudienceTab("event");
  clearList();
  const options = document.getElementById("audience-options");
  if (options) options.style.display = "";
  const startBuild = document.getElementById("start-build-btn");
  if (startBuild) startBuild.disabled = false;
  const customBuild = document.getElementById("custom-build-btn");
  if (customBuild) customBuild.disabled = false;
  const customTextarea = document.getElementById("custom_audience_request");
  if (customTextarea) customTextarea.value = "";
  const ticker = document.getElementById("audience-ticker");
  if (ticker) { ticker.textContent = ""; ticker.classList.add("hidden"); }
  const planActions = document.getElementById("audience-plan-actions");
  if (planActions) planActions.classList.add("hidden");
  const wrap = document.getElementById("audience-sublists-wrap");
  if (wrap) wrap.classList.add("hidden");
  const subs = document.getElementById("audience-sublists");
  if (subs) subs.innerHTML = "";
  const status = document.getElementById("audience-status");
  if (status) { status.innerHTML = ""; status.classList.add("hidden"); }
  const badge = document.getElementById("audience-status-badge");
  if (badge) { badge.textContent = "— choose how to set the send audience"; badge.style.color = "var(--gray-400)"; }
  const startImpl = document.getElementById("start-impl-btn");
  if (startImpl) { startImpl.disabled = true; startImpl.textContent = "Create Campaign Draft →"; }
}

// Skip audience entirely — create the email only (no send list attached).
function skipAudience() {
  _masterListId = "";
  startImplementation();
}

// ── Step 3 → 4: Start Implementation — clone the email, then attach the list ──
async function startImplementation() {
  const subject     = document.getElementById("subject").value.trim();
  const previewText = document.getElementById("preview_text").value.trim();

  const startBtn = document.getElementById("start-impl-btn");
  if (startBtn) { startBtn.disabled = true; startBtn.textContent = "⏳ Creating Draft…"; }

  showStep(4);
  const badge = document.getElementById("impl-status-badge");
  if (badge) { badge.textContent = "Cloning email…"; badge.style.color = "var(--gray-500)"; }
  setLoading("done-message", "Cloning the email to a HubSpot draft and applying the campaign content…");

  try {
    // Submit = clone the email only. The audience list is attached right after.
    const resp = await fetch(`${API}/clone`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        approved: true,
        subject: subject || null,
        preview_text: previewText || null,
        send_list_id: null,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Request failed");

    _emailId  = data.email_id || null;
    _draftUrl = data.draft_url || "";
    renderMessage("done-message", data.message);
    if (_draftUrl) showDraftLink("done-draft-link", _draftUrl);

    // Attach the built master audience list (the "later update" after clone).
    if (_masterListId && _emailId) {
      if (badge) badge.textContent = "Attaching audience…";
      try {
        const slResp = await fetch(`${API}/set-send-list`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, email_id: _emailId, send_list_id: _masterListId }),
        });
        const slData = await slResp.json();
        if (!slResp.ok) throw new Error(slData.detail || "Send list not applied");
        appendMessage("done-message", `✅ Master audience attached as send list (List ID ${_masterListId}${slData.list_type ? `, ${slData.list_type}` : ""}).`);
        if (badge) { badge.textContent = "✓ Complete"; badge.style.color = "#166534"; }
      } catch (slErr) {
        appendMessage("done-message", `⚠️ Audience list built (ID ${_masterListId}) but NOT attached: ${slErr.message}. Apply it manually in HubSpot.`);
        if (badge) { badge.textContent = "⚠ Attach failed"; badge.style.color = "#dc2626"; }
      }
    } else {
      appendMessage("done-message", "ℹ️ No audience list attached — set a send list manually in HubSpot.");
      if (badge) { badge.textContent = "✓ Complete"; badge.style.color = "#166534"; }
    }
  } catch (err) {
    clearStatus("done-message");
    if (badge) { badge.textContent = "⚠ Failed"; badge.style.color = "#dc2626"; }
    renderMessage("done-message", `⚠️ Implementation failed: ${escapeHtml(err.message)}`);
    showStep(3);
    if (startBtn) { startBtn.disabled = false; startBtn.textContent = "Create Campaign Draft →"; }
  }
}

function editPlan() {
  showStep(1);
}

// ── Chat (free-form follow-up, available on steps 2-4) ──────────────────────

async function sendChat(containerId, inputId) {
  const input = document.getElementById(inputId);
  const msg = input.value.trim();
  if (!msg || !sessionId) return;
  input.value = "";

  const statusId = containerId + "-status";
  setLoading(statusId, "Working on it…");

  try {
    const resp = await fetch(`${API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: msg }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Request failed");
    clearStatus(statusId);
    appendMessage(containerId, data.message);
  } catch (err) {
    showError(statusId, err.message);
  }
}

function onChatKey(event, containerId, inputId) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendChat(containerId, inputId);
  }
}

// ── Start new session ────────────────────────────────────────────────────────

function startOver() {
  sessionId = null;
  _generatedHtml = "";
  _emailId = null;
  _draftUrl = "";
  _masterListId = "";
  _sections = [];
  closeBriefStream();
  const briefLog = document.getElementById("brief-log");
  if (briefLog) briefLog.innerHTML = "";
  const sectionsEd = document.getElementById("sections-editor");
  if (sectionsEd) sectionsEd.innerHTML = "";
  document.getElementById("event_url").value = "";
  document.getElementById("extra_context").value = "";
  document.getElementById("subject").value = "";
  document.getElementById("preview_text").value = "";
  clearList();

  // Reset stage badge, content displays
  document.getElementById("stage-badge").classList.add("hidden");
  document.getElementById("utm-chip").classList.add("hidden");
  document.getElementById("utm-chip").style.display = "none";
  const frame = document.getElementById("email-preview-frame");
  if (frame) frame.srcdoc = "";
  const subjEl = document.getElementById("subject-display");
  const prevEl = document.getElementById("preview-display");
  if (subjEl) subjEl.textContent = "⏳ Drafting…";
  if (prevEl) prevEl.textContent = "⏳ Drafting…";
  const badge = document.getElementById("content-status-badge");
  if (badge) { badge.textContent = "⏳ Drafting…"; badge.style.color = ""; }
  const changeInput = document.getElementById("change-request-input");
  if (changeInput) changeInput.value = "";

  // Reset step-2 advance button + step-3 audience UI + implementation badge
  const audBtn = document.getElementById("build-audience-btn");
  if (audBtn) { audBtn.disabled = true; audBtn.textContent = "⏳ Drafting content…"; }
  resetAudienceUI();
  const implBadge = document.getElementById("impl-status-badge");
  if (implBadge) { implBadge.textContent = ""; implBadge.style.color = ""; }

  ["step1-status","step2-status","plan-message","clone-message",
   "clone-draft-link","done-message","done-draft-link"].forEach(clearStatus);
  showStep(1);
}

// ── Searchable list picker ────────────────────────────────────────────────────

let _listSearchTimer = null;

async function onListSearch(query) {
  const dropdown = document.getElementById("list-dropdown");
  if (!query || query.length < 2) {
    dropdown.classList.add("hidden");
    return;
  }
  clearTimeout(_listSearchTimer);
  _listSearchTimer = setTimeout(async () => {
    try {
      const resp = await fetch(`${API}/lists/search?q=${encodeURIComponent(query)}`);
      const data = await resp.json();
      const lists = data.lists || [];
      if (!lists.length) {
        dropdown.innerHTML = `<div class="list-dropdown-item" style="color:var(--gray-400)">No lists found</div>`;
      } else {
        dropdown.innerHTML = lists.map(l => `
          <div class="list-dropdown-item" onclick="selectList('${l.id}','${escapeHtml(l.name)}',${l.size})">
            <span>${escapeHtml(l.name)}</span>
            <span class="list-count">${l.size ? l.size.toLocaleString() + " contacts" : ""}</span>
          </div>`).join("");
      }
      dropdown.classList.remove("hidden");
    } catch (_) {}
  }, 300);
}

function selectList(id, name, size) {
  document.getElementById("send_list_id").value = id;
  const inp = document.getElementById("list-search-input");
  if (inp) inp.value = "";
  document.getElementById("list-dropdown").classList.add("hidden");
  const sel = document.getElementById("list-selected");
  sel.innerHTML = `
    <span>✓ <strong>${escapeHtml(name)}</strong></span>
    <span style="color:var(--gray-600);font-size:12px">${size ? size.toLocaleString() + " contacts" : ""}</span>
    <span class="list-clear" onclick="clearList()" title="Remove">×</span>`;
  sel.classList.remove("hidden");

  // An existing list becomes the send list directly (attached at implementation).
  _masterListId = String(id);
  _subLists = [{ name: name, id: String(id), kind: "selected" }];
  renderSubLists();
  const badge = document.getElementById("audience-status-badge");
  if (badge) { badge.textContent = "✓ Existing list selected"; badge.style.color = "#166534"; }
  const startImpl = document.getElementById("start-impl-btn");
  if (startImpl) { startImpl.disabled = false; startImpl.textContent = "Create Campaign Draft →"; }
}

function clearList() {
  const idEl = document.getElementById("send_list_id");
  if (idEl) idEl.value = "";
  const inEl = document.getElementById("list-search-input");
  if (inEl) inEl.value = "";
  const selEl = document.getElementById("list-selected");
  if (selEl) selEl.classList.add("hidden");
  // If the cleared selection was the chosen send list (no build ran), reset it.
  if (_subLists.length === 1 && _subLists[0].kind === "selected") {
    _masterListId = "";
    _subLists = [];
    renderSubLists();
    const startImpl = document.getElementById("start-impl-btn");
    if (startImpl) startImpl.disabled = true;
    const badge = document.getElementById("audience-status-badge");
    if (badge) { badge.textContent = "— choose how to set the send audience"; badge.style.color = "var(--gray-400)"; }
  }
}

// ── Sub-lists rolled into the master audience ─────────────────────────────────

const _LIST_SVG = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>';

function renderSubLists(scope = "step3") {
  const ids  = _AUD_UI_SCOPES[scope] || _AUD_UI_SCOPES.step3;
  const wrap = document.getElementById(ids.sublistsWrap);
  const box  = document.getElementById(ids.sublists);
  if (!box) return;
  if (!_subLists.length) {
    box.innerHTML = "";
    if (wrap) wrap.classList.add("hidden");
    return;
  }
  if (wrap) wrap.classList.remove("hidden");
  box.innerHTML = _subLists.map(s => {
    const tag = s.kind === "master"   ? '<span class="sublist-tag master">Master</span>'
              : s.kind === "selected" ? '<span class="sublist-tag selected">Selected</span>'
              : "";
    const idHtml = s.url
      ? `<a class="sublist-id" href="${escapeHtml(s.url)}" target="_blank" rel="noopener">ID ${escapeHtml(s.id)}</a>`
      : `<span class="sublist-id">ID ${escapeHtml(s.id)}</span>`;
    return `<div class="sublist-row">
      <span class="sublist-ico">${_LIST_SVG}</span>
      <span class="sublist-name">${escapeHtml(s.name)}</span>
      ${idHtml}
      ${tag}
    </div>`;
  }).join("");
}

// Parse "✅ <name> created — ID: <id> — <url>" or "🔁 <name> updated in place — ID: <id> — <url>"
// lines from the build log into sub-list rows (RULE 10/RULE 6 reuse-check prints the latter).
function _parseSubList(text, scope = "step3") {
  const m = String(text).match(/(?:✅|🔁)\s*(.+?)\s+(?:created|updated in place)\s*[—\-:]+\s*ID:?\s*(\d{3,})(?:\s*[—\-]+\s*(\S+))?/i);
  if (!m) return;
  const name = m[1].trim().replace(/^\[|\]$/g, "");
  const id   = m[2];
  const url  = m[3] || "";
  const existing = _subLists.find(s => s.id === id);
  if (existing) { if (url) existing.url = url; return; }
  _subLists.push({ name, id, url, kind: "created" });
  renderSubLists(scope);
}

// ── Plan-review "add more filters" panel ─────────────────────────────────────
// Lets the user tack extra property conditions onto the plan before approving;
// they get folded into the plan text sent to the build phase (see
// _extraFiltersPlanText()) so the agent ANDs each one into every inclusion group.

const _EXTRA_FILTER_NO_VALUE_OPS = new Set(["is known", "is unknown"]);

function _toggleExtraFilterValueInput() {
  const op  = document.getElementById("extra-filter-operator");
  const val = document.getElementById("extra-filter-value");
  if (!op || !val) return;
  const noValue = _EXTRA_FILTER_NO_VALUE_OPS.has(op.value);
  val.disabled = noValue;
  val.placeholder = noValue ? "(no value needed)" : "Value (comma-separate for multiple)";
  if (noValue) val.value = "";
}

function addExtraFilter() {
  const propEl = document.getElementById("extra-filter-property");
  const opEl   = document.getElementById("extra-filter-operator");
  const valEl  = document.getElementById("extra-filter-value");
  if (!propEl || !opEl || !valEl) return;

  const property = propEl.value.trim();
  const operator = opEl.value;
  const value    = valEl.value.trim();
  const needsValue = !_EXTRA_FILTER_NO_VALUE_OPS.has(operator);

  if (!property) { showError("custom-audience-url-status", "Enter a property name for the filter."); return; }
  if (needsValue && !value) { showError("custom-audience-url-status", "Enter a value for this filter, or pick 'is known'/'is unknown'."); return; }
  clearStatus("custom-audience-url-status");

  _extraFilters.push({ property, operator, value: needsValue ? value : "" });
  propEl.value = "";
  valEl.value  = "";
  renderExtraFilters();
}

function removeExtraFilter(index) {
  _extraFilters.splice(index, 1);
  renderExtraFilters();
}

function renderExtraFilters() {
  const box = document.getElementById("extra-filter-list");
  if (!box) return;
  box.innerHTML = _extraFilters.map((f, i) => `
    <span class="sublist-tag" style="background:var(--gray-100);color:var(--gray-700);display:inline-flex;align-items:center;gap:6px;padding:5px 8px">
      ${escapeHtml(f.property)} ${escapeHtml(f.operator)}${f.value ? ` "${escapeHtml(f.value)}"` : ""}
      <a href="#" onclick="removeExtraFilter(${i});return false;" style="color:var(--gray-500);text-decoration:none;font-weight:700">✕</a>
    </span>`).join("");
}

// Rendered as a plan addendum the building-phase prompt (RULE 11 / RULE 7)
// knows to parse and AND into every inclusion group it builds.
function _extraFiltersPlanText() {
  if (!_extraFilters.length) return "";
  const lines = _extraFilters.map(f =>
    `- Property "${f.property}" ${f.operator}${f.value ? ` "${f.value}"` : ""}`);
  return `\n\n## USER-ADDED FILTERS\n${lines.join("\n")}\n`;
}

function _masterListLinkHtml(mid, url) {
  return url
    ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">List ID ${escapeHtml(mid)}</a>`
    : `List ID ${escapeHtml(mid)}`;
}

function _markMaster(id, url, scope = "step3") {
  id = String(id);
  let found = false;
  _subLists.forEach(s => { if (s.id === id) { s.kind = "master"; if (url) s.url = url; found = true; } });
  if (!found) _subLists.push({ name: "Master Audience", id, url: url || "", kind: "master" });
  renderSubLists(scope);
}

// ── Structured clarifying questions (present_open_questions tool) ───────────
// When the planning agent has open/blocking questions, it calls the
// present_open_questions tool instead of only printing an "Open questions /
// flags" table. The backend forwards that as an SSE {type:'question'} event;
// we render it as selectable buttons (+ optional free-text "Other") here,
// then fold the answers into _audienceQA and re-run planning so the agent
// incorporates them into a revised plan before the user approves the build.

let _questionAnswers = [];  // parallel array to _pendingQuestions — selected/typed answer per question, "" until answered

function renderAudienceQuestions(questions, flow, scope = "step3") {
  const ids  = _AUD_UI_SCOPES[scope] || _AUD_UI_SCOPES.step3;
  const wrap = document.getElementById(ids.questionsWrap);
  if (!wrap) return;
  if (!questions || !questions.length) { clearAudienceQuestions(scope); return; }

  _pendingQuestions = questions;
  _pendingQuestionsFlow = flow;
  _pendingQuestionsScope = scope;
  _questionAnswers = questions.map(() => "");

  const approveBtn = document.getElementById(ids.approveBtn);
  if (approveBtn) approveBtn.disabled = true;

  wrap.innerHTML = questions.map((qq, i) => {
    const opts = (qq.options || []).map(opt => `
      <button type="button" class="btn btn-outline audience-q-opt" data-qi="${i}" data-val="${escapeHtml(opt)}"
        onclick="selectAudienceAnswer(${i}, this)" style="margin:3px 6px 3px 0">${escapeHtml(opt)}</button>
    `).join("");
    const customInput = qq.allow_custom !== false ? `
      <input type="text" placeholder="Other — type your own answer" data-qi="${i}"
        oninput="typeAudienceAnswer(${i}, this.value)"
        style="margin-top:6px;width:100%;max-width:360px;font-size:13px;padding:6px 9px" />
    ` : "";
    return `
      <div class="audience-question" data-qi="${i}" style="margin-bottom:14px;padding:10px 12px;background:#fffbeb;border:1px solid #fcd34d;border-radius:6px">
        <div style="font-weight:600;font-size:13px;color:var(--gray-800)">${i + 1}. ${escapeHtml(qq.question || "")}</div>
        ${qq.why_it_blocks ? `<div style="font-size:12px;color:var(--gray-500);margin-top:2px">${escapeHtml(qq.why_it_blocks)}</div>` : ""}
        <div style="margin-top:8px">${opts}</div>
        ${customInput}
      </div>
    `;
  }).join("") + `
    <div class="btn-row" style="margin-top:4px">
      <button class="btn btn-primary" id="${ids.submitAnswersBtn}" onclick="submitAudienceAnswers()" disabled>
        Submit Answers &amp; Regenerate Plan
      </button>
    </div>
  `;
  wrap.classList.remove("hidden");
  wrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function _refreshSubmitAnswersBtn(scope = _pendingQuestionsScope) {
  const ids = _AUD_UI_SCOPES[scope] || _AUD_UI_SCOPES.step3;
  const btn = document.getElementById(ids.submitAnswersBtn);
  if (btn) btn.disabled = _questionAnswers.some(a => !a);
}

function selectAudienceAnswer(qi, btnEl) {
  _questionAnswers[qi] = btnEl.dataset.val;
  const group = btnEl.closest(".audience-question");
  if (group) {
    group.querySelectorAll(".audience-q-opt").forEach(b => {
      b.classList.toggle("btn-primary", b === btnEl);
      b.classList.toggle("btn-outline", b !== btnEl);
    });
    const custom = group.querySelector("input[type=text]");
    if (custom) custom.value = "";
  }
  _refreshSubmitAnswersBtn();
}

function typeAudienceAnswer(qi, value, scope = _pendingQuestionsScope) {
  _questionAnswers[qi] = value.trim();
  const ids = _AUD_UI_SCOPES[scope] || _AUD_UI_SCOPES.step3;
  const group = document.querySelector(`#${ids.questionsWrap} .audience-question[data-qi="${qi}"]`);
  if (group && value.trim()) {
    group.querySelectorAll(".audience-q-opt").forEach(b => b.classList.replace("btn-primary", "btn-outline"));
  }
  _refreshSubmitAnswersBtn(scope);
}

function clearAudienceQuestions(scope = _pendingQuestionsScope) {
  _pendingQuestions = null;
  _pendingQuestionsFlow = "";
  _questionAnswers = [];
  const ids = _AUD_UI_SCOPES[scope] || _AUD_UI_SCOPES.step3;
  const wrap = document.getElementById(ids.questionsWrap);
  if (wrap) { wrap.innerHTML = ""; wrap.classList.add("hidden"); }
  const approveBtn = document.getElementById(ids.approveBtn);
  if (approveBtn) approveBtn.disabled = false;
}

function submitAudienceAnswers(scope = _pendingQuestionsScope) {
  if (!_pendingQuestions || _questionAnswers.some(a => !a)) return;
  const qaBlock = _pendingQuestions.map((qq, i) =>
    `Q: ${qq.question}\nA: ${_questionAnswers[i]}`
  ).join("\n");
  _audienceQA = _audienceQA ? `${_audienceQA}\n${qaBlock}` : qaBlock;
  const flow = _pendingQuestionsFlow;
  clearAudienceQuestions(scope);
  if (flow === "custom") {
    runCustomAudienceBuild(scope);
  } else {
    runAudienceBuild(_audiencePlanEventUrl);
  }
}

// ── Step 3: Audience Preview — plan the segment, then build only after approval ──
//
// Two stages, both streamed over the same SSE endpoint:
//   1. runAudienceBuild()    — Phase 1 only. Produces a plan as text. No HubSpot lists exist yet.
//   2. approveAudiencePlan() — Phase 2 only, using the reviewed plan text. This is the only
//                              function in this file that actually creates HubSpot lists.

// Open the shared SSE stream and dispatch to the given handlers.
// `onDelta(text)` gets raw streamed chunks for live ticker rendering (no forced
// newline — chunks are appended as-is). `onOutput(line)` only ever fires with
// complete, reconstructed lines (deltas are buffered until a `\n`), since callers
// like _parseSubList() regex-match a full line and would break on fragments.
function _openAudienceStream(jobId, streamSessionId, handlers) {
  const streamUrl = streamSessionId
    ? `${API}/audience-stream/${jobId}?session_id=${encodeURIComponent(streamSessionId)}`
    : `${API}/audience-stream/${jobId}`;
  const es = new EventSource(streamUrl);
  let lineBuf = "";

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    if (msg.type === "heartbeat") return;
    if (msg.type === "output" && msg.text) {
      if (msg.delta) {
        handlers.onDelta && handlers.onDelta(msg.text);
        lineBuf += msg.text;
        let idx;
        while ((idx = lineBuf.indexOf("\n")) !== -1) {
          const line = lineBuf.slice(0, idx);
          lineBuf = lineBuf.slice(idx + 1);
          if (line.trim()) handlers.onOutput && handlers.onOutput(line);
        }
      } else {
        handlers.onDelta && handlers.onDelta(msg.text + "\n");
        handlers.onOutput && handlers.onOutput(msg.text);
      }
      return;
    }
    if (msg.type === "question") {
      handlers.onQuestion && handlers.onQuestion(msg.questions || []);
      return;
    }
    if (msg.type === "complete") {
      if (lineBuf.trim()) { handlers.onOutput && handlers.onOutput(lineBuf); lineBuf = ""; }
      es.close(); handlers.onComplete && handlers.onComplete(msg); return;
    }
    if (msg.type === "error") { es.close(); handlers.onError && handlers.onError(msg); }
  };
  es.onerror = () => { es.close(); handlers.onError && handlers.onError({ text: "Stream disconnected" }); };
  return es;
}

// Stage 1 — generate the segment plan. `urlOverride` is set when kicked off from the
// "paste a URL" prompt (no campaign session yet, or the session's own scrape failed).
// Creates no HubSpot lists — see submitAudienceUrl().
async function runAudienceBuild(urlOverride) {
  const eventUrl   = (urlOverride || "").trim();
  const standalone = !sessionId;  // no campaign session → nothing scraped yet, no email to attach to later
  if (standalone && !eventUrl) { updateAudienceUrlPrompt(); return; }

  _activeAudienceFlow = "event";
  _masterListId = "";
  _subLists = [];
  _audiencePlanText = "";
  _audiencePlanEventUrl = eventUrl;
  _audiencePlanStandalone = standalone;
  renderSubLists();
  clearList();  // drop any previously selected existing list

  const badge       = document.getElementById("audience-status-badge");
  const buildBtn    = document.getElementById("start-build-btn");
  const ticker      = document.getElementById("audience-ticker");
  const statusEl    = document.getElementById("audience-status");
  const planActions = document.getElementById("audience-plan-actions");
  const startImpl   = document.getElementById("start-impl-btn");

  if (badge)       { badge.textContent = "⏳ Planning audience segment…"; badge.style.color = "var(--gray-500)"; }
  if (buildBtn)    { buildBtn.disabled = true; }
  if (planActions) planActions.classList.add("hidden");
  if (startImpl)   { startImpl.disabled = true; startImpl.textContent = "Create Campaign Draft →"; }
  ticker.textContent = "";
  ticker.classList.remove("hidden");
  statusEl.classList.add("hidden");
  statusEl.innerHTML = "";
  clearAudienceQuestions();

  let jobId = null;
  try {
    const resp = await fetch(`${API}/${standalone ? "audience/plan" : "audience-plan"}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(standalone
        ? { event_url: eventUrl, qa: _audienceQA }
        : { session_id: sessionId, event_url: eventUrl, qa: _audienceQA }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "Failed to start planning");
    }
    const data = await resp.json();
    jobId = data.job_id;
    _audiencePlanEventUrl = data.event_url || eventUrl;
  } catch (e) {
    ticker.classList.add("hidden");
    if (badge)    { badge.textContent = "⚠ Planning failed — " + escapeHtml(e.message); badge.style.color = "#dc2626"; }
    if (buildBtn) buildBtn.disabled = false;
    // Scrape/URL missing — surface the URL prompt instead of leaving a dead end.
    if (/no event url/i.test(e.message || "")) updateAudienceUrlPrompt();
    return;
  }

  _openAudienceStream(jobId, standalone ? "" : sessionId, {
    onDelta: (text) => {
      ticker.textContent += text;
      ticker.scrollTop = ticker.scrollHeight;
    },
    onQuestion: (questions) => renderAudienceQuestions(questions, "event"),
    onComplete: (msg) => {
      if (buildBtn) buildBtn.disabled = false;
      _audiencePlanText = ticker.textContent.trim();
      if (!_audiencePlanText || msg.success === false) {
        if (badge) { badge.textContent = "⚠ Planning failed — see log above"; badge.style.color = "#dc2626"; }
        return;
      }
      if (badge) { badge.textContent = "📝 Plan ready — review below, then approve to create lists"; badge.style.color = "#92400e"; }
      if (planActions) planActions.classList.remove("hidden");
    },
    onError: (msg) => {
      if (badge)    { badge.textContent = `⚠ Planning error: ${escapeHtml(msg.text || "unknown")}`; badge.style.color = "#dc2626"; }
      if (buildBtn) buildBtn.disabled = false;
    },
  });
}

// Stage 2 — the user has reviewed the plan text in the ticker; now actually create the
// HubSpot lists (Phase 2 only, reusing the captured plan so it isn't re-generated).
async function approveAudiencePlan() {
  if (!_audiencePlanText) return;
  const standalone = _audiencePlanStandalone;

  const badge       = document.getElementById("audience-status-badge");
  const ticker      = document.getElementById("audience-ticker");
  const statusEl    = document.getElementById("audience-status");
  const planActions = document.getElementById("audience-plan-actions");
  const approveBtn  = document.getElementById("approve-plan-btn");
  const startImpl   = document.getElementById("start-impl-btn");

  if (approveBtn) approveBtn.disabled = true;
  if (badge)      { badge.textContent = "⏳ Creating HubSpot lists…"; badge.style.color = "var(--gray-500)"; }
  if (startImpl)  { startImpl.disabled = true; startImpl.textContent = "⏳ Building audience…"; }
  ticker.textContent += "\n── Building approved plan ──\n";
  ticker.scrollTop = ticker.scrollHeight;

  const planWithExtras = _audiencePlanText + _extraFiltersPlanText();

  let jobId = null;
  try {
    const resp = await fetch(`${API}/${standalone ? "audience/run" : "build-audience"}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(standalone
        ? { event_url: _audiencePlanEventUrl, plan: planWithExtras, qa: _audienceQA }
        : { session_id: sessionId, event_url: _audiencePlanEventUrl, plan: planWithExtras, qa: _audienceQA }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "Failed to start audience build");
    }
    const data = await resp.json();
    jobId = data.job_id;
  } catch (e) {
    if (badge)      { badge.textContent = "⚠ Build failed — " + escapeHtml(e.message); badge.style.color = "#dc2626"; }
    if (approveBtn) approveBtn.disabled = false;
    if (startImpl)  { startImpl.disabled = true; startImpl.textContent = "Create Campaign Draft →"; }
    return;
  }

  _openAudienceStream(jobId, standalone ? "" : sessionId, {
    onDelta: (text) => {
      ticker.textContent += text;
      ticker.scrollTop = ticker.scrollHeight;
    },
    onOutput: (text) => {
      _parseSubList(text);  // surface each created list below the log
    },
    onComplete: (msg) => {
      if (approveBtn) approveBtn.disabled = false;
      const mid = msg.master_list_id;
      if (mid) {
        _masterListId = String(mid);
        _markMaster(mid, msg.master_list_url);
        if (planActions) planActions.classList.add("hidden");
        const link = _masterListLinkHtml(mid, msg.master_list_url);
        if (statusEl) {
          statusEl.classList.remove("hidden");
          statusEl.innerHTML = standalone
            ? `<span style="color:#166534">✅ Master audience ready (${link}). Start a campaign plan (Step 1) to attach it to an email.</span>`
            : `<span style="color:#166534">✅ Master audience ready (${link}). It is attached to the email when you start implementation.</span>`;
        }
        if (badge) { badge.textContent = `✓ Audience ready (ID ${escapeHtml(mid)})`; badge.style.color = "#166534"; }
        // Implementation clones/attaches against a campaign session — nothing to attach to yet in standalone mode.
        if (startImpl) { startImpl.disabled = standalone; startImpl.textContent = "Create Campaign Draft →"; }
      } else {
        if (badge)     { badge.textContent = "⚠ Build finished but list ID not found — pick an existing list or skip"; badge.style.color = "#92400e"; }
        if (startImpl) { startImpl.disabled = true; startImpl.textContent = "Create Campaign Draft →"; }
      }
    },
    onError: (msg) => {
      if (badge)      { badge.textContent = `⚠ Build error: ${escapeHtml(msg.text || "unknown")}`; badge.style.color = "#dc2626"; }
      if (approveBtn) approveBtn.disabled = false;
    },
  });
}

// ── Custom Request flow — free-text description instead of an event URL ─────
// Mirrors runAudienceBuild()/approveAudiencePlan() exactly; only the request
// payload and endpoint paths differ. Shares the same ticker/plan-actions/
// sub-lists/status UI, dispatched via _activeAudienceFlow.

async function runCustomAudienceBuild(scope = "step3") {
  const ids = _AUD_UI_SCOPES[scope] || _AUD_UI_SCOPES.step3;
  const textarea = document.getElementById(ids.requestInput);
  const request = ((textarea && textarea.value) || "").trim();
  if (!request) {
    showError(ids.urlStatus, "Please describe the audience you need.");
    return;
  }
  clearStatus(ids.urlStatus);

  _activeAudienceFlow = "custom";
  _masterListId = "";
  _subLists = [];
  _customAudienceRequest = request;
  _customAudiencePlanText = "";
  renderSubLists(scope);
  if (scope === "step3") clearList();

  const badge       = document.getElementById(ids.statusBadge);
  const buildBtn    = document.getElementById(ids.buildBtn);
  const ticker      = document.getElementById(ids.ticker);
  const statusEl    = document.getElementById(ids.statusEl);
  const planActions = document.getElementById(ids.planActions);
  const startImpl   = document.getElementById(ids.startImplBtn);

  if (badge)       { badge.textContent = "⏳ Planning audience segment…"; badge.style.color = "var(--gray-500)"; }
  if (buildBtn)    buildBtn.disabled = true;
  if (planActions) planActions.classList.add("hidden");
  if (startImpl)   { startImpl.disabled = true; startImpl.textContent = "Create Campaign Draft →"; }
  if (ticker)   { ticker.textContent = ""; ticker.classList.remove("hidden"); }
  if (statusEl) { statusEl.classList.add("hidden"); statusEl.innerHTML = ""; }
  clearAudienceQuestions(scope);

  const standalone = !sessionId;
  let jobId = null;
  try {
    const resp = await fetch(`${API}/audience/custom-plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request, session_id: standalone ? "" : sessionId, qa: _audienceQA }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "Failed to start planning");
    }
    const data = await resp.json();
    jobId = data.job_id;
  } catch (e) {
    if (ticker) ticker.classList.add("hidden");
    if (badge)    { badge.textContent = "⚠ Planning failed — " + escapeHtml(e.message); badge.style.color = "#dc2626"; }
    if (buildBtn) buildBtn.disabled = false;
    return;
  }

  _openAudienceStream(jobId, standalone ? "" : sessionId, {
    onDelta: (text) => {
      if (!ticker) return;
      ticker.textContent += text;
      ticker.scrollTop = ticker.scrollHeight;
    },
    onQuestion: (questions) => renderAudienceQuestions(questions, "custom", scope),
    onComplete: (msg) => {
      if (buildBtn) buildBtn.disabled = false;
      _customAudiencePlanText = (ticker ? ticker.textContent : "").trim();
      if (!_customAudiencePlanText || msg.success === false) {
        if (badge) { badge.textContent = "⚠ Planning failed — see log above"; badge.style.color = "#dc2626"; }
        return;
      }
      if (badge) { badge.textContent = "📝 Plan ready — review below, then approve to create lists"; badge.style.color = "#92400e"; }
      if (planActions) planActions.classList.remove("hidden");
    },
    onError: (msg) => {
      if (badge)    { badge.textContent = `⚠ Planning error: ${escapeHtml(msg.text || "unknown")}`; badge.style.color = "#dc2626"; }
      if (buildBtn) buildBtn.disabled = false;
    },
  });
}

async function approveCustomAudiencePlan(scope = "step3") {
  if (!_customAudiencePlanText) return;
  const ids = _AUD_UI_SCOPES[scope] || _AUD_UI_SCOPES.step3;
  const standalone = !sessionId;

  const badge       = document.getElementById(ids.statusBadge);
  const ticker      = document.getElementById(ids.ticker);
  const statusEl    = document.getElementById(ids.statusEl);
  const planActions = document.getElementById(ids.planActions);
  const approveBtn  = document.getElementById(ids.approveBtn);
  const startImpl   = document.getElementById(ids.startImplBtn);

  if (approveBtn) approveBtn.disabled = true;
  if (badge)      { badge.textContent = "⏳ Creating HubSpot lists…"; badge.style.color = "var(--gray-500)"; }
  if (startImpl)  { startImpl.disabled = true; startImpl.textContent = "⏳ Building audience…"; }
  if (ticker) { ticker.textContent += "\n── Building approved plan ──\n"; ticker.scrollTop = ticker.scrollHeight; }

  let jobId = null;
  try {
    const resp = await fetch(`${API}/audience/custom-run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request: _customAudienceRequest,
        session_id: standalone ? "" : sessionId,
        plan: _customAudiencePlanText + _extraFiltersPlanText(),
        qa: _audienceQA,
      }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "Failed to start audience build");
    }
    const data = await resp.json();
    jobId = data.job_id;
  } catch (e) {
    if (badge)      { badge.textContent = "⚠ Build failed — " + escapeHtml(e.message); badge.style.color = "#dc2626"; }
    if (approveBtn) approveBtn.disabled = false;
    if (startImpl)  { startImpl.disabled = true; startImpl.textContent = "Create Campaign Draft →"; }
    return;
  }

  _openAudienceStream(jobId, standalone ? "" : sessionId, {
    onDelta: (text) => {
      if (!ticker) return;
      ticker.textContent += text;
      ticker.scrollTop = ticker.scrollHeight;
    },
    onOutput: (text) => {
      _parseSubList(text, scope);
    },
    onComplete: (msg) => {
      if (approveBtn) approveBtn.disabled = false;
      const mid = msg.master_list_id;
      if (mid) {
        _masterListId = String(mid);
        _markMaster(mid, msg.master_list_url, scope);
        if (planActions) planActions.classList.add("hidden");
        const link = _masterListLinkHtml(mid, msg.master_list_url);
        if (statusEl) {
          statusEl.classList.remove("hidden");
          statusEl.innerHTML = scope === "builder"
            ? `<span style="color:#166534">✅ Master audience ready (${link}). Use it as the send list for any campaign.</span>`
            : standalone
              ? `<span style="color:#166534">✅ Master audience ready (${link}). Start a campaign plan (Step 1) to attach it to an email.</span>`
              : `<span style="color:#166534">✅ Master audience ready (${link}). It is attached to the email when you start implementation.</span>`;
        }
        if (badge) { badge.textContent = `✓ Audience ready (ID ${escapeHtml(mid)})`; badge.style.color = "#166534"; }
        if (startImpl) { startImpl.disabled = standalone; startImpl.textContent = "Create Campaign Draft →"; }
      } else {
        if (badge)     { badge.textContent = "⚠ Build finished but list ID not found — pick an existing list or skip"; badge.style.color = "#92400e"; }
        if (startImpl) { startImpl.disabled = true; startImpl.textContent = "Create Campaign Draft →"; }
      }
    },
    onError: (msg) => {
      if (badge)      { badge.textContent = `⚠ Build error: ${escapeHtml(msg.text || "unknown")}`; badge.style.color = "#dc2626"; }
      if (approveBtn) approveBtn.disabled = false;
    },
  });
}

// Shared Approve button dispatches to whichever tab's plan is active.
function approveActiveAudiencePlan() {
  if (_activeAudienceFlow === "custom") approveCustomAudiencePlan();
  else approveAudiencePlan();
}

// Discard the reviewed plan without building anything, back to the initial choice state.
function discardAudiencePlan() {
  const flow = _activeAudienceFlow;
  resetAudienceUI();
  if (flow === "custom") switchAudienceTab("custom");
  else updateAudienceUrlPrompt();
}

// Close dropdown when clicking outside
document.addEventListener("click", (e) => {
  if (!e.target.closest(".list-picker")) {
    const d = document.getElementById("list-dropdown");
    if (d) d.classList.add("hidden");
  }
});

// ── Init ─────────────────────────────────────────────────────────────────────

async function initMode() {
  try {
    const resp = await fetch(`${API}/status`);
    const data = await resp.json();
    const banner = document.getElementById("mode-banner");
    if (!banner) return;
    banner.innerHTML = `⚡ <strong>Marketing Automation</strong> — connected to HubSpot`;
    banner.className = "mode-banner mode-claude";
    banner.classList.remove("hidden");
  } catch (_) {}
}

document.addEventListener("DOMContentLoaded", () => { showStep(1); initMode(); });
