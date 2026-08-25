let lastResult = null; // { email_type, email_plan, variants: [...] }
let heroImageId = "";
let heroImageUrl = "";
let approved = false;

let lastAudiencePlan = null;
let audienceQA = "";
let audienceBuilt = false;

// Shared "audience step complete" gate for the Next button — satisfied by
// EITHER sub-tab: the Custom Audience flow (buildAudience()) or picking an
// existing list in the Use Existing List sub-tab (selectExistingList()).
let audienceStepComplete = false;

// The single source of truth for "which list to send to", regardless of
// which Audience Preview sub-tab produced it — set by buildAudience() and by
// selectExistingList(). The Implementation tab reads this.
let selectedListId = "";

// Per-stage results from /api/approve (stage/email_id/draft_url/...), so the
// Implementation tab knows which HubSpot email id/draft to act on.
let approvedResults = [];

let implementationRendered = false;

let activeAudienceSubTab = "reuse";

const TABS = ["planning", "email-preview", "audience-preview", "implementation"];

const STAGE_LABELS = { single: "Email", invite: "1. Invite", reminder: "2. Reminder", deadline: "3. Deadline" };

// Furthest tab index the user has unlocked by completing the step before it.
// Steps can't be skipped ahead of this by clicking the tab bar.
let unlockedTabIndex = 0;

function updateStepsLockState() {
  TABS.forEach((t, i) => {
    document.getElementById(`tab-${t}`).classList.toggle("locked", i > unlockedTabIndex);
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
    setStatus("tab-lock-status", "Complete the current step first before moving ahead.", "error");
    return;
  }
  setStatus("tab-lock-status", "", "info");
  for (const t of TABS) {
    document.getElementById(`panel-${t}`).classList.toggle("hidden", t !== name);
    document.getElementById(`tab-${t}`).classList.toggle("active", t === name);
  }
  if (name === "implementation" && !implementationRendered) {
    renderImplementationPanel();
    implementationRendered = true;
  }
}

function goNextFromEmailPreview() {
  if (!approved) return;
  unlockUpTo(2);
  switchTab("audience-preview");
}

function goNextFromAudiencePreview() {
  if (!audienceStepComplete) return;
  unlockUpTo(3);
  switchTab("implementation");
}

function switchAudienceTab(name) {
  activeAudienceSubTab = name;
  document.getElementById("audience-subpanel-reuse").classList.toggle("hidden", name !== "reuse");
  document.getElementById("audience-subpanel-custom").classList.toggle("hidden", name !== "custom");
  document.getElementById("audience-subtab-btn-reuse").className = `btn ${name === "reuse" ? "btn-primary" : "btn-outline"}`;
  document.getElementById("audience-subtab-btn-custom").className = `btn ${name === "custom" ? "btn-primary" : "btn-outline"}`;
}

updateStepsLockState();

function setStatus(elId, message, kind) {
  const el = document.getElementById(elId);
  el.textContent = message;
  el.className = message ? `status-${kind}` : "hidden";
}

async function uploadHeroImage() {
  const input = document.getElementById("hero_image_file");
  const file = input.files[0];
  if (!file) return;

  setStatus("hero-image-status", "Uploading…", "info");
  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/upload-hero-image", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Upload failed (${res.status})`);
    }
    const data = await res.json();
    heroImageId = data.hero_image_id;
    heroImageUrl = data.url;

    const thumb = document.getElementById("hero_image_thumb");
    thumb.src = heroImageUrl;
    thumb.classList.remove("hidden");
    setStatus("hero-image-status", "Staged locally. Will upload to HubSpot only on Approve.", "success");
  } catch (e) {
    setStatus("hero-image-status", e.message, "error");
  }
}

async function generatePreview() {
  const sourceText = document.getElementById("source_text").value.trim();
  const promotedUrl = document.getElementById("promoted_url").value.trim();
  const emailType = document.getElementById("email_type").value;
  const emailPlan = document.querySelector('input[name="email_plan"]:checked').value;

  if (!sourceText || !promotedUrl || !emailType) {
    setStatus("planning-status", "Source text, link, and email type are required.", "error");
    return;
  }

  const btn = document.getElementById("generate-btn");
  btn.disabled = true;
  setStatus(
    "planning-status",
    emailPlan === "sequence" ? "Generating invite/reminder/deadline sequence…" : "Generating preview…",
    "info"
  );

  try {
    const res = await fetch("/api/generate-preview", {
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
    document.getElementById("email-preview-next-btn").disabled = true;
    renderAllVariantCards();
    setStatus("planning-status", "", "info");
    unlockUpTo(1);
    switchTab("email-preview");
  } catch (e) {
    setStatus("planning-status", e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

function variantCardHtml(variant, i) {
  const label = STAGE_LABELS[variant.stage] || variant.stage;
  const showShareLine = lastResult.email_type === "report";
  return `
    <div class="card variant-card">
      <div class="card-title">${lastResult.variants.length > 1 ? `Email ${label}` : "Email Preview"}</div>
      <iframe id="preview-frame-${i}" style="width:100%;min-height:600px;border:1px solid #ddd;border-radius:6px" srcdoc="${escapeAttr(variant.html)}"></iframe>

      <div class="field" style="margin-top:16px">
        <label>Subject</label>
        <input id="edit_subject-${i}" type="text" value="${escapeAttr(variant.subject)}" />
      </div>
      <div class="field">
        <label>Preview text</label>
        <input id="edit_preview_text-${i}" type="text" value="${escapeAttr(variant.preview_text)}" />
      </div>
      <div class="field">
        <label>Hero headline</label>
        <input id="edit_hero_headline-${i}" type="text" value="${escapeAttr(variant.hero_headline)}" />
      </div>
      <div class="field">
        <label>Body paragraphs (one per line)</label>
        <textarea id="edit_body-${i}" rows="6">${escapeHtml((variant.body_paragraphs || []).join("\n"))}</textarea>
      </div>
      <div class="field">
        <label>Impact / reason-to-care sentence</label>
        <input id="edit_impact_sentence-${i}" type="text" value="${escapeAttr(variant.impact_sentence || "")}" />
      </div>
      <div class="field${showShareLine ? "" : " hidden"}">
        <label>Share-button line (report emails only)</label>
        <input id="edit_share_line-${i}" type="text" value="${escapeAttr(variant.share_line || "")}" />
      </div>
      <div class="btn-row">
        <button class="btn btn-secondary" onclick="rerenderVariant(${i})">Re-render this preview</button>
      </div>
    </div>
  `;
}

function escapeAttr(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

function escapeHtml(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderAllVariantCards() {
  document.getElementById("preview-meta").textContent =
    lastResult.variants.length > 1
      ? `Email type: ${lastResult.email_type} — Invite → Reminder → Deadline sequence (3 emails)`
      : `Email type: ${lastResult.email_type}`;

  document.getElementById("variant-cards").innerHTML = lastResult.variants
    .map((v, i) => variantCardHtml(v, i))
    .join("");

  const approveBtn = document.getElementById("approve-btn");
  approveBtn.disabled = false;
  approveBtn.textContent =
    lastResult.variants.length > 1 ? "Approve & create 3 HubSpot drafts" : "Approve & create HubSpot draft";
  setStatus("approve-status", "", "info");
  document.getElementById("approve-results").classList.add("hidden");
  document.getElementById("approve-results").innerHTML = "";
}

function syncEditsToVariant(i) {
  const v = lastResult.variants[i];
  v.subject = document.getElementById(`edit_subject-${i}`).value;
  v.preview_text = document.getElementById(`edit_preview_text-${i}`).value;
  v.hero_headline = document.getElementById(`edit_hero_headline-${i}`).value;
  v.body_paragraphs = document.getElementById(`edit_body-${i}`).value
    .split("\n").map(s => s.trim()).filter(Boolean);
  v.impact_sentence = document.getElementById(`edit_impact_sentence-${i}`).value;
  const shareEl = document.getElementById(`edit_share_line-${i}`);
  if (shareEl) v.share_line = shareEl.value;
}

async function rerenderVariant(i) {
  syncEditsToVariant(i);
  const variant = lastResult.variants[i];

  const res = await fetch("/api/rerender-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email_type: lastResult.email_type,
      promoted_url: document.getElementById("promoted_url").value.trim(),
      hero_image_id: heroImageId,
      variant,
    }),
  });
  const data = await res.json();
  variant.html = data.html;
  document.getElementById(`preview-frame-${i}`).srcdoc = variant.html;
}

async function approvePreview() {
  if (!lastResult || approved) return;
  lastResult.variants.forEach((_, i) => syncEditsToVariant(i));

  const btn = document.getElementById("approve-btn");
  btn.disabled = true;
  setStatus(
    "approve-status",
    lastResult.variants.length > 1
      ? "Cloning the latest matching HubSpot email and applying your copy to all 3 drafts…"
      : "Cloning the latest matching HubSpot email and applying your copy…",
    "info"
  );

  try {
    const res = await fetch("/api/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email_type: lastResult.email_type,
        promoted_url: document.getElementById("promoted_url").value.trim(),
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
      "approve-status",
      `${data.results.length > 1 ? "Drafts" : "Draft"} created in HubSpot (cloned from "${data.results[0].cloned_from_name}").${hasWarnings ? " See warning below." : ` Open ${data.results.length > 1 ? "them" : "it"} below:`}`,
      hasWarnings ? "error" : "success"
    );

    const resultsEl = document.getElementById("approve-results");
    resultsEl.classList.remove("hidden");
    const warningsHtml = (data.warnings || [])
      .map(w => `<div class="status-error" style="margin-bottom:8px">${escapeHtml(w)}</div>`)
      .join("");
    const linksHtml = data.results
      .map(r => {
        const label = STAGE_LABELS[r.stage] || r.stage;
        return `<a class="approve-result-link" href="${r.draft_url}" target="_blank" rel="noopener">Open "${label}" draft in HubSpot →</a>`;
      })
      .join("");
    resultsEl.innerHTML = warningsHtml + linksHtml;
    document.getElementById("email-preview-next-btn").disabled = false;
    unlockUpTo(2);
  } catch (e) {
    btn.disabled = false;
    setStatus("approve-status", e.message, "error");
  }
}

// --- Audience Preview (custom audience builder) ---

async function planAudience() {
  const description = document.getElementById("audience_description").value.trim();
  if (!description) {
    setStatus("audience-plan-status", "Describe the audience you need first.", "error");
    return;
  }

  // If a plan is already on screen, sync any user edits into the qa context so
  // a re-propose call incorporates them instead of starting over.
  if (lastAudiencePlan) syncAudienceEditsToPlan();

  const btn = document.getElementById("audience-plan-btn");
  btn.disabled = true;
  setStatus("audience-plan-status", "Proposing segment logic…", "info");

  try {
    const res = await fetch("/api/audience/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description, qa: audienceQA }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();
    lastAudiencePlan = data.plan;
    audienceBuilt = false;
    document.getElementById("audience-preview-next-btn").disabled = !audienceStepComplete;
    renderAudiencePlan();
    setStatus("audience-plan-status", "", "info");
  } catch (e) {
    setStatus("audience-plan-status", e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

function renderAudiencePlan() {
  const plan = lastAudiencePlan;
  document.getElementById("audience-plan-card").classList.remove("hidden");
  document.getElementById("audience-plan-summary").textContent = plan.plan_summary || "";

  document.getElementById("audience_list_name").value = plan.list_name || "";
  document.getElementById("audience_locations").value = (plan.locations || [])
    .map(l => l.country ? `${l.city}, ${l.country}` : l.city).join("\n");
  document.getElementById("audience_named_events").value = (plan.named_events || []).join("\n");
  document.getElementById("audience_apply_suppression").checked = !!plan.apply_suppression;
  document.getElementById("audience_suppression_terms").value = (plan.suppression_search_terms || []).join("\n");

  const qEl = document.getElementById("audience-questions");
  const questions = plan.open_questions || [];
  if (questions.length) {
    qEl.classList.remove("hidden");
    qEl.innerHTML = `<div class="card-desc" style="margin-top:0">This blocks building — answer below, then click "Re-propose with edits":</div>` +
      questions.map((q, i) => `
        <div class="field">
          <label>${escapeHtml(q.question)}</label>
          ${q.why_it_blocks ? `<div class="card-desc" style="margin:2px 0 6px">${escapeHtml(q.why_it_blocks)}</div>` : ""}
          <div class="btn-row" style="flex-wrap:wrap">
            ${(q.options || []).map(opt => `<button type="button" class="btn btn-secondary" onclick="answerAudienceQuestion(${i}, ${JSON.stringify(opt).replace(/"/g, "&quot;")})">${escapeHtml(opt)}</button>`).join("")}
          </div>
        </div>
      `).join("");
  } else {
    qEl.classList.add("hidden");
    qEl.innerHTML = "";
  }

  document.getElementById("audience-build-btn").disabled = questions.length > 0;
  document.getElementById("audience-build-status").classList.add("hidden");
  document.getElementById("audience-build-results").classList.add("hidden");
  document.getElementById("audience-build-results").innerHTML = "";
}

function answerAudienceQuestion(i, answer) {
  const plan = lastAudiencePlan;
  const q = (plan.open_questions || [])[i];
  if (!q) return;
  audienceQA += `Q: ${q.question}\nA: ${answer}\n`;
  planAudience();
}

function syncAudienceEditsToPlan() {
  const plan = lastAudiencePlan;
  plan.list_name = document.getElementById("audience_list_name").value;
  plan.locations = document.getElementById("audience_locations").value
    .split("\n").map(s => s.trim()).filter(Boolean)
    .map(line => {
      const [city, country] = line.split(",").map(s => (s || "").trim());
      return { city, country: country || "" };
    });
  plan.named_events = document.getElementById("audience_named_events").value
    .split("\n").map(s => s.trim()).filter(Boolean);
  plan.apply_suppression = document.getElementById("audience_apply_suppression").checked;
  plan.suppression_search_terms = document.getElementById("audience_suppression_terms").value
    .split("\n").map(s => s.trim()).filter(Boolean);
}

async function buildAudience() {
  if (!lastAudiencePlan || audienceBuilt) return;
  syncAudienceEditsToPlan();

  const btn = document.getElementById("audience-build-btn");
  btn.disabled = true;
  setStatus("audience-build-status", "Creating list(s) in HubSpot…", "info");

  try {
    const res = await fetch("/api/audience/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: lastAudiencePlan }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Build failed (${res.status})`);
    }
    const data = await res.json();
    audienceBuilt = true;
    audienceStepComplete = true;
    selectedListId = data.master_list.list_id;
    btn.textContent = "List(s) created";
    setStatus("audience-build-status", "Created in HubSpot. Open below:", "success");

    const links = [
      `<a class="approve-result-link" href="${data.master_list.url}" target="_blank" rel="noopener">Open master list "${escapeHtml(data.master_list.name)}" →</a>`,
    ];
    if (data.suppression_list) {
      links.push(`<a class="approve-result-link" href="${data.suppression_list.url}" target="_blank" rel="noopener">Open suppression list "${escapeHtml(data.suppression_list.name)}" →</a>`);
    }
    const resultsEl = document.getElementById("audience-build-results");
    resultsEl.classList.remove("hidden");
    resultsEl.innerHTML = links.join("");
    document.getElementById("audience-preview-next-btn").disabled = false;
    unlockUpTo(3);
  } catch (e) {
    btn.disabled = false;
    setStatus("audience-build-status", e.message, "error");
  }
}

// ── Use Existing List — searchable HubSpot list picker ──────────────────────
// Selecting a result here skips discovery/composition entirely: the chosen
// list becomes the send list directly, same as buildAudience() completing.

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
      const res = await fetch(`/api/audience-builder/lists/search?q=${encodeURIComponent(query)}`);
      const data = await res.json();
      const results = data.results || [];
      if (!results.length) {
        dropdown.innerHTML = `<div class="list-dropdown-item" style="color:#999">No lists found</div>`;
      } else {
        dropdown.innerHTML = results.map(l => `
          <div class="list-dropdown-item" onclick="selectExistingList(${JSON.stringify(String(l.listId)).replace(/"/g, "&quot;")}, ${JSON.stringify(l.name || "").replace(/"/g, "&quot;")}, ${l.size ?? "null"})">
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
  selectedListId = String(id);
  document.getElementById("send_list_id").value = id;
  const inp = document.getElementById("list-search-input");
  if (inp) inp.value = "";
  document.getElementById("list-dropdown").classList.add("hidden");

  const sel = document.getElementById("list-selected");
  sel.innerHTML = `
    <span>✓ <strong>${escapeHtml(name)}</strong></span>
    <span style="color:#777;font-size:12px">${size ? Number(size).toLocaleString() + " contacts" : ""}</span>
    <span class="list-clear" onclick="clearExistingList()" title="Remove">×</span>`;
  sel.classList.remove("hidden");

  audienceStepComplete = true;
  document.getElementById("audience-preview-next-btn").disabled = false;
  unlockUpTo(3);
}

function clearExistingList() {
  if (selectedListId === document.getElementById("send_list_id").value) selectedListId = "";
  document.getElementById("send_list_id").value = "";
  const inp = document.getElementById("list-search-input");
  if (inp) inp.value = "";
  document.getElementById("list-selected").classList.add("hidden");
}

document.addEventListener("click", (e) => {
  if (!e.target.closest(".list-picker")) {
    const d = document.getElementById("list-dropdown");
    if (d) d.classList.add("hidden");
  }
});

// --- Implementation ---

function stageEmailId(stage) {
  const r = (approvedResults || []).find(x => x.stage === stage);
  return r ? r.email_id : "";
}

function renderImplementationPanel() {
  const el = document.getElementById("implementation-content");
  const isSequence = lastResult && lastResult.email_plan === "sequence";

  if (!isSequence) {
    const emailId = stageEmailId("single");
    el.innerHTML = `
      <div class="card">
        <div class="card-title">Schedule the send</div>
        <div class="card-desc" style="margin-top:0">
          Pick the date and time you plan to send this email. Clicking below attaches your
          selected audience list to the draft as its send-to list — it does <strong>not</strong>
          schedule or activate anything in HubSpot. You still need to open the draft in HubSpot
          and schedule/send it yourself for the date and time you pick.
        </div>
        <div class="field-row">
          <div class="field"><label>Send date</label><input id="impl-single-date" type="date" /></div>
          <div class="field"><label>Send time</label><input id="impl-single-time" type="time" value="09:00" /></div>
        </div>
        <div id="impl-single-status" class="hidden"></div>
        <div class="btn-row">
          <button class="btn btn-primary" id="impl-single-btn" onclick="submitImplementationSingle('${emailId}')">Attach audience list</button>
        </div>
        <div id="impl-single-results" class="hidden"></div>
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
        <div class="field"><label>1. Invite — send date</label><input id="impl-invite-date" type="date" /></div>
        <div class="field"><label>Invite — send time</label><input id="impl-invite-time" type="time" value="09:00" /></div>
      </div>
      <div class="field-row">
        <div class="field"><label>2. Reminder — send date</label><input id="impl-reminder-date" type="date" /></div>
        <div class="field"><label>Reminder — send time</label><input id="impl-reminder-time" type="time" value="10:00" /></div>
      </div>
      <div class="field-row">
        <div class="field"><label>3. Deadline — send date</label><input id="impl-deadline-date" type="date" /></div>
        <div class="field"><label>Deadline — send time</label><input id="impl-deadline-time" type="time" value="09:00" /></div>
      </div>

      <div id="impl-sequence-status" class="hidden"></div>
      <div class="btn-row">
        <button class="btn btn-primary" id="impl-sequence-btn"
          onclick="submitImplementationSequence('${inviteId}', '${reminderId}', '${deadlineId}')">
          Build sequence workflow (disabled)
        </button>
      </div>
      <div id="impl-sequence-results" class="hidden"></div>
    </div>`;
}

async function submitImplementationSingle(emailId) {
  const listId = selectedListId || document.getElementById("send_list_id").value || "";
  const date = document.getElementById("impl-single-date").value;
  const time = document.getElementById("impl-single-time").value;

  if (!emailId) { setStatus("impl-single-status", "No approved email found — go back and approve a draft first.", "error"); return; }
  if (!listId) { setStatus("impl-single-status", "No audience list selected — go back and pick or build one first.", "error"); return; }
  if (!date || !time) { setStatus("impl-single-status", "Pick a send date and time.", "error"); return; }

  const btn = document.getElementById("impl-single-btn");
  btn.disabled = true;
  setStatus("impl-single-status", "Attaching audience list to the draft…", "info");
  try {
    const res = await fetch("/api/implementation/single", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email_id: emailId, list_id: listId, send_date: date, send_time: time }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();
    btn.textContent = "List attached";
    setStatus(
      "impl-single-status",
      "Audience list attached. Nothing was scheduled — open the draft below and schedule it yourself for the date/time you picked.",
      "success"
    );
    const resultsEl = document.getElementById("impl-single-results");
    resultsEl.classList.remove("hidden");
    resultsEl.innerHTML = `<a class="approve-result-link" href="${data.draft_url}" target="_blank" rel="noopener">Open draft in HubSpot to schedule for ${escapeHtml(data.send_date)} ${escapeHtml(data.send_time)} →</a>`;
  } catch (e) {
    btn.disabled = false;
    setStatus("impl-single-status", e.message, "error");
  }
}

async function submitImplementationSequence(inviteId, reminderId, deadlineId) {
  const listId = selectedListId || document.getElementById("send_list_id").value || "";
  const invite = { date: document.getElementById("impl-invite-date").value, time: document.getElementById("impl-invite-time").value };
  const reminder = { date: document.getElementById("impl-reminder-date").value, time: document.getElementById("impl-reminder-time").value };
  const deadline = { date: document.getElementById("impl-deadline-date").value, time: document.getElementById("impl-deadline-time").value };

  if (!inviteId || !reminderId || !deadlineId) {
    setStatus("impl-sequence-status", "Missing one of the 3 approved emails — go back and approve all 3 drafts first.", "error");
    return;
  }
  if (!listId) { setStatus("impl-sequence-status", "No audience list selected — go back and pick or build one first.", "error"); return; }
  if (!invite.date || !invite.time || !reminder.date || !reminder.time || !deadline.date || !deadline.time) {
    setStatus("impl-sequence-status", "Pick a date and time for all 3 emails.", "error");
    return;
  }

  const btn = document.getElementById("impl-sequence-btn");
  btn.disabled = true;
  setStatus("impl-sequence-status", "Cloning the sequence workflow with your emails, dates, and list (disabled)…", "info");
  try {
    const res = await fetch("/api/implementation/sequence", {
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
      "impl-sequence-status",
      "Sequence workflow cloned with your 3 emails, dates, and audience list — disabled. Nothing was activated. Open it below to review and turn it on when ready.",
      "success"
    );
    const resultsEl = document.getElementById("impl-sequence-results");
    resultsEl.classList.remove("hidden");
    resultsEl.innerHTML = `
      <a class="approve-result-link" href="${data.invite_draft_url}" target="_blank" rel="noopener">Open invite draft (sent by the workflow) →</a>
      <a class="approve-result-link" href="${data.workflow_url}" target="_blank" rel="noopener">Open cloned workflow (disabled) to review &amp; enable →</a>`;
  } catch (e) {
    btn.disabled = false;
    setStatus("impl-sequence-status", e.message, "error");
  }
}
