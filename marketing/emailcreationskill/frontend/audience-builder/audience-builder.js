// ── Audience Builder: existing-list discovery + master-list composer ──
// Uses globals defined in app.js (API, setLoading, clearStatus, showError,
// escapeHtml, clearAudienceQuestions, runDirectSignalBuild, _markMaster,
// _masterListId) — this file is loaded after app.js.
//
// Dual-hosted in two screens via a `scope` param on every public function,
// mirroring the _AUD_UI_SCOPES pattern app.js already uses for "Build From
// Scratch": "builder" = the standalone Audience Builder tab (default, so
// every existing onclick="AudienceBuilder.xyz()" call site with no scope arg
// keeps its exact original ids/behavior), "step3" = the Campaign Builder
// Step 3 "Reuse or Discover Existing Audience" panel. Each scope gets its own
// DOM-id map (_SCOPES) and its own mutable state bucket (_states), so running
// discovery in one screen never clobbers the other's grid/selection.
const AudienceBuilder = (() => {
  const SIGNAL_LABELS = {
    last_sent: "Used In Past Sends",
    project_opt_in: "Project Opt-In",
    lf_newsletter_opt_in: "LF Newsletter Opt-In",
    event_registration: "Event Registration",
    education_enrollment: "Education Enrollment",
    page_view: "Page View",
    event_speakers: "Event Speakers",
    uncertain: "Uncertain",
    added: "Manually Added",
  };

  // Every prompt below ends with the same explicit no-suppression instruction:
  // these are single-signal inclusion lists built one at a time from the
  // Discover/Reuse "Qualifying Lists Not Found" panel, not the final send
  // audience. Suppressions must be applied exactly once, later, on the master
  // list that combines these — never baked into an individual signal list here.
  const _NO_SUPPRESSION_NOTE = " This is a single inclusion list for one signal only — it will be combined into a master audience later. Do not add any suppression filters or a Combined Suppression list to it; suppressions apply only at the master-list level.";

  const SIGNAL_INFO = {
    project_opt_in: {
      label: "Project Opt-In",
      description: "Contacts opted into this project's own email subscription type (not the general LF newsletter).",
      prompt: (eventUrl) => `Build a list of contacts opted into this project's own email subscription type (project-specific opt-in, not the general Linux Foundation newsletter) for the event at ${eventUrl}.${_NO_SUPPRESSION_NOTE}`,
    },
    lf_newsletter_opt_in: {
      label: "LF Newsletter Opt-In",
      description: "Contacts opted into the Linux Foundation Newsletter subscription type.",
      prompt: (eventUrl) => `Build a list of contacts opted into the Linux Foundation Newsletter subscription type, relevant to the event at ${eventUrl}.${_NO_SUPPRESSION_NOTE}`,
    },
    event_registration: {
      label: "Event Registration",
      description: "All-time registrants for this event, across all past editions.",
      prompt: (eventUrl) => `Build a list of all-time registrants (all editions) for the event at ${eventUrl}.${_NO_SUPPRESSION_NOTE}`,
    },
    education_enrollment: {
      label: "Education Enrollment",
      description: "Contacts enrolled in LFX Education courses related to this event's topic area.",
      prompt: (eventUrl) => `Build a list of contacts enrolled in LFX Education courses related to the topic area of the event at ${eventUrl}.${_NO_SUPPRESSION_NOTE}`,
    },
    page_view: {
      label: "Page View",
      description: "Contacts who viewed this event's page (page-view based segment).",
      prompt: (eventUrl) => `Build a page-view based list of contacts who viewed the event page at ${eventUrl}.${_NO_SUPPRESSION_NOTE}`,
    },
    event_speakers: {
      label: "Event Speakers",
      description: "Contacts who are speakers for this event specifically, not all registrants.",
      prompt: (eventUrl) => `Build a list of contacts who are speakers (not general registrants) for the event at ${eventUrl}.${_NO_SUPPRESSION_NOTE}`,
    },
  };

  // Section-grouping order + per-section accent/caption — mirrors the
  // layered "Layer 1 / Layer 2 / Layer 3" grouping from the audience-engine
  // reference, applied over our own 5-signal taxonomy instead of its
  // lookalike/intent/profile-fit buckets.
  const SIGNAL_ORDER = [
    "last_sent",
    "event_registration",
    "event_speakers",
    "project_opt_in",
    "lf_newsletter_opt_in",
    "education_enrollment",
    "page_view",
    "uncertain",
    "added",
  ];
  const SIGNAL_DESC = {
    last_sent: "Used in a past send for this event but not classified under the 5 signals below",
    project_opt_in: "Opted into this project's own subscription type",
    lf_newsletter_opt_in: "Opted into the Linux Foundation newsletter",
    event_registration: "All-time registrants for this event",
    education_enrollment: "Enrolled in related education content",
    page_view: "Viewed this event's page",
    event_speakers: "Speakers for this event specifically",
    uncertain: "Needs manual review before including",
    added: "Manually added via search",
  };
  const SIGNAL_ACCENT = {
    last_sent: "var(--blue-dark)",
    project_opt_in: "var(--blue)",
    lf_newsletter_opt_in: "#6d28d9",
    event_registration: "#166534",
    education_enrollment: "var(--yellow)",
    page_view: "#be185d",
    event_speakers: "#c2410c",
    uncertain: "var(--gray-400)",
    added: "var(--gray-500)",
  };

  // DOM-id map per scope. "builder" ids are exactly the original standalone-tab
  // ids (unchanged). "step3" ids point at the parallel markup added to Step 3's
  // "Reuse or Discover Existing Audience" panel, except customRequest/
  // customTicker/customStatusBadge which intentionally point at Step 3's
  // existing "Custom Audience" sub-tab ids (_AUD_UI_SCOPES.step3 in app.js) —
  // "Create list" for a missing signal reuses that tab's full plan-review UI
  // rather than duplicating it a third time.
  const _SCOPES = {
    builder: {
      eventUrl: "ab-event-url",
      discoverBtn: "ab-discover-btn",
      discoverStatus: "ab-discover-status",
      discoverTicker: "ab-discover-ticker",
      existingMasterSection: "ab-existing-master-section",
      existingMasterGrid: "ab-existing-master-grid",
      lastSentSection: "ab-last-sent-section",
      lastSentGrid: "ab-last-sent-grid",
      results: "ab-results",
      statSegments: "ab-stat-segments",
      statContacts: "ab-stat-contacts",
      statContactsTag: "ab-stat-contacts-tag",
      exactCountBtn: "ab-exact-count-btn",
      statSelected: "ab-stat-selected",
      cardSections: "ab-card-sections",
      searchInput: "ab-search-input",
      searchDropdown: "ab-search-dropdown",
      suppressionStatus: "ab-suppression-status",
      suppressionContacts: "ab-suppression-contacts",
      suppressionContactsTag: "ab-suppression-contacts-tag",
      suppressionExactBtn: "ab-suppression-exact-btn",
      suppressionGrid: "ab-suppression-grid",
      buildMasterBtn: "ab-build-master-btn",
      buildStatus: "ab-build-status",
      missingSection: "ab-missing-section",
      missingGrid: "ab-missing-grid",
      customRequest: "ab-custom-request",
      customTicker: "ab-custom-ticker",
    },
    step3: {
      eventUrl: "s3ab-event-url",
      discoverBtn: "s3ab-discover-btn",
      discoverStatus: "s3ab-discover-status",
      discoverTicker: "s3ab-discover-ticker",
      existingMasterSection: "s3ab-existing-master-section",
      existingMasterGrid: "s3ab-existing-master-grid",
      lastSentSection: "s3ab-last-sent-section",
      lastSentGrid: "s3ab-last-sent-grid",
      results: "s3ab-results",
      statSegments: "s3ab-stat-segments",
      statContacts: "s3ab-stat-contacts",
      statContactsTag: "s3ab-stat-contacts-tag",
      exactCountBtn: "s3ab-exact-count-btn",
      statSelected: "s3ab-stat-selected",
      cardSections: "s3ab-card-sections",
      searchInput: "s3ab-search-input",
      searchDropdown: "s3ab-search-dropdown",
      suppressionStatus: "s3ab-suppression-status",
      suppressionContacts: "s3ab-suppression-contacts",
      suppressionContactsTag: "s3ab-suppression-contacts-tag",
      suppressionExactBtn: "s3ab-suppression-exact-btn",
      suppressionGrid: "s3ab-suppression-grid",
      buildMasterBtn: "s3ab-build-master-btn",
      buildStatus: "s3ab-build-status",
      missingSection: "s3ab-missing-section",
      missingGrid: "s3ab-missing-grid",
      customRequest: "custom_audience_request",
      customTicker: "audience-ticker",
    },
  };

  function _ids(scope) { return _SCOPES[scope] || _SCOPES.builder; }

  function _newState() {
    return {
      cards: [],
      selected: new Set(),
      missingSignals: [],
      searchTimer: null,
      discoverES: null,
      pendingMissingSignal: null, // signal key the direct-build request below is for
      buildingSignals: new Set(), // signal keys with a direct build currently in flight
      brandShort: "", // resolved by the discovery agent, reused for suppression/last-sent lookups
      eventName: "",
      // Suppression & Exclusions — standard hygiene lists + this event's current
      // registrants (mapped from the discovered event_registration card, if any),
      // all pre-selected by default. Feeds compose-master's exclude_list_ids.
      suppressionCards: [],
      suppressionSelected: new Set(),
      // "What was sent last time" — up to 3 recent emails for this event, each
      // with the HubSpot lists they used (see backend/audience_builder/last_sent.py).
      lastSent: [],
      // Flattened list_ids across all lastSent entries — drives the "Used last
      // time" card badge and the auto-select-on-discover behavior below.
      lastSentIncludedIds: new Set(),
      lastSentSuppressionIds: new Set(),
      // Master lists already built for this event by an earlier run (see
      // backend/audience_builder/master_list.py: find_existing_master_lists) —
      // purely informational, so the user can check whether one is still
      // current before building a new one.
      existingMasterLists: [],
      // Last direct-build failure for a missing signal, so renderMissingSignals
      // can show it inline on that card instead of relying on the (now hidden,
      // since we stay on this tab) Custom Audience tab's own status badge.
      buildError: null, // { signal, message } | null
    };
  }
  const _states = { builder: _newState(), step3: _newState() };
  function _st(scope) { return _states[scope] || _states.builder; }

  function _sumSelectedSize(cards, selectedSet) {
    const sizeById = new Map(cards.map(c => [String(c.list_id), c.size]));
    let total = 0;
    selectedSet.forEach(id => {
      const s = sizeById.get(id);
      if (typeof s === "number") total += s;
    });
    return total;
  }

  async function _fetchExactCount(ids) {
    const resp = await fetch(`${API}/audience-builder/preview-count`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ list_ids: ids }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || "Failed to get exact count");
    return data;
  }

  function _fmtSentDate(v) {
    if (!v) return "Unknown date";
    const n = Number(v);
    const d = Number.isFinite(n) && String(v).trim() !== "" ? new Date(n) : new Date(v);
    if (isNaN(d.getTime())) return "Unknown date";
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  function _suppressionCardHtml(c, scope, st) {
    const id = String(c.list_id);
    const selected = st.suppressionSelected.has(id);
    const badgeClass = c.badge || "suppression";
    const recommended = c.category === "event_specific"
      ? `<span class="ab-recommended-tag">★ Recommended</span>` : "";
    const usedLastSent = st.lastSentSuppressionIds.has(id)
      ? `<span class="ab-lastsent-badge" title="Suppressed in a past send for this event">📧 Used last time</span>` : "";
    return `
      <div class="ab-card${selected ? " selected" : ""}" onclick="AudienceBuilder.toggleSuppressionCard('${id}','${scope}')">
        <div class="ab-card-top">
          <span class="ab-signal-badge ab-signal-${escapeHtml(badgeClass)}">${escapeHtml(c.label || "Suppression")}</span>
          <span class="ab-card-check"></span>
        </div>
        <div class="ab-card-name">${escapeHtml(c.name || "(untitled list)")}</div>
        <div class="ab-card-meta"><span>ID ${escapeHtml(id)}</span>${recommended}${usedLastSent}</div>
        <div class="ab-stat-row">
          <div class="ab-stat-box">
            <div class="ab-stat-label">Contacts</div>
            <div class="ab-stat-value">${c.size != null ? Number(c.size).toLocaleString() : "—"}</div>
          </div>
        </div>
      </div>`;
  }

  function renderSuppressionCards(scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    const grid = document.getElementById(ids.suppressionGrid);
    if (!grid) return;
    grid.innerHTML = st.suppressionCards.map(c => _suppressionCardHtml(c, scope, st)).join("");

    const totalContacts = _sumSelectedSize(st.suppressionCards, st.suppressionSelected);
    const totalEl = document.getElementById(ids.suppressionContacts);
    if (totalEl) totalEl.textContent = totalContacts ? totalContacts.toLocaleString() : "—";
    const tag = document.getElementById(ids.suppressionContactsTag);
    if (tag) tag.textContent = st.suppressionSelected.size ? "(estimate, may overlap)" : "";
    const exactBtn = document.getElementById(ids.suppressionExactBtn);
    if (exactBtn) { exactBtn.disabled = st.suppressionSelected.size === 0; exactBtn.textContent = "Get exact count"; }
  }

  function toggleSuppressionCard(id, scope = "builder") {
    const st = _st(scope);
    id = String(id);
    if (st.suppressionSelected.has(id)) st.suppressionSelected.delete(id);
    else st.suppressionSelected.add(id);
    renderSuppressionCards(scope);
  }

  async function getSuppressionExactCount(scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    if (!st.suppressionSelected.size) return;
    const btn = document.getElementById(ids.suppressionExactBtn);
    const tag = document.getElementById(ids.suppressionContactsTag);
    if (btn) { btn.disabled = true; btn.textContent = "Calculating…"; }
    try {
      const data = await _fetchExactCount(Array.from(st.suppressionSelected));
      const totalEl = document.getElementById(ids.suppressionContacts);
      if (totalEl) totalEl.textContent = Number(data.count || 0).toLocaleString();
      if (tag) tag.textContent = data.exact ? "(exact)" : `(estimate — ${data.reason || "too large for exact"})`;
    } catch (e) {
      if (tag) tag.textContent = "(failed)";
    } finally {
      if (btn) { btn.disabled = st.suppressionSelected.size === 0; btn.textContent = "Get exact count"; }
    }
  }

  async function loadSuppressionLists(scope = "builder") {
    const st = _st(scope);
    st.suppressionCards = [];
    st.suppressionSelected = new Set();

    // Current Registrants — reuse whatever Event Registration list(s)
    // discovery already found for this event; suppressing on it prevents
    // re-inviting people who already registered.
    st.cards.filter(c => c.signal === "event_registration").forEach(c => {
      const id = String(c.list_id);
      st.suppressionCards.push({
        list_id: id,
        name: c.name,
        label: "Current Registrants",
        badge: "current_registrants",
        category: "current_registrants",
        size: c.size,
      });
      st.suppressionSelected.add(id);
    });

    try {
      const params = new URLSearchParams({ brand_short: st.brandShort || "", event_name: st.eventName || "" });
      const resp = await fetch(`${API}/audience-builder/suppression-lists?${params}`);
      if (resp.ok) {
        const data = await resp.json();
        (data.results || []).forEach(r => {
          const id = String(r.list_id);
          const category = r.category || "standard";
          st.suppressionCards.push({
            list_id: id,
            name: r.name,
            label: r.label,
            badge: category === "event_specific" ? "event_specific" : category === "brand" ? "brand" : "suppression",
            category,
            size: r.size,
          });
          st.suppressionSelected.add(id);
        });
      }
    } catch (_) {
      // Non-fatal — standard suppressions just won't be pre-populated; the
      // user can still build the master list with only Current Registrants
      // (or none) suppressed.
    }

    // Surface the most relevant suppressions first — an existing per-event
    // suppression list (if found) is the strongest signal, then brand-scoped
    // opt-outs, then current registrants, then the generic portfolio-wide terms.
    const rank = { event_specific: 0, brand: 1, current_registrants: 2, standard: 3 };
    st.suppressionCards.sort((a, b) => (rank[a.category] ?? 9) - (rank[b.category] ?? 9));

    renderSuppressionCards(scope);
  }

  function _cardHtml(c, scope, st) {
    const id = String(c.list_id);
    const selected = st.selected.has(id);
    const usedLastSent = st.lastSentIncludedIds.has(id)
      ? `<span class="ab-lastsent-badge" title="Used in a past send for this event">📧 Used last time</span>` : "";
    const newBadge = c.justCreated
      ? `<span class="ab-newlycreated-badge" title="Built just now in this session">✨ Newly created</span>` : "";
    const stats = [
      { label: "Contacts", value: c.size != null ? Number(c.size).toLocaleString() : "—" },
    ];
    if (c.list_type) stats.push({ label: "List type", value: c.list_type });
    const statsHtml = stats.map(s => `
      <div class="ab-stat-box">
        <div class="ab-stat-label">${escapeHtml(s.label)}</div>
        <div class="ab-stat-value">${escapeHtml(String(s.value))}</div>
      </div>`).join("");
    const hubspotLink = c.hubspot_url
      ? `<a class="ab-hubspot-link" href="${escapeHtml(c.hubspot_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">View in HubSpot ↗</a>` : "";
    return `
      <div class="ab-card${selected ? " selected" : ""}${c.justCreated ? " ab-card-new" : ""}" onclick="AudienceBuilder.toggleCard('${id}','${scope}')">
        <div class="ab-card-top">
          <span class="ab-card-check"></span>
          ${newBadge}
        </div>
        <div class="ab-card-name">${escapeHtml(c.name || "(untitled list)")}</div>
        <div class="ab-card-meta"><span>ID ${escapeHtml(id)}</span>${usedLastSent}</div>
        <div class="ab-stat-row">${statsHtml}</div>
        ${c.reason ? `<div class="ab-card-reason">${escapeHtml(c.reason)}</div>` : ""}
        ${hubspotLink}
      </div>`;
  }

  function renderCards(scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    const container = document.getElementById(ids.cardSections);
    if (!container) return;

    const bySignal = new Map();
    st.cards.forEach(c => {
      const sig = c.signal || "uncertain";
      if (!bySignal.has(sig)) bySignal.set(sig, []);
      bySignal.get(sig).push(c);
    });

    container.innerHTML = SIGNAL_ORDER.filter(sig => bySignal.has(sig)).map(sig => {
      const group = bySignal.get(sig);
      const cardsHtml = group.map(c => _cardHtml(c, scope, st)).join("");
      const accent = SIGNAL_ACCENT[sig] || "var(--gray-300)";
      return `
        <div class="ab-section">
          <div class="ab-section-header" style="border-left-color:${accent}">
            <span class="ab-section-title">${escapeHtml(SIGNAL_LABELS[sig] || sig)}</span>
            <span class="ab-section-count">${group.length} list${group.length === 1 ? "" : "s"}</span>
            <span class="ab-section-desc">${escapeHtml(SIGNAL_DESC[sig] || "")}</span>
          </div>
          <div class="ab-card-grid">${cardsHtml}</div>
        </div>`;
    }).join("");

    updateSummary(scope);
  }

  function renderMissingSignals(missing, scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    st.missingSignals = missing || [];
    const section = document.getElementById(ids.missingSection);
    const grid = document.getElementById(ids.missingGrid);
    if (!section || !grid) return;
    if (!st.missingSignals.length) {
      section.classList.add("hidden");
      grid.innerHTML = "";
      return;
    }
    grid.innerHTML = st.missingSignals.map(sig => {
      const info = SIGNAL_INFO[sig] || { label: sig, description: "" };
      const building = st.buildingSignals.has(sig);
      const errorHtml = (st.buildError && st.buildError.signal === sig)
        ? `<div class="ab-card-reason" style="border-top:none;padding-top:0;margin-top:6px;color:#dc2626">⚠ ${escapeHtml(st.buildError.message)}</div>` : "";
      return `
        <div class="ab-card ab-card-missing">
          <div class="ab-card-top">
            <span class="ab-signal-badge ab-signal-${escapeHtml(sig)}">${escapeHtml(info.label)}</span>
          </div>
          <div class="ab-card-reason" style="border-top:none;padding-top:0;margin-top:0">${escapeHtml(info.description)}</div>
          ${errorHtml}
          <div class="btn-row" style="margin-top:10px">
            <button class="btn btn-outline" type="button" ${building ? "disabled" : ""} onclick="AudienceBuilder.createMissingSignal('${sig}','${scope}')">${building ? "Building…" : "Create list"}</button>
          </div>
        </div>`;
    }).join("");
    section.classList.remove("hidden");
  }

  // These 5 signals each resolve to one deterministic filter shape (a custom
  // event, a contact property, or a subscription-type property) — so "Create
  // list" skips the plan-generation/review step entirely and calls
  // runDirectSignalBuild() (app.js) to build straight from a pre-set request,
  // via /api/audience/custom-run with an empty plan (chains planning+building
  // in one job, no approval gate). Deliberately stays on THIS tab throughout —
  // the request textarea is filled behind the scenes so runDirectSignalBuild
  // has something to send, but we never switch to the Custom Audience sub-tab;
  // progress/result surface inline on the missing-signal card itself (via
  // renderMissingSignals' "Building…" state and onCustomListBuilt/
  // onCustomBuildFailed below).
  async function createMissingSignal(signalKey, scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    const info = SIGNAL_INFO[signalKey];
    if (!info || st.buildingSignals.has(signalKey)) return;
    st.pendingMissingSignal = signalKey;
    st.buildingSignals.add(signalKey);
    if (st.buildError && st.buildError.signal === signalKey) st.buildError = null;
    renderMissingSignals(st.missingSignals, scope);

    const urlInput = document.getElementById(ids.eventUrl);
    const eventUrl = ((urlInput && urlInput.value) || "").trim();
    const request = info.prompt(eventUrl);
    const textarea = document.getElementById(ids.customRequest);
    if (textarea) textarea.value = request;

    if (typeof runDirectSignalBuild === "function") {
      await runDirectSignalBuild(request, scope);
    }
  }

  // Called by app.js's runDirectSignalBuild() (scope="builder"/"step3" only)
  // once a directly-built list finishes. Folds the new list straight into the
  // discovery grid — selected, under its signal, flagged justCreated so
  // _cardHtml can highlight it and link out to HubSpot — instead of leaving it
  // stranded only in the Build From Scratch result panel. Returns the signal
  // key it attached to, or null if this build wasn't for a missing signal (so
  // app.js's confirmation message can vary accordingly).
  function onCustomListBuilt({ list_id, name, hubspot_url }, scope = "builder") {
    const st = _st(scope);
    const signal = st.pendingMissingSignal;
    st.pendingMissingSignal = null;
    if (!signal) return null;
    st.buildingSignals.delete(signal);

    const id = String(list_id);
    if (!st.cards.some(c => String(c.list_id) === id)) {
      st.cards.push({
        list_id: id,
        name: name || `List ${id}`,
        signal,
        size: null,
        reason: "Created via Build From Scratch",
        hubspot_url: hubspot_url || "",
        justCreated: true,
      });
    }
    st.selected.add(id);
    renderMissingSignals(st.missingSignals.filter(s => s !== signal), scope);
    const results = document.getElementById(_ids(scope).results);
    if (results) results.classList.remove("hidden");
    renderCards(scope);
    if (signal === "event_registration") loadSuppressionLists(scope);
    return signal;
  }

  // Called by app.js's runDirectSignalBuild() when a direct build fails —
  // clears the in-flight state so the missing-signal card's button resets to
  // "Create list" instead of staying stuck on "Building…", and surfaces the
  // failure reason inline on that card (we no longer switch to the Custom
  // Audience tab, whose own status badge would otherwise have shown this).
  function onCustomBuildFailed(scope = "builder", message = "") {
    const st = _st(scope);
    const signal = st.pendingMissingSignal;
    st.pendingMissingSignal = null;
    if (signal) {
      st.buildingSignals.delete(signal);
      st.buildError = { signal, message: message || "Build failed — see Custom Audience log" };
    }
    renderMissingSignals(st.missingSignals, scope);
  }

  function updateSummary(scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    const segEl = document.getElementById(ids.statSegments);
    if (segEl) segEl.textContent = String(st.cards.length);

    const totalContacts = _sumSelectedSize(st.cards, st.selected);
    const totalEl = document.getElementById(ids.statContacts);
    if (totalEl) totalEl.textContent = totalContacts ? totalContacts.toLocaleString() : "—";
    const tag = document.getElementById(ids.statContactsTag);
    if (tag) tag.textContent = st.selected.size ? "(estimate, may overlap)" : "";

    const selEl = document.getElementById(ids.statSelected);
    if (selEl) selEl.textContent = String(st.selected.size);

    const buildBtn = document.getElementById(ids.buildMasterBtn);
    if (buildBtn) buildBtn.disabled = st.selected.size === 0;
    const exactBtn = document.getElementById(ids.exactCountBtn);
    if (exactBtn) { exactBtn.disabled = st.selected.size === 0; exactBtn.textContent = "Get exact count"; }
  }

  async function getExactCount(scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    if (!st.selected.size) return;
    const btn = document.getElementById(ids.exactCountBtn);
    const tag = document.getElementById(ids.statContactsTag);
    if (btn) { btn.disabled = true; btn.textContent = "Calculating…"; }
    try {
      const data = await _fetchExactCount(Array.from(st.selected));
      const totalEl = document.getElementById(ids.statContacts);
      if (totalEl) totalEl.textContent = Number(data.count || 0).toLocaleString();
      if (tag) tag.textContent = data.exact ? "(exact)" : `(estimate — ${data.reason || "too large for exact"})`;
    } catch (e) {
      if (tag) tag.textContent = "(failed)";
    } finally {
      if (btn) { btn.disabled = st.selected.size === 0; btn.textContent = "Get exact count"; }
    }
  }

  function _lastSentCardHtml(e, idx, scope) {
    const included = (e.included_lists || [])
      .map(l => `${escapeHtml(l.name)}${l.size != null ? ` (${Number(l.size).toLocaleString()})` : ""}`)
      .join(", ") || "—";
    const suppressed = (e.suppression_lists || [])
      .map(l => `${escapeHtml(l.name)}${l.size != null ? ` (${Number(l.size).toLocaleString()})` : ""}`)
      .join(", ") || "—";
    return `
      <div class="ab-last-sent-card">
        <div class="ab-last-sent-top">
          <div class="ab-last-sent-name">${escapeHtml(e.email_name || "(untitled email)")}</div>
          <div class="ab-last-sent-date">${escapeHtml(_fmtSentDate(e.sent_at))}</div>
        </div>
        <div class="ab-last-sent-row"><span class="ab-last-sent-label">Sent to:</span> ${included}</div>
        <div class="ab-last-sent-row"><span class="ab-last-sent-label">Suppressed:</span> ${suppressed}</div>
        <div class="btn-row" style="margin-top:8px">
          ${e.hubspot_url ? `<a class="btn btn-outline" href="${escapeHtml(e.hubspot_url)}" target="_blank" rel="noopener">View in HubSpot</a>` : ""}
          <button class="btn btn-primary" type="button" onclick="AudienceBuilder.useLastSentSelection(${idx},'${scope}')">Use same selection</button>
        </div>
      </div>`;
  }

  function renderLastSent(scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    const section = document.getElementById(ids.lastSentSection);
    const grid = document.getElementById(ids.lastSentGrid);
    if (!section || !grid) return;
    if (!st.lastSent.length) {
      section.classList.add("hidden");
      grid.innerHTML = "";
      return;
    }
    grid.innerHTML = st.lastSent.map((e, i) => _lastSentCardHtml(e, i, scope)).join("");
    section.classList.remove("hidden");
  }

  async function loadLastSent(eventName, brandShort, scope = "builder") {
    const st = _st(scope);
    st.lastSent = [];
    st.lastSentIncludedIds = new Set();
    st.lastSentSuppressionIds = new Set();
    renderLastSent(scope);
    if (!eventName && !brandShort) return;
    try {
      const params = new URLSearchParams({ event_name: eventName || "", brand_short: brandShort || "" });
      const resp = await fetch(`${API}/audience-builder/last-sent?${params}`);
      if (!resp.ok) return;
      const data = await resp.json();
      st.lastSent = data.results || [];
      const includedBrief = new Map(); // list_id -> {name, size} from the first send that used it
      st.lastSent.forEach(e => {
        (e.included_lists || []).forEach(l => {
          const id = String(l.list_id);
          st.lastSentIncludedIds.add(id);
          if (!includedBrief.has(id)) includedBrief.set(id, l);
        });
        (e.suppression_lists || []).forEach(l => st.lastSentSuppressionIds.add(String(l.list_id)));
      });

      // Auto-select discovered cards that match a list used in a past send —
      // these "common" lists shouldn't require a manual "Use same selection"
      // click. Suppression cards are already all pre-selected by default
      // (loadSuppressionLists), so only the inclusion side needs this.
      st.cards.forEach(c => {
        if (st.lastSentIncludedIds.has(String(c.list_id))) st.selected.add(String(c.list_id));
      });

      // A past-send inclusion list often doesn't fit any of the 5 discovery
      // signals (e.g. a regional/demographic segment) and so never becomes a
      // card at all — that left it selectable only via a manual "Use same
      // selection" click. Synthesize a card for it too, under its own
      // "Used In Past Sends" section, so it's never silently missing from the
      // buildable grid.
      includedBrief.forEach((l, id) => {
        // Dead list reference (see last_sent.py's missing:True) — nothing to
        // build from, so don't surface it as a selectable/buildable card.
        if (l.missing) return;
        if (!st.cards.some(c => String(c.list_id) === id)) {
          st.cards.push({
            list_id: id, name: l.name, signal: "last_sent", size: l.size,
            reason: "Used in a past send for this event; not classified under the 5 signals above.",
          });
        }
        st.selected.add(id);
      });

      renderLastSent(scope);
      renderCards(scope);
      renderSuppressionCards(scope);
    } catch (_) {
      // Non-fatal — the panel just stays empty; last-sent is a convenience
      // surface, not required to build a master list.
    }
  }

  function _existingMasterCardHtml(m) {
    return `
      <div class="ab-last-sent-card">
        <div class="ab-last-sent-top">
          <div class="ab-last-sent-name">${escapeHtml(m.name || "(untitled list)")}</div>
        </div>
        <div class="ab-last-sent-row"><span class="ab-last-sent-label">Contacts:</span> ${m.size != null ? Number(m.size).toLocaleString() : "—"}</div>
        <div class="btn-row" style="margin-top:8px">
          ${m.hubspot_url ? `<a class="btn btn-outline" href="${escapeHtml(m.hubspot_url)}" target="_blank" rel="noopener">View in HubSpot</a>` : ""}
        </div>
      </div>`;
  }

  function renderExistingMasterLists(scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    const section = document.getElementById(ids.existingMasterSection);
    const grid = document.getElementById(ids.existingMasterGrid);
    if (!section || !grid) return;
    if (!st.existingMasterLists.length) {
      section.classList.add("hidden");
      grid.innerHTML = "";
      return;
    }
    grid.innerHTML = st.existingMasterLists.map(_existingMasterCardHtml).join("");
    section.classList.remove("hidden");
  }

  async function loadExistingMasterLists(eventName, brandShort, scope = "builder") {
    const st = _st(scope);
    st.existingMasterLists = [];
    renderExistingMasterLists(scope);
    if (!eventName && !brandShort) return;
    try {
      const params = new URLSearchParams({ event_name: eventName || "", brand_short: brandShort || "" });
      const resp = await fetch(`${API}/audience-builder/existing-master-lists?${params}`);
      if (!resp.ok) return;
      const data = await resp.json();
      st.existingMasterLists = data.results || [];
      renderExistingMasterLists(scope);
    } catch (_) {
      // Non-fatal — the panel just stays empty; this is a convenience
      // surface, not required to build a master list.
    }
  }

  // Pre-selects the same lists (inclusion + suppression) that a prior send
  // used, adding any not already present as synthetic "added" cards — mirrors
  // the existing search-and-add flow rather than a separate code path.
  //
  // On scope="step3" it then wires up the send list without any extra click:
  // a simple prior send (1-2 included lists, no suppression) reuses those
  // list(s) directly as the campaign's send list — no new HubSpot list is
  // created, exactly like app.js's selectList() does for a manually-picked
  // list. Anything more complex (3+ included lists, or any suppression) still
  // goes through buildMaster() to compose a single send target, since that's
  // the only way today to combine >2 lists or apply a suppression exclusion.
  async function useLastSentSelection(idx, scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    const e = st.lastSent[idx];
    if (!e) return;

    (e.included_lists || []).forEach(l => {
      if (l.missing) return; // dead list reference — nothing to build from
      const id = String(l.list_id);
      if (!st.cards.some(c => String(c.list_id) === id)) {
        st.cards.push({
          list_id: id, name: l.name, signal: "added", size: l.size,
          reason: `Used in "${e.email_name || "a prior send"}" (${_fmtSentDate(e.sent_at)})`,
        });
      }
      st.selected.add(id);
    });

    (e.suppression_lists || []).forEach(l => {
      if (l.missing) return; // dead list reference — nothing to build from
      const id = String(l.list_id);
      if (!st.suppressionCards.some(c => String(c.list_id) === id)) {
        st.suppressionCards.push({ list_id: id, name: l.name, label: "From last send", badge: "suppression", category: "standard", size: l.size });
      }
      st.suppressionSelected.add(id);
    });

    const results = document.getElementById(ids.results);
    if (results) results.classList.remove("hidden");
    renderCards(scope);
    renderSuppressionCards(scope);

    if (!st.selected.size) return;

    if (scope === "step3") {
      const liveIncluded = (e.included_lists || []).filter(l => !l.missing);
      const liveSuppression = (e.suppression_lists || []).filter(l => !l.missing);
      if (liveIncluded.length >= 1 && liveIncluded.length <= 2 && liveSuppression.length === 0) {
        _useListsDirectly(liveIncluded, scope);
        return;
      }
    }
    await buildMaster(scope);
  }

  // Wires 1-2 already-existing lists straight in as the campaign's send
  // list(s), with no HubSpot list composed — mirrors app.js's selectList()
  // ("An existing list becomes the send list directly").
  function _useListsDirectly(lists, scope) {
    const listIds = lists.map(l => String(l.list_id));
    if (typeof _masterListIds !== "undefined") _masterListIds = listIds;
    if (typeof _masterListId !== "undefined") _masterListId = listIds[0];
    if (typeof _subLists !== "undefined") {
      _subLists = lists.map(l => ({ name: l.name, id: String(l.list_id), kind: "selected" }));
      if (typeof renderSubLists === "function") renderSubLists(scope);
    }
    const badge = document.getElementById("audience-status-badge");
    if (badge) {
      badge.textContent = listIds.length > 1
        ? `✓ Using ${listIds.length} lists from last send directly`
        : "✓ Using list from last send directly";
      badge.style.color = "#166534";
    }
    const startImpl = document.getElementById("start-impl-btn");
    if (startImpl) { startImpl.disabled = false; startImpl.textContent = "Create Campaign Draft →"; }
  }

  // Clears a scope's discovery state back to "no discovery run yet" — used by
  // app.js's resetAudienceUI() when the user starts a new campaign, so a
  // stale Step 3 "Reuse Existing Audience" grid from a prior campaign isn't
  // left showing.
  function reset(scope = "builder") {
    const ids = _ids(scope);
    _states[scope] = _newState();
    const urlInput = document.getElementById(ids.eventUrl);
    if (urlInput) urlInput.value = "";
    clearStatus(ids.discoverStatus);
    renderCards(scope);
    renderSuppressionCards(scope);
    renderMissingSignals([], scope);
    renderLastSent(scope);
    renderExistingMasterLists(scope);
    const results = document.getElementById(ids.results);
    if (results) results.classList.add("hidden");
  }

  function toggleCard(id, scope = "builder") {
    const st = _st(scope);
    id = String(id);
    if (st.selected.has(id)) st.selected.delete(id);
    else st.selected.add(id);
    renderCards(scope);
  }

  function selectAll(scope = "builder") {
    const st = _st(scope);
    st.cards.forEach(c => st.selected.add(String(c.list_id)));
    renderCards(scope);
  }

  function selectNone(scope = "builder") {
    _st(scope).selected.clear();
    renderCards(scope);
  }

  async function discover(scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    const urlInput = document.getElementById(ids.eventUrl);
    const eventUrl = ((urlInput && urlInput.value) || "").trim();
    if (!eventUrl || !/^https?:\/\//i.test(eventUrl)) {
      showError(ids.discoverStatus, "Please enter a valid URL starting with http:// or https://");
      return;
    }
    clearStatus(ids.discoverStatus);

    st.cards = [];
    st.selected = new Set();
    st.suppressionCards = [];
    st.suppressionSelected = new Set();
    st.brandShort = "";
    st.eventName = "";
    st.lastSent = [];
    st.lastSentIncludedIds = new Set();
    st.lastSentSuppressionIds = new Set();
    st.existingMasterLists = [];
    renderCards(scope);
    renderSuppressionCards(scope);
    renderMissingSignals([], scope);
    renderLastSent(scope);
    renderExistingMasterLists(scope);
    const results = document.getElementById(ids.results);
    if (results) results.classList.add("hidden");

    const discoverBtn = document.getElementById(ids.discoverBtn);
    const ticker = document.getElementById(ids.discoverTicker);
    if (discoverBtn) discoverBtn.disabled = true;
    if (ticker) { ticker.textContent = ""; ticker.classList.remove("hidden"); }

    let jobId = null;
    try {
      const resp = await fetch(`${API}/audience-builder/discover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_url: eventUrl, qa: "" }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || "Failed to start discovery");
      }
      const data = await resp.json();
      jobId = data.job_id;
    } catch (e) {
      if (ticker) ticker.classList.add("hidden");
      showError(ids.discoverStatus, e.message);
      if (discoverBtn) discoverBtn.disabled = false;
      return;
    }

    if (st.discoverES) st.discoverES.close();
    st.discoverES = new EventSource(`${API}/audience-builder/discover-stream/${jobId}`);

    st.discoverES.onmessage = (evt) => {
      let msg;
      try { msg = JSON.parse(evt.data); } catch (_) { return; }

      if (msg.type === "output") {
        if (ticker && msg.text) {
          const line = document.createElement("div");
          line.className = "ab-log-line";
          line.textContent = msg.text;
          ticker.appendChild(line);
          ticker.scrollTop = ticker.scrollHeight;
        }
      } else if (msg.type === "discovered") {
        const found = (msg.lists || []).map(l => ({ ...l }));
        const uncertain = (msg.uncertain || []).map(l => ({ ...l, signal: "uncertain" }));
        st.cards = found.concat(uncertain);
        st.brandShort = msg.brand_short || "";
        st.eventName = msg.event_name || "";
        const results2 = document.getElementById(ids.results);
        if (results2) results2.classList.remove("hidden");
        renderCards(scope);
        renderMissingSignals(msg.missing_signals, scope);
        loadSuppressionLists(scope);
        loadLastSent(st.eventName, st.brandShort, scope);
        loadExistingMasterLists(st.eventName, st.brandShort, scope);
      }

      if (msg.done) {
        st.discoverES.close();
        st.discoverES = null;
        if (discoverBtn) discoverBtn.disabled = false;
        renderMissingSignals(msg.missing_signals, scope);
        if (msg.success === false && !st.cards.length) {
          showError(ids.discoverStatus, "Discovery finished without finding any lists — see the log above.");
        }
      }
    };

    st.discoverES.onerror = () => {
      if (st.discoverES) { st.discoverES.close(); st.discoverES = null; }
      if (discoverBtn) discoverBtn.disabled = false;
    };
  }

  async function onSearch(query, scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    const dropdown = document.getElementById(ids.searchDropdown);
    if (!dropdown) return;
    if (!query || query.length < 2) {
      dropdown.classList.add("hidden");
      return;
    }
    clearTimeout(st.searchTimer);
    st.searchTimer = setTimeout(async () => {
      try {
        const resp = await fetch(`${API}/audience-builder/lists/search?q=${encodeURIComponent(query)}`);
        const data = await resp.json();
        const results = data.results || [];
        if (!results.length) {
          dropdown.innerHTML = `<div class="list-dropdown-item" style="color:var(--gray-400)">No lists found</div>`;
        } else {
          dropdown.innerHTML = results.map(l => `
            <div class="list-dropdown-item" onclick="AudienceBuilder.addFromSearch('${l.listId}','${escapeHtml(l.name)}',${l.size || 0},'${scope}')">
              <span>${escapeHtml(l.name)}</span>
              <span class="list-count">${l.size ? Number(l.size).toLocaleString() + " contacts" : ""}</span>
            </div>`).join("");
        }
        dropdown.classList.remove("hidden");
      } catch (_) {}
    }, 300);
  }

  function addFromSearch(id, name, size, scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    id = String(id);
    if (!st.cards.some(c => String(c.list_id) === id)) {
      st.cards.push({ list_id: id, name, signal: "added", size, reason: "Manually added" });
    }
    st.selected.add(id);

    const input = document.getElementById(ids.searchInput);
    if (input) input.value = "";
    const dropdown = document.getElementById(ids.searchDropdown);
    if (dropdown) dropdown.classList.add("hidden");

    const results = document.getElementById(ids.results);
    if (results) results.classList.remove("hidden");
    renderCards(scope);
  }

  async function buildMaster(scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    if (!st.selected.size) return;
    const buildBtn = document.getElementById(ids.buildMasterBtn);
    if (buildBtn) buildBtn.disabled = true;
    setLoading(ids.buildStatus, "Building master list in HubSpot…");

    const urlInput = document.getElementById(ids.eventUrl);
    const eventUrl = ((urlInput && urlInput.value) || "").trim();

    // Guard against a list being both an inclusion and a suppression at once
    // (e.g. Current Registrants happens to point at the same list ID as a
    // selected Event Registration card) — that would zero out its own branch.
    const excludeIds = Array.from(st.suppressionSelected).filter(id => !st.selected.has(id));

    try {
      const resp = await fetch(`${API}/audience-builder/compose-master`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ list_ids: Array.from(st.selected), event_url: eventUrl, exclude_list_ids: excludeIds }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || "Failed to build master list");
      }
      const data = await resp.json();
      const el = document.getElementById(ids.buildStatus);
      if (el) {
        el.classList.remove("hidden");
        const sizeText = data.size != null && data.size !== "unknown"
          ? ` · ${escapeHtml(String(Number(data.size).toLocaleString?.() || data.size))} contacts`
          : "";
        const suppressionLine = data.suppression_list_id
          ? `<div style="margin-top:6px">🚫 Suppressions applied via <a href="${escapeHtml(data.suppression_hubspot_url || "#")}" target="_blank" rel="noopener">${escapeHtml(data.suppression_name || "Combined Suppression")}</a></div>`
          : "";
        el.innerHTML = `<div class="success-box">✅ Master list ready — <a href="${escapeHtml(data.hubspot_url || "#")}" target="_blank" rel="noopener">${escapeHtml(data.name || "view in HubSpot")}</a> (List ID ${escapeHtml(String(data.list_id))}${sizeText})${suppressionLine}</div>`;
      }

      // scope="step3" only — wire the composed master list into the campaign
      // session the same way the AI-planning path does (see approveCustomAudiencePlan
      // in app.js): set the shared _masterListId global so Step 3 → 4's
      // startImplementation() attaches it via /api/set-send-list after clone,
      // fold it into the "Lists in the master audience" panel, and unlock
      // "Create Campaign Draft".
      if (scope === "step3" && data.list_id) {
        if (typeof _masterListId !== "undefined") _masterListId = String(data.list_id);
        if (typeof _masterListIds !== "undefined") _masterListIds = [String(data.list_id)];
        if (typeof _markMaster === "function") _markMaster(data.list_id, data.hubspot_url, "step3");
        const badge = document.getElementById("audience-status-badge");
        if (badge) { badge.textContent = `✓ Audience ready (ID ${data.list_id})`; badge.style.color = "#166534"; }
        const startImpl = document.getElementById("start-impl-btn");
        if (startImpl) { startImpl.disabled = false; startImpl.textContent = "Create Campaign Draft →"; }
      }
    } catch (e) {
      showError(ids.buildStatus, e.message);
    } finally {
      if (buildBtn) buildBtn.disabled = st.selected.size === 0;
    }
  }

  function discardCustomPlan(scope = "builder") {
    const ids = _ids(scope), st = _st(scope);
    st.pendingMissingSignal = null;
    const planActions = document.getElementById("ab-custom-plan-actions");
    if (planActions) planActions.classList.add("hidden");
    clearAudienceQuestions(scope === "step3" ? "step3" : "builder");

    const ticker = document.getElementById(ids.customTicker);
    if (ticker) { ticker.textContent = ""; ticker.classList.add("hidden"); }

    clearStatus("ab-custom-result");
    clearStatus(ids.customTicker === "ab-custom-ticker" ? "ab-custom-status" : "custom-audience-url-status");

    const badge = document.getElementById("ab-custom-status-badge");
    if (badge) { badge.textContent = "— describe an audience in your own words"; badge.style.color = "var(--gray-400)"; }

    const buildBtn = document.getElementById("ab-custom-build-btn");
    if (buildBtn) buildBtn.disabled = false;

    const roleSpeakers = document.getElementById("ab-role-filter-speakers");
    if (roleSpeakers) roleSpeakers.checked = false;
    const roleAmbassadors = document.getElementById("ab-role-filter-ambassadors");
    if (roleAmbassadors) roleAmbassadors.checked = false;
  }

  return {
    discover, selectAll, selectNone, toggleCard, onSearch, addFromSearch, buildMaster,
    discardCustomPlan, createMissingSignal, onCustomListBuilt, onCustomBuildFailed,
    toggleSuppressionCard, getExactCount, getSuppressionExactCount, useLastSentSelection, reset,
  };
})();
