/*
 * Survey / Report Promo tab — Planning → Email Preview → Audience → Implementation.
 *
 * Ported from Survey_Workflow_automation/frontend/app.js. That file was 28 bare
 * top-level functions; this app already has globals named switchTab/setStatus/
 * escapeHtml/approved/..., so everything is wrapped in one IIFE exported as
 * `SurveyPromo` and every DOM id is `sp-` prefixed.
 *
 * The Audience step is NOT the survey app's own audience planner (dropped). It
 * drives this repo's Audience Builder via its `survey` scope (spab-* ids in
 * index.html, registered in audience-builder.js's _SCOPES). AudienceBuilder's
 * buildMaster() calls onAudienceListReady() below when a master list is composed;
 * the "use an existing list" picker calls selectExistingList() directly.
 */
const SurveyPromo = (() => {
  "use strict";

  const API = "/api/survey";

  let lastResult = null;      // { email_type, email_plan, variants: [...] }
  let heroImageId = "";
  let heroImageUrl = "";
  let approved = false;

  // Satisfied by EITHER audience path: composing a master list via the Audience
  // Builder, or picking an existing HubSpot list.
  let audienceStepComplete = false;

  // Single source of truth for "which list to send to", regardless of which
  // audience path produced it. The Implementation step reads this.
  let selectedListId = "";

  // Per-stage results from /approve (stage/email_id/draft_url/...), so the
  // Implementation step knows which HubSpot email id/draft to act on.
  let approvedResults = [];

  let implementationRendered = false;

  const TABS = ["planning", "email-preview", "audience", "implementation"];

  const STAGE_LABELS = {
    single: "Email", invite: "1. Invite", reminder: "2. Reminder", deadline: "3. Deadline",
  };

  // Furthest tab index unlocked by completing the step before it. Steps can't
  // be skipped ahead of this by clicking the tab bar.
  let unlockedTabIndex = 0;

  // ── Helpers ────────────────────────────────────────────────────────────────

  function $(id) { return document.getElementById(id); }

  function setStatus(elId, message, kind) {
    const el = $(elId);
    if (!el) return;
    el.textContent = message;
    el.className = message ? `status-${kind}` : "hidden";
  }

  function escapeAttr(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
  }

  function escapeHtml(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ── Step navigation ────────────────────────────────────────────────────────

  function updateStepsLockState() {
    TABS.forEach((t, i) => {
      const el = $(`sp-tab-${t}`);
      if (el) el.classList.toggle("locked", i > unlockedTabIndex);
    });
  }

  function unlockUpTo(idx) {
    if (idx > unlockedTabIndex) {
      unlockedTabIndex = idx;
      updateStepsLockState();
    }
  }

  function switchTab(name) {
    const idx = TABS.indexOf(name);
    if (idx > unlockedTabIndex) {
      setStatus("sp-tab-lock-status", "Complete the current step first before moving ahead.", "error");
      return;
    }
    setStatus("sp-tab-lock-status", "", "info");
    for (const t of TABS) {
      const panel = $(`sp-panel-${t}`);
      const tab = $(`sp-tab-${t}`);
      if (panel) panel.classList.toggle("hidden", t !== name);
      if (tab) tab.classList.toggle("active", t === name);
    }
    if (name === "implementation" && !implementationRendered) {
      renderImplementationPanel();
      implementationRendered = true;
    }
  }

  function goNextFromEmailPreview() {
    if (!approved) return;
    unlockUpTo(2);
    switchTab("audience");
  }

  function goNextFromAudience() {
    if (!audienceStepComplete) return;
    unlockUpTo(3);
    switchTab("implementation");
  }

  // ── Planning ───────────────────────────────────────────────────────────────

  async function uploadHeroImage() {
    const input = $("sp-hero-image-file");
    const file = input && input.files[0];
    if (!file) return;

    setStatus("sp-hero-image-status", "Uploading…", "info");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${API}/upload-hero-image`, { method: "POST", body: formData });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Upload failed (${res.status})`);
      }
      const data = await res.json();
      heroImageId = data.hero_image_id;
      heroImageUrl = data.url;

      const thumb = $("sp-hero-image-thumb");
      thumb.src = heroImageUrl;
      thumb.classList.remove("hidden");
      setStatus("sp-hero-image-status", "Staged locally. Will upload to HubSpot only on Approve.", "success");
    } catch (e) {
      setStatus("sp-hero-image-status", e.message, "error");
    }
  }

  async function generatePreview() {
    const sourceText = $("sp-source-text").value.trim();
    const promotedUrl = $("sp-promoted-url").value.trim();
    const emailType = $("sp-email-type").value;
    const emailPlan = document.querySelector('input[name="sp_email_plan"]:checked').value;

    if (!sourceText || !promotedUrl || !emailType) {
      setStatus("sp-planning-status", "Source text, link, and email type are required.", "error");
      return;
    }

    const btn = $("sp-generate-btn");
    btn.disabled = true;
    setStatus(
      "sp-planning-status",
      emailPlan === "sequence" ? "Generating invite/reminder/deadline sequence…" : "Generating preview…",
      "info"
    );

    try {
      const res = await fetch(`${API}/generate-preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_text: sourceText,
          promoted_url: promotedUrl,
          email_type: emailType,
          email_plan: emailPlan,
          hero_image_id: heroImageId,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Request failed (${res.status})`);
      }
      lastResult = await res.json();
      approved = false;
      $("sp-email-preview-next-btn").disabled = true;
      renderAllVariantCards();
      setStatus("sp-planning-status", "", "info");
      unlockUpTo(1);
      switchTab("email-preview");
    } catch (e) {
      setStatus("sp-planning-status", e.message, "error");
    } finally {
      btn.disabled = false;
    }
  }

  // ── Email Preview ──────────────────────────────────────────────────────────

  function variantCardHtml(variant, i) {
    const label = STAGE_LABELS[variant.stage] || variant.stage;
    const showShareLine = lastResult.email_type === "report";
    return `
      <div class="card variant-card">
        <div class="card-title">${lastResult.variants.length > 1 ? `Email ${label}` : "Email Preview"}</div>
        <iframe id="sp-preview-frame-${i}" style="width:100%;min-height:600px;border:1px solid var(--gray-200);border-radius:6px" srcdoc="${escapeAttr(variant.html)}"></iframe>

        <div class="field" style="margin-top:16px">
          <label>Subject</label>
          <input id="sp-edit-subject-${i}" type="text" value="${escapeAttr(variant.subject)}" />
        </div>
        <div class="field">
          <label>Preview text</label>
          <input id="sp-edit-preview-text-${i}" type="text" value="${escapeAttr(variant.preview_text)}" />
        </div>
        <div class="field">
          <label>Hero headline</label>
          <input id="sp-edit-hero-headline-${i}" type="text" value="${escapeAttr(variant.hero_headline)}" />
        </div>
        <div class="field">
          <label>Body paragraphs (one per line)</label>
          <textarea id="sp-edit-body-${i}" rows="6">${escapeHtml((variant.body_paragraphs || []).join("\n"))}</textarea>
        </div>
        <div class="field">
          <label>Impact / reason-to-care sentence</label>
          <input id="sp-edit-impact-${i}" type="text" value="${escapeAttr(variant.impact_sentence || "")}" />
        </div>
        <div class="field${showShareLine ? "" : " hidden"}">
          <label>Share-button line (report emails only)</label>
          <input id="sp-edit-share-line-${i}" type="text" value="${escapeAttr(variant.share_line || "")}" />
        </div>
        <div class="btn-row">
          <button class="btn btn-outline" onclick="SurveyPromo.rerenderVariant(${i})">Re-render this preview</button>
        </div>
      </div>
    `;
  }

  function renderAllVariantCards() {
    $("sp-preview-meta").textContent =
      lastResult.variants.length > 1
        ? `Email type: ${lastResult.email_type} — Invite → Reminder → Deadline sequence (3 emails)`
        : `Email type: ${lastResult.email_type}`;

    $("sp-variant-cards").innerHTML = lastResult.variants
      .map((v, i) => variantCardHtml(v, i))
      .join("");

    const approveBtn = $("sp-approve-btn");
    approveBtn.disabled = false;
    approveBtn.textContent =
      lastResult.variants.length > 1 ? "Approve & create 3 HubSpot drafts" : "Approve & create HubSpot draft";
    setStatus("sp-approve-status", "", "info");
    $("sp-approve-results").classList.add("hidden");
    $("sp-approve-results").innerHTML = "";
  }

  function syncEditsToVariant(i) {
    const v = lastResult.variants[i];
    v.subject = $(`sp-edit-subject-${i}`).value;
    v.preview_text = $(`sp-edit-preview-text-${i}`).value;
    v.hero_headline = $(`sp-edit-hero-headline-${i}`).value;
    v.body_paragraphs = $(`sp-edit-body-${i}`).value
      .split("\n").map(s => s.trim()).filter(Boolean);
    v.impact_sentence = $(`sp-edit-impact-${i}`).value;
    const shareEl = $(`sp-edit-share-line-${i}`);
    if (shareEl) v.share_line = shareEl.value;
  }

  async function rerenderVariant(i) {
    syncEditsToVariant(i);
    const variant = lastResult.variants[i];

    const res = await fetch(`${API}/rerender-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email_type: lastResult.email_type,
        promoted_url: $("sp-promoted-url").value.trim(),
        hero_image_id: heroImageId,
        variant,
      }),
    });
    const data = await res.json();
    variant.html = data.html;
    $(`sp-preview-frame-${i}`).srcdoc = variant.html;
  }

  async function approvePreview() {
    if (!lastResult || approved) return;
    lastResult.variants.forEach((_, i) => syncEditsToVariant(i));

    const btn = $("sp-approve-btn");
    btn.disabled = true;
    setStatus(
      "sp-approve-status",
      lastResult.variants.length > 1
        ? "Cloning the latest matching HubSpot email and applying your copy to all 3 drafts…"
        : "Cloning the latest matching HubSpot email and applying your copy…",
      "info"
    );

    try {
      const res = await fetch(`${API}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email_type: lastResult.email_type,
          promoted_url: $("sp-promoted-url").value.trim(),
          hero_image_id: heroImageId,
          variants: lastResult.variants,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Approve failed (${res.status})`);
      }
      const data = await res.json();
      approved = true;
      approvedResults = data.results;
      btn.textContent = data.results.length > 1 ? "3 drafts created" : "Draft created";
      const hasWarnings = (data.warnings || []).length > 0;
      setStatus(
        "sp-approve-status",
        `${data.results.length > 1 ? "Drafts" : "Draft"} created in HubSpot (cloned from "${data.results[0].cloned_from_name}").${hasWarnings ? " See warning below." : ` Open ${data.results.length > 1 ? "them" : "it"} below:`}`,
        hasWarnings ? "error" : "success"
      );

      const resultsEl = $("sp-approve-results");
      resultsEl.classList.remove("hidden");
      const warningsHtml = (data.warnings || [])
        .map(w => `<div class="status-error" style="margin-bottom:8px">${escapeHtml(w)}</div>`)
        .join("");
      const linksHtml = data.results
        .map(r => {
          const label = STAGE_LABELS[r.stage] || r.stage;
          return `<a class="approve-result-link" href="${escapeAttr(r.draft_url)}" target="_blank" rel="noopener">Open "${escapeHtml(label)}" draft in HubSpot →</a>`;
        })
        .join("");
      resultsEl.innerHTML = warningsHtml + linksHtml;
      $("sp-email-preview-next-btn").disabled = false;
      unlockUpTo(2);
    } catch (e) {
      btn.disabled = false;
      setStatus("sp-approve-status", e.message, "error");
    }
  }

  // ── Audience ───────────────────────────────────────────────────────────────
  // Two ways in: pick an existing HubSpot list, or describe one in plain
  // English. Both converge on markAudienceReady(). The custom flow is app.js's,
  // hosted here through its _AUD_UI_SCOPES["survey"] id set.

  const AUD_SUBTABS = ["existing", "custom"];

  function switchAudienceSubTab(name) {
    for (const t of AUD_SUBTABS) {
      const flow = $(`sp-aud-flow-${t}`);
      const btn = $(`sp-aud-tab-${t}`);
      if (flow) flow.classList.toggle("hidden", t !== name);
      if (btn) {
        btn.classList.toggle("btn-primary", t === name);
        btn.classList.toggle("btn-outline", t !== name);
      }
    }
  }

  // Both entry points below just record a HubSpot list id and unlock the next
  // step. All the actual discovery/composition work is the Audience Builder's.

  function markAudienceReady(listId) {
    selectedListId = String(listId);
    audienceStepComplete = true;
    const next = $("sp-audience-next-btn");
    if (next) next.disabled = false;
    unlockUpTo(3);
  }

  /** Called by approveCustomAudiencePlan() in app.js when scope === "survey". */
  function onAudienceListReady(listId, hubspotUrl, name) {
    markAudienceReady(listId);
    const badge = $("sp-audience-status-badge");
    if (badge) {
      badge.textContent = `✓ Audience ready (List ID ${listId})`;
      badge.style.color = "#166534";
    }
  }

  // ── Audience: pick an existing HubSpot list instead of building one ────────

  let _listSearchTimer = null;

  function onListSearch(query) {
    const dropdown = $("sp-list-dropdown");
    if (!query || query.length < 2) {
      dropdown.classList.add("hidden");
      return;
    }
    clearTimeout(_listSearchTimer);
    _listSearchTimer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/audience-builder/lists/search?q=${encodeURIComponent(query)}`);
        const data = await res.json();
        const results = data.results || [];
        if (!results.length) {
          dropdown.innerHTML = `<div class="list-dropdown-item" style="color:var(--gray-400)">No lists found</div>`;
        } else {
          dropdown.innerHTML = results.map(l => `
            <div class="list-dropdown-item" onclick="SurveyPromo.selectExistingList(${JSON.stringify(String(l.listId)).replace(/"/g, "&quot;")}, ${JSON.stringify(l.name || "").replace(/"/g, "&quot;")}, ${l.size ?? "null"})">
              <span>${escapeHtml(l.name || "")}</span>
              <span class="list-count">${l.size ? l.size.toLocaleString() + " contacts" : ""}</span>
            </div>`).join("");
        }
        dropdown.classList.remove("hidden");
      } catch (_) {
        dropdown.classList.add("hidden");
      }
    }, 300);
  }

  function selectExistingList(id, name, size) {
    const inp = $("sp-list-search-input");
    if (inp) inp.value = "";
    $("sp-list-dropdown").classList.add("hidden");

    const sel = $("sp-list-selected");
    sel.innerHTML = `
      <span>✓ <strong>${escapeHtml(name)}</strong></span>
      <span style="color:var(--gray-500);font-size:12px">${size ? Number(size).toLocaleString() + " contacts" : ""}</span>
      <span class="list-clear" onclick="SurveyPromo.clearExistingList()" title="Remove">×</span>`;
    sel.classList.remove("hidden");

    markAudienceReady(id);
  }

  function clearExistingList() {
    selectedListId = "";
    audienceStepComplete = false;
    const inp = $("sp-list-search-input");
    if (inp) inp.value = "";
    $("sp-list-selected").classList.add("hidden");
    const next = $("sp-audience-next-btn");
    if (next) next.disabled = true;
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#flow-survey-promo .list-picker")) {
      const d = $("sp-list-dropdown");
      if (d) d.classList.add("hidden");
    }
  });

  // ── Implementation ─────────────────────────────────────────────────────────

  function stageEmailId(stage) {
    const r = (approvedResults || []).find(x => x.stage === stage);
    return r ? r.email_id : "";
  }

  function renderImplementationPanel() {
    const el = $("sp-implementation-content");
    const isSequence = lastResult && lastResult.email_plan === "sequence";

    if (!isSequence) {
      const emailId = stageEmailId("single");
      el.innerHTML = `
        <div class="card">
          <div class="card-title">Schedule the send</div>
          <div class="card-desc" style="margin-top:0">
            Pick the date you plan to send this email. Clicking below attaches your selected
            audience list to the draft as its send-to list, and adds the standard suppression
            lists (global opt-outs, GDPR and master exclusion) to its <strong>don&#39;t send
            to</strong> list. It does <strong>not</strong> schedule or activate anything in
            HubSpot — you still open the draft and schedule it yourself for the date you pick.
          </div>
          <div class="field-row">
            <div class="field"><label>Send date</label><input id="sp-impl-single-date" type="date" /></div>
          </div>
          <div id="sp-impl-single-status" class="hidden"></div>
          <div class="btn-row">
            <button class="btn btn-primary" id="sp-impl-single-btn" onclick="SurveyPromo.submitImplementationSingle('${emailId}')">Attach audience list</button>
          </div>
          <div id="sp-impl-single-results" class="hidden"></div>
        </div>`;
      return;
    }

    const inviteId = stageEmailId("invite");
    const reminderId = stageEmailId("reminder");
    const deadlineId = stageEmailId("deadline");

    el.innerHTML = `
      <div class="card">
        <div class="card-title">Schedule the sequence</div>
        <div class="card-desc" style="margin-top:0">
          Pick a date and time for each of the 3 emails. All three sends, their dates, and your
          selected audience list are set on a cloned automation workflow (based on the standard
          survey-sequence workflow), created <strong>disabled</strong> — open it in HubSpot and
          turn it on yourself when ready. Nothing is activated automatically.
        </div>

        <div class="field-row">
          <div class="field"><label>1. Invite — send date</label><input id="sp-impl-invite-date" type="date" /></div>
          <div class="field"><label>Invite — send time</label><input id="sp-impl-invite-time" type="time" value="09:00" /></div>
        </div>
        <div class="field-row">
          <div class="field"><label>2. Reminder — send date</label><input id="sp-impl-reminder-date" type="date" /></div>
          <div class="field"><label>Reminder — send time</label><input id="sp-impl-reminder-time" type="time" value="10:00" /></div>
        </div>
        <div class="field-row">
          <div class="field"><label>3. Deadline — send date</label><input id="sp-impl-deadline-date" type="date" /></div>
          <div class="field"><label>Deadline — send time</label><input id="sp-impl-deadline-time" type="time" value="09:00" /></div>
        </div>

        <div id="sp-impl-sequence-status" class="hidden"></div>
        <div class="btn-row">
          <button class="btn btn-primary" id="sp-impl-sequence-btn"
            onclick="SurveyPromo.submitImplementationSequence('${inviteId}', '${reminderId}', '${deadlineId}')">
            Build sequence workflow (disabled)
          </button>
        </div>
        <div id="sp-impl-sequence-results" class="hidden"></div>
      </div>`;
  }

  async function submitImplementationSingle(emailId) {
    const listId = selectedListId || "";
    const date = $("sp-impl-single-date").value;

    if (!emailId) { setStatus("sp-impl-single-status", "No approved email found — go back and approve a draft first.", "error"); return; }
    if (!listId) { setStatus("sp-impl-single-status", "No audience list selected — go back and pick or build one first.", "error"); return; }
    if (!date) { setStatus("sp-impl-single-status", "Pick a send date.", "error"); return; }

    const btn = $("sp-impl-single-btn");
    btn.disabled = true;
    setStatus("sp-impl-single-status", "Attaching audience and suppression lists to the draft…", "info");
    try {
      const res = await fetch(`${API}/implementation/single`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email_id: emailId, list_id: listId, send_date: date }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      btn.textContent = "List attached";
      setStatus(
        "sp-impl-single-status",
        "Audience and suppression lists attached. Nothing was scheduled — open the draft below and schedule it yourself for the date you picked.",
        "success"
      );
      // Name the suppression lists that actually landed — they're resolved by
      // name search at request time, so the set can differ run to run and an
      // empty result is a real (silent) outcome worth surfacing.
      const suppressed = data.suppression_lists || [];
      const suppressedHtml = suppressed.length
        ? `<div class="card-desc" style="margin-top:10px">Added to the draft&#39;s <strong>don&#39;t send to</strong> list: ${suppressed.map((s) => escapeHtml(s.name || s.label)).join(", ")}.</div>`
        : `<div class="card-desc" style="margin-top:10px">⚠ No standard suppression lists resolved in HubSpot — check the draft&#39;s <strong>don&#39;t send to</strong> field yourself before sending.</div>`;
      const resultsEl = $("sp-impl-single-results");
      resultsEl.classList.remove("hidden");
      resultsEl.innerHTML = `<a class="approve-result-link" href="${escapeAttr(data.draft_url)}" target="_blank" rel="noopener">Open draft in HubSpot to schedule for ${escapeHtml(data.send_date)} →</a>${suppressedHtml}`;
    } catch (e) {
      btn.disabled = false;
      setStatus("sp-impl-single-status", e.message, "error");
    }
  }

  async function submitImplementationSequence(inviteId, reminderId, deadlineId) {
    const listId = selectedListId || "";
    const invite = { date: $("sp-impl-invite-date").value, time: $("sp-impl-invite-time").value };
    const reminder = { date: $("sp-impl-reminder-date").value, time: $("sp-impl-reminder-time").value };
    const deadline = { date: $("sp-impl-deadline-date").value, time: $("sp-impl-deadline-time").value };

    if (!inviteId || !reminderId || !deadlineId) {
      setStatus("sp-impl-sequence-status", "Missing one of the 3 approved emails — go back and approve all 3 drafts first.", "error");
      return;
    }
    if (!listId) { setStatus("sp-impl-sequence-status", "No audience list selected — go back and pick or build one first.", "error"); return; }
    if (!invite.date || !invite.time || !reminder.date || !reminder.time || !deadline.date || !deadline.time) {
      setStatus("sp-impl-sequence-status", "Pick a date and time for all 3 emails.", "error");
      return;
    }

    const btn = $("sp-impl-sequence-btn");
    btn.disabled = true;
    setStatus("sp-impl-sequence-status", "Cloning the sequence workflow with your emails, dates, and list (disabled)…", "info");
    try {
      const res = await fetch(`${API}/implementation/sequence`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          list_id: listId,
          invite_email_id: inviteId, reminder_email_id: reminderId, deadline_email_id: deadlineId,
          invite, reminder, deadline,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      btn.textContent = "Sequence built (disabled)";
      setStatus(
        "sp-impl-sequence-status",
        "Sequence workflow cloned with your 3 emails, dates, and audience list — disabled. Nothing was activated. Open it below to review and turn it on when ready.",
        "success"
      );
      const resultsEl = $("sp-impl-sequence-results");
      resultsEl.classList.remove("hidden");
      resultsEl.innerHTML = `
        <a class="approve-result-link" href="${escapeAttr(data.invite_draft_url)}" target="_blank" rel="noopener">Open invite draft (sent by the workflow) →</a>
        <a class="approve-result-link" href="${escapeAttr(data.workflow_url)}" target="_blank" rel="noopener">Open cloned workflow (disabled) to review &amp; enable →</a>`;
    } catch (e) {
      btn.disabled = false;
      setStatus("sp-impl-sequence-status", e.message, "error");
    }
  }

  updateStepsLockState();

  return {
    switchTab, goNextFromEmailPreview, goNextFromAudience,
    uploadHeroImage, generatePreview,
    rerenderVariant, approvePreview,
    switchAudienceSubTab,
    onAudienceListReady, onListSearch, selectExistingList, clearExistingList,
    submitImplementationSingle, submitImplementationSequence,
  };
})();
