const API = "/api";
let sessionId = null;
let _generatedHtml = "";

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
      <div class="claude-label">🤖 Claude</div>
      ${markdownToHtml(text)}
    </div>`;
  el.classList.remove("hidden");
}

function appendMessage(containerId, text) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const div = document.createElement("div");
  div.className = "claude-message";
  div.innerHTML = `<div class="claude-label">🤖 Claude</div>${markdownToHtml(text)}`;
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

  setLoading("step1-status", "Claude is researching the event, detecting campaign stage, and generating email content…");
  document.getElementById("plan-btn").disabled = true;

  let planSessionId = null;

  try {
    const resp = await fetch(`${API}/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, extra_context: extraContext || null, email_type: emailType || null }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Request failed");

    planSessionId = data.session_id;
    sessionId = planSessionId;
    clearStatus("step1-status");
    showStep(2);

    // ── Render plan text (isolated so errors don't block content generation)
    try { renderMessage("plan-message", data.message); } catch (_) {}

    // ── Stage badge (isolated)
    try {
      const badge = document.getElementById("stage-badge");
      if (badge && data.stage && data.stage.name && data.stage.name !== "Unknown") {
        const s = data.stage;
        badge.style.background = FUNNEL_COLORS[s.funnel] || "#6b7280";
        const iconEl = document.getElementById("stage-icon");
        const nameEl = document.getElementById("stage-name-label");
        const funnelEl = document.getElementById("stage-funnel-label");
        const daysEl = document.getElementById("stage-days-label");
        if (iconEl)   iconEl.textContent   = STAGE_ICONS[s.funnel] || "📅";
        if (nameEl)   nameEl.textContent   = s.name;
        if (funnelEl) funnelEl.textContent = `· ${s.funnel}`;
        if (daysEl && s.days_to_event != null) {
          const d = s.days_to_event;
          daysEl.textContent = d > 0 ? `(${d}d to event)` : d === 0 ? "(today!)" : `(${Math.abs(d)}d post-event)`;
        }
        badge.classList.remove("hidden");
      } else if (badge) {
        badge.classList.add("hidden");
      }
    } catch (_) {}

    // ── Source email chip (isolated)
    try {
      const chip = document.getElementById("source-email-chip");
      const nameEl = document.getElementById("source-email-name");
      if (chip && data.source_email && data.source_email.name) {
        if (nameEl) nameEl.textContent = data.source_email.name;
        chip.style.display = "flex";
        chip.classList.remove("hidden");
      } else if (chip) {
        chip.style.display = "none";
      }
    } catch (_) {}

    // ── Set loading state (isolated so it never blocks content generation)
    try { _setContentLoading(true); } catch (_) {}

  } catch (err) {
    if (!planSessionId) {
      // Plan API call failed — show error on step 1
      showError("step1-status", err.message);
    }
    // If planSessionId is set, plan succeeded but a rendering error occurred —
    // fall through to finally so content generation still fires
  } finally {
    document.getElementById("plan-btn").disabled = false;
    // Always fire content generation if the plan API returned a session
    if (planSessionId) {
      generateEmailContent(planSessionId);
    }
  }
}

// ── Content generation helpers ───────────────────────────────────────────────

function _setContentLoading(loading) {
  const approveBtn = document.getElementById("approve-btn");
  const updateBtn  = document.getElementById("update-btn");
  const badge      = document.getElementById("content-status-badge");
  const subjEl     = document.getElementById("subject-display");
  const prevEl     = document.getElementById("preview-display");
  const frame      = document.getElementById("email-preview-frame");

  if (loading) {
    approveBtn.disabled    = true;
    approveBtn.textContent = "⏳ Generating content…";
    if (updateBtn) updateBtn.disabled = true;
    if (badge)  badge.textContent  = "⏳ Generating…";
    if (subjEl) subjEl.textContent = "⏳ Generating…";
    if (prevEl) prevEl.textContent = "⏳ Generating…";
    if (frame)  frame.srcdoc = `<html><body style="margin:48px 40px;font-family:Arial,sans-serif;color:#555;text-align:center">
      <div style="font-size:36px;margin-bottom:14px">⏳</div>
      <div style="font-size:15px;font-weight:600;margin-bottom:8px">Generating email content…</div>
      <div style="font-size:13px;color:#888">Claude is using the official LF Events stage template<br>to write a personalised email. Takes ~60 seconds.</div>
    </body></html>`;
  }
}

function _applyGeneratedContent(data) {
  const approveBtn = document.getElementById("approve-btn");
  const updateBtn  = document.getElementById("update-btn");
  const badge      = document.getElementById("content-status-badge");
  const subjEl     = document.getElementById("subject-display");
  const prevEl     = document.getElementById("preview-display");
  const frame      = document.getElementById("email-preview-frame");
  const sendlistEl = document.getElementById("sendlist-display");

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

  // Update send list display if brand history has one
  if (data.send_list_name) {
    sendlistEl.textContent = data.send_list_name;
  }

  badge.textContent      = "✅ Ready to approve";
  badge.style.color      = "#16a34a";
  approveBtn.disabled    = false;
  approveBtn.textContent = "✓ Approve & Create Email";
  if (updateBtn) updateBtn.disabled = false;
}

async function generateEmailContent(sid, changeRequest = "") {
  try {
    const body = { session_id: sid };
    if (changeRequest) body.change_request = changeRequest;

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
    const frame      = document.getElementById("email-preview-frame");
    const badge      = document.getElementById("content-status-badge");
    const approveBtn = document.getElementById("approve-btn");
    const updateBtn  = document.getElementById("update-btn");

    frame.srcdoc = `<html><body style="margin:48px 40px;font-family:Arial,sans-serif;color:#c00;font-size:13px">
      <strong>⚠️ Content generation failed:</strong> ${escapeHtml(err.message)}<br><br>
      Use the "Request Changes" box to try again, or approve without auto-content.</body></html>`;
    badge.textContent      = "⚠️ Generation failed";
    badge.style.color      = "#dc2626";
    approveBtn.disabled    = false;
    approveBtn.textContent = "✓ Approve & Create Email";
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

  setLoading("change-status", "Claude is updating the content…");
  _setContentLoading(true);

  await generateEmailContent(sessionId, changeText);
  // Keep the change request text so user can iterate
}

// ── Step 2: Approve plan ─────────────────────────────────────────────────────

async function approvePlan() {
  const subject     = document.getElementById("subject").value.trim();
  const previewText = document.getElementById("preview_text").value.trim();
  const sendListId  = document.getElementById("send_list_id").value.trim();

  setLoading("step2-status", "Creating email, applying settings and content…");
  document.getElementById("approve-btn").disabled = true;

  try {
    const resp = await fetch(`${API}/clone`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        approved: true,
        subject: subject || null,
        preview_text: previewText || null,
        send_list_id: sendListId || null,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Request failed");

    clearStatus("step2-status");

    if (data.content_applied) {
      // Content was auto-applied — go directly to Done
      showStep(4);
      renderMessage("done-message", data.message);
      if (data.draft_url) showDraftLink("done-draft-link", data.draft_url);
    } else {
      // No auto-content — show optional override step
      showStep(3);
      renderMessage("clone-message", data.message);
      if (data.draft_url) showDraftLink("clone-draft-link", data.draft_url);
    }
  } catch (err) {
    showError("step2-status", err.message);
  } finally {
    document.getElementById("approve-btn").disabled = false;
  }
}

function editPlan() {
  showStep(1);
}

// ── Step 3: Submit content ───────────────────────────────────────────────────

async function submitContent() {
  const content = document.getElementById("content").value.trim();
  if (!content) {
    showError("step3-status", "Please provide email content.");
    return;
  }

  setLoading("step3-status", "Processing content and updating email body…");
  document.getElementById("content-btn").disabled = true;

  try {
    const resp = await fetch(`${API}/content`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, content }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Request failed");

    clearStatus("step3-status");
    showStep(4);
    renderMessage("done-message", data.message);
    if (data.draft_url) showDraftLink("done-draft-link", data.draft_url);
  } catch (err) {
    showError("step3-status", err.message);
  } finally {
    document.getElementById("content-btn").disabled = false;
  }
}

// ── Chat (free-form follow-up, available on steps 2-4) ──────────────────────

async function sendChat(containerId, inputId) {
  const input = document.getElementById(inputId);
  const msg = input.value.trim();
  if (!msg || !sessionId) return;
  input.value = "";

  const statusId = containerId + "-status";
  setLoading(statusId, "Claude is thinking…");

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
  document.getElementById("event_url").value = "";
  document.getElementById("extra_context").value = "";
  document.getElementById("subject").value = "";
  document.getElementById("preview_text").value = "";
  clearList();
  document.getElementById("content").value = "";

  // Reset stage badge, content displays
  document.getElementById("stage-badge").classList.add("hidden");
  const frame = document.getElementById("email-preview-frame");
  if (frame) frame.srcdoc = "";
  const subjEl = document.getElementById("subject-display");
  const prevEl = document.getElementById("preview-display");
  if (subjEl) subjEl.textContent = "⏳ Generating…";
  if (prevEl) prevEl.textContent = "⏳ Generating…";
  const badge = document.getElementById("content-status-badge");
  if (badge) { badge.textContent = "⏳ Generating…"; badge.style.color = ""; }
  const changeInput = document.getElementById("change-request-input");
  if (changeInput) changeInput.value = "";

  ["step1-status","step2-status","step3-status","plan-message","clone-message",
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
  document.getElementById("list-search-input").value = "";
  document.getElementById("list-dropdown").classList.add("hidden");
  const sel = document.getElementById("list-selected");
  sel.innerHTML = `
    <span>✓ <strong>${escapeHtml(name)}</strong></span>
    <span style="color:var(--gray-600);font-size:12px">${size ? size.toLocaleString() + " contacts" : ""}</span>
    <span class="list-clear" onclick="clearList()" title="Remove">×</span>`;
  sel.classList.remove("hidden");
}

function clearList() {
  document.getElementById("send_list_id").value = "";
  document.getElementById("list-search-input").value = "";
  document.getElementById("list-selected").classList.add("hidden");
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
    if (data.mode.includes("Claude Code")) {
      banner.innerHTML = `🤖 Running in <strong>Claude AI Mode</strong> — using Claude Code`;
      banner.className = "mode-banner mode-claude";
    } else {
      banner.innerHTML = `🤖 Running in <strong>Claude AI Mode</strong> — using Anthropic API`;
      banner.className = "mode-banner mode-claude";
    }
    banner.classList.remove("hidden");
  } catch (_) {}
}

document.addEventListener("DOMContentLoaded", () => { showStep(1); initMode(); });
