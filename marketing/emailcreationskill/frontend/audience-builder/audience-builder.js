// ── Audience Builder tab: existing-list discovery + master-list composer ──
// Uses globals defined in app.js (API, setLoading, clearStatus, showError,
// escapeHtml, clearAudienceQuestions) — this file is loaded after app.js.
const AudienceBuilder = (() => {
  const SIGNAL_LABELS = {
    last_sent: "Used In Past Sends",
    project_opt_in: "Project Opt-In",
    lf_newsletter_opt_in: "LF Newsletter Opt-In",
    event_registration: "Event Registration",
    education_enrollment: "Education Enrollment",
    page_view: "Page View",
    uncertain: "Uncertain",
    added: "Manually Added",
  };

  const SIGNAL_INFO = {
    project_opt_in: {
      label: "Project Opt-In",
      description: "Contacts opted into this project's own email subscription type (not the general LF newsletter).",
      prompt: (eventUrl) => `Build a list of contacts opted into this project's own email subscription type (project-specific opt-in, not the general Linux Foundation newsletter) for the event at ${eventUrl}.`,
    },
    lf_newsletter_opt_in: {
      label: "LF Newsletter Opt-In",
      description: "Contacts opted into the Linux Foundation Newsletter subscription type.",
      prompt: (eventUrl) => `Build a list of contacts opted into the Linux Foundation Newsletter subscription type, relevant to the event at ${eventUrl}.`,
    },
    event_registration: {
      label: "Event Registration",
      description: "All-time registrants for this event, across all past editions.",
      prompt: (eventUrl) => `Build a list of all-time registrants (all editions) for the event at ${eventUrl}.`,
    },
    education_enrollment: {
      label: "Education Enrollment",
      description: "Contacts enrolled in LFX Education courses related to this event's topic area.",
      prompt: (eventUrl) => `Build a list of contacts enrolled in LFX Education courses related to the topic area of the event at ${eventUrl}.`,
    },
    page_view: {
      label: "Page View",
      description: "Contacts who viewed this event's page (page-view based segment).",
      prompt: (eventUrl) => `Build a page-view based list of contacts who viewed the event page at ${eventUrl}.`,
    },
  };

  // Section-grouping order + per-section accent/caption — mirrors the
  // layered "Layer 1 / Layer 2 / Layer 3" grouping from the audience-engine
  // reference, applied over our own 5-signal taxonomy instead of its
  // lookalike/intent/profile-fit buckets.
  const SIGNAL_ORDER = [
    "last_sent",
    "event_registration",
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
    uncertain: "var(--gray-400)",
    added: "var(--gray-500)",
  };

  let _cards = [];
  let _selected = new Set();
  let _missingSignals = [];
  let _searchTimer = null;
  let _discoverES = null;
  let _pendingMissingSignal = null; // signal key the direct-build request below is for
  let _buildingSignals = new Set(); // signal keys with a direct build currently in flight
  let _brandShort = ""; // resolved by the discovery agent, reused for suppression/last-sent lookups
  let _eventName = "";

  // Suppression & Exclusions — standard hygiene lists + this event's current
  // registrants (mapped from the discovered event_registration card, if any),
  // all pre-selected by default. Feeds compose-master's exclude_list_ids.
  let _suppressionCards = [];
  let _suppressionSelected = new Set();

  // "What was sent last time" — up to 3 recent emails for this event, each
  // with the HubSpot lists they used (see backend/audience_builder/last_sent.py).
  let _lastSent = [];
  // Flattened list_ids across all _lastSent entries — drives the "Used last
  // time" card badge and the auto-select-on-discover behavior below.
  let _lastSentIncludedIds = new Set();
  let _lastSentSuppressionIds = new Set();

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

  function _suppressionCardHtml(c) {
    const id = String(c.list_id);
    const selected = _suppressionSelected.has(id);
    const badgeClass = c.badge || "suppression";
    const recommended = c.category === "event_specific"
      ? `<span class="ab-recommended-tag">★ Recommended</span>` : "";
    const usedLastSent = _lastSentSuppressionIds.has(id)
      ? `<span class="ab-lastsent-badge" title="Suppressed in a past send for this event">📧 Used last time</span>` : "";
    return `
      <div class="ab-card${selected ? " selected" : ""}" onclick="AudienceBuilder.toggleSuppressionCard('${id}')">
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

  function renderSuppressionCards() {
    const grid = document.getElementById("ab-suppression-grid");
    if (!grid) return;
    grid.innerHTML = _suppressionCards.map(_suppressionCardHtml).join("");

    const totalContacts = _sumSelectedSize(_suppressionCards, _suppressionSelected);
    const totalEl = document.getElementById("ab-suppression-contacts");
    if (totalEl) totalEl.textContent = totalContacts ? totalContacts.toLocaleString() : "—";
    const tag = document.getElementById("ab-suppression-contacts-tag");
    if (tag) tag.textContent = _suppressionSelected.size ? "(estimate, may overlap)" : "";
    const exactBtn = document.getElementById("ab-suppression-exact-btn");
    if (exactBtn) { exactBtn.disabled = _suppressionSelected.size === 0; exactBtn.textContent = "Get exact count"; }
  }

  function toggleSuppressionCard(id) {
    id = String(id);
    if (_suppressionSelected.has(id)) _suppressionSelected.delete(id);
    else _suppressionSelected.add(id);
    renderSuppressionCards();
  }

  async function getSuppressionExactCount() {
    if (!_suppressionSelected.size) return;
    const btn = document.getElementById("ab-suppression-exact-btn");
    const tag = document.getElementById("ab-suppression-contacts-tag");
    if (btn) { btn.disabled = true; btn.textContent = "Calculating…"; }
    try {
      const data = await _fetchExactCount(Array.from(_suppressionSelected));
      const totalEl = document.getElementById("ab-suppression-contacts");
      if (totalEl) totalEl.textContent = Number(data.count || 0).toLocaleString();
      if (tag) tag.textContent = data.exact ? "(exact)" : `(estimate — ${data.reason || "too large for exact"})`;
    } catch (e) {
      if (tag) tag.textContent = "(failed)";
    } finally {
      if (btn) { btn.disabled = _suppressionSelected.size === 0; btn.textContent = "Get exact count"; }
    }
  }

  async function loadSuppressionLists() {
    _suppressionCards = [];
    _suppressionSelected = new Set();

    // Current Registrants — reuse whatever Event Registration list(s)
    // discovery already found for this event; suppressing on it prevents
    // re-inviting people who already registered.
    _cards.filter(c => c.signal === "event_registration").forEach(c => {
      const id = String(c.list_id);
      _suppressionCards.push({
        list_id: id,
        name: c.name,
        label: "Current Registrants",
        badge: "current_registrants",
        category: "current_registrants",
        size: c.size,
      });
      _suppressionSelected.add(id);
    });

    try {
      const params = new URLSearchParams({ brand_short: _brandShort || "", event_name: _eventName || "" });
      const resp = await fetch(`${API}/audience-builder/suppression-lists?${params}`);
      if (resp.ok) {
        const data = await resp.json();
        (data.results || []).forEach(r => {
          const id = String(r.list_id);
          const category = r.category || "standard";
          _suppressionCards.push({
            list_id: id,
            name: r.name,
            label: r.label,
            badge: category === "event_specific" ? "event_specific" : category === "brand" ? "brand" : "suppression",
            category,
            size: r.size,
          });
          _suppressionSelected.add(id);
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
    _suppressionCards.sort((a, b) => (rank[a.category] ?? 9) - (rank[b.category] ?? 9));

    renderSuppressionCards();
  }

  function _cardHtml(c) {
    const id = String(c.list_id);
    const selected = _selected.has(id);
    const usedLastSent = _lastSentIncludedIds.has(id)
      ? `<span class="ab-lastsent-badge" title="Used in a past send for this event">📧 Used last time</span>` : "";
    const stats = [
      { label: "Contacts", value: c.size != null ? Number(c.size).toLocaleString() : "—" },
    ];
    if (c.list_type) stats.push({ label: "List type", value: c.list_type });
    const statsHtml = stats.map(s => `
      <div class="ab-stat-box">
        <div class="ab-stat-label">${escapeHtml(s.label)}</div>
        <div class="ab-stat-value">${escapeHtml(String(s.value))}</div>
      </div>`).join("");
    return `
      <div class="ab-card${selected ? " selected" : ""}" onclick="AudienceBuilder.toggleCard('${id}')">
        <div class="ab-card-top">
          <span class="ab-card-check"></span>
        </div>
        <div class="ab-card-name">${escapeHtml(c.name || "(untitled list)")}</div>
        <div class="ab-card-meta"><span>ID ${escapeHtml(id)}</span>${usedLastSent}</div>
        <div class="ab-stat-row">${statsHtml}</div>
        ${c.reason ? `<div class="ab-card-reason">${escapeHtml(c.reason)}</div>` : ""}
      </div>`;
  }

  function renderCards() {
    const container = document.getElementById("ab-card-sections");
    if (!container) return;

    const bySignal = new Map();
    _cards.forEach(c => {
      const sig = c.signal || "uncertain";
      if (!bySignal.has(sig)) bySignal.set(sig, []);
      bySignal.get(sig).push(c);
    });

    container.innerHTML = SIGNAL_ORDER.filter(sig => bySignal.has(sig)).map(sig => {
      const group = bySignal.get(sig);
      const cardsHtml = group.map(_cardHtml).join("");
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

    updateSummary();
  }

  function renderMissingSignals(missing) {
    _missingSignals = missing || [];
    const section = document.getElementById("ab-missing-section");
    const grid = document.getElementById("ab-missing-grid");
    if (!section || !grid) return;
    if (!_missingSignals.length) {
      section.classList.add("hidden");
      grid.innerHTML = "";
      return;
    }
    grid.innerHTML = _missingSignals.map(sig => {
      const info = SIGNAL_INFO[sig] || { label: sig, description: "" };
      const building = _buildingSignals.has(sig);
      return `
        <div class="ab-card ab-card-missing">
          <div class="ab-card-top">
            <span class="ab-signal-badge ab-signal-${escapeHtml(sig)}">${escapeHtml(info.label)}</span>
          </div>
          <div class="ab-card-reason" style="border-top:none;padding-top:0;margin-top:0">${escapeHtml(info.description)}</div>
          <div class="btn-row" style="margin-top:10px">
            <button class="btn btn-outline" type="button" ${building ? "disabled" : ""} onclick="AudienceBuilder.createMissingSignal('${sig}')">${building ? "Building…" : "Create list"}</button>
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
  // in one job, no approval gate).
  async function createMissingSignal(signalKey) {
    const info = SIGNAL_INFO[signalKey];
    if (!info || _buildingSignals.has(signalKey)) return;
    _pendingMissingSignal = signalKey;
    _buildingSignals.add(signalKey);
    renderMissingSignals(_missingSignals);

    const urlInput = document.getElementById("ab-event-url");
    const eventUrl = ((urlInput && urlInput.value) || "").trim();
    const request = info.prompt(eventUrl);
    const textarea = document.getElementById("ab-custom-request");
    if (textarea) textarea.value = request;
    const ticker = document.getElementById("ab-custom-ticker");
    (ticker || textarea)?.scrollIntoView({ behavior: "smooth", block: "center" });

    if (typeof runDirectSignalBuild === "function") {
      await runDirectSignalBuild(request, "builder");
    }
  }

  // Called by app.js's runDirectSignalBuild() (scope="builder" only) once a
  // directly-built list finishes. Folds the new list straight into the
  // discovery grid — selected, under its signal — instead of leaving it
  // stranded only in the Build From Scratch result panel. Returns the signal
  // key it attached to, or null if this build wasn't for a missing signal (so
  // app.js's confirmation message can vary accordingly).
  function onCustomListBuilt({ list_id, name }) {
    const signal = _pendingMissingSignal;
    _pendingMissingSignal = null;
    if (!signal) return null;
    _buildingSignals.delete(signal);

    const id = String(list_id);
    if (!_cards.some(c => String(c.list_id) === id)) {
      _cards.push({
        list_id: id,
        name: name || `List ${id}`,
        signal,
        size: null,
        reason: "Created via Build From Scratch",
      });
    }
    _selected.add(id);
    renderMissingSignals(_missingSignals.filter(s => s !== signal));
    document.getElementById("ab-results").classList.remove("hidden");
    renderCards();
    if (signal === "event_registration") loadSuppressionLists();
    return signal;
  }

  // Called by app.js's runDirectSignalBuild() when a direct build fails —
  // clears the in-flight state so the missing-signal card's button resets to
  // "Create list" instead of staying stuck on "Building…".
  function onCustomBuildFailed() {
    const signal = _pendingMissingSignal;
    _pendingMissingSignal = null;
    if (signal) _buildingSignals.delete(signal);
    renderMissingSignals(_missingSignals);
  }

  function updateSummary() {
    const segEl = document.getElementById("ab-stat-segments");
    if (segEl) segEl.textContent = String(_cards.length);

    const totalContacts = _sumSelectedSize(_cards, _selected);
    const totalEl = document.getElementById("ab-stat-contacts");
    if (totalEl) totalEl.textContent = totalContacts ? totalContacts.toLocaleString() : "—";
    const tag = document.getElementById("ab-stat-contacts-tag");
    if (tag) tag.textContent = _selected.size ? "(estimate, may overlap)" : "";

    const selEl = document.getElementById("ab-stat-selected");
    if (selEl) selEl.textContent = String(_selected.size);

    const buildBtn = document.getElementById("ab-build-master-btn");
    if (buildBtn) buildBtn.disabled = _selected.size === 0;
    const exactBtn = document.getElementById("ab-exact-count-btn");
    if (exactBtn) { exactBtn.disabled = _selected.size === 0; exactBtn.textContent = "Get exact count"; }
  }

  async function getExactCount() {
    if (!_selected.size) return;
    const btn = document.getElementById("ab-exact-count-btn");
    const tag = document.getElementById("ab-stat-contacts-tag");
    if (btn) { btn.disabled = true; btn.textContent = "Calculating…"; }
    try {
      const data = await _fetchExactCount(Array.from(_selected));
      const totalEl = document.getElementById("ab-stat-contacts");
      if (totalEl) totalEl.textContent = Number(data.count || 0).toLocaleString();
      if (tag) tag.textContent = data.exact ? "(exact)" : `(estimate — ${data.reason || "too large for exact"})`;
    } catch (e) {
      if (tag) tag.textContent = "(failed)";
    } finally {
      if (btn) { btn.disabled = _selected.size === 0; btn.textContent = "Get exact count"; }
    }
  }

  function _lastSentCardHtml(e, idx) {
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
          <button class="btn btn-primary" type="button" onclick="AudienceBuilder.useLastSentSelection(${idx})">Use same selection</button>
        </div>
      </div>`;
  }

  function renderLastSent() {
    const section = document.getElementById("ab-last-sent-section");
    const grid = document.getElementById("ab-last-sent-grid");
    if (!section || !grid) return;
    if (!_lastSent.length) {
      section.classList.add("hidden");
      grid.innerHTML = "";
      return;
    }
    grid.innerHTML = _lastSent.map((e, i) => _lastSentCardHtml(e, i)).join("");
    section.classList.remove("hidden");
  }

  async function loadLastSent(eventName, brandShort) {
    _lastSent = [];
    _lastSentIncludedIds = new Set();
    _lastSentSuppressionIds = new Set();
    renderLastSent();
    if (!eventName && !brandShort) return;
    try {
      const params = new URLSearchParams({ event_name: eventName || "", brand_short: brandShort || "" });
      const resp = await fetch(`${API}/audience-builder/last-sent?${params}`);
      if (!resp.ok) return;
      const data = await resp.json();
      _lastSent = data.results || [];
      const includedBrief = new Map(); // list_id -> {name, size} from the first send that used it
      _lastSent.forEach(e => {
        (e.included_lists || []).forEach(l => {
          const id = String(l.list_id);
          _lastSentIncludedIds.add(id);
          if (!includedBrief.has(id)) includedBrief.set(id, l);
        });
        (e.suppression_lists || []).forEach(l => _lastSentSuppressionIds.add(String(l.list_id)));
      });

      // Auto-select discovered cards that match a list used in a past send —
      // these "common" lists shouldn't require a manual "Use same selection"
      // click. Suppression cards are already all pre-selected by default
      // (loadSuppressionLists), so only the inclusion side needs this.
      _cards.forEach(c => {
        if (_lastSentIncludedIds.has(String(c.list_id))) _selected.add(String(c.list_id));
      });

      // A past-send inclusion list often doesn't fit any of the 5 discovery
      // signals (e.g. a regional/demographic segment) and so never becomes a
      // card at all — that left it selectable only via a manual "Use same
      // selection" click. Synthesize a card for it too, under its own
      // "Used In Past Sends" section, so it's never silently missing from the
      // buildable grid.
      includedBrief.forEach((l, id) => {
        if (!_cards.some(c => String(c.list_id) === id)) {
          _cards.push({
            list_id: id, name: l.name, signal: "last_sent", size: l.size,
            reason: "Used in a past send for this event; not classified under the 5 signals above.",
          });
        }
        _selected.add(id);
      });

      renderLastSent();
      renderCards();
      renderSuppressionCards();
    } catch (_) {
      // Non-fatal — the panel just stays empty; last-sent is a convenience
      // surface, not required to build a master list.
    }
  }

  // Pre-selects the same lists (inclusion + suppression) that a prior send
  // used, adding any not already present as synthetic "added" cards — mirrors
  // the existing search-and-add flow rather than a separate code path.
  function useLastSentSelection(idx) {
    const e = _lastSent[idx];
    if (!e) return;

    (e.included_lists || []).forEach(l => {
      const id = String(l.list_id);
      if (!_cards.some(c => String(c.list_id) === id)) {
        _cards.push({
          list_id: id, name: l.name, signal: "added", size: l.size,
          reason: `Used in "${e.email_name || "a prior send"}" (${_fmtSentDate(e.sent_at)})`,
        });
      }
      _selected.add(id);
    });

    (e.suppression_lists || []).forEach(l => {
      const id = String(l.list_id);
      if (!_suppressionCards.some(c => String(c.list_id) === id)) {
        _suppressionCards.push({ list_id: id, name: l.name, label: "From last send", badge: "suppression", category: "standard", size: l.size });
      }
      _suppressionSelected.add(id);
    });

    document.getElementById("ab-results").classList.remove("hidden");
    renderCards();
    renderSuppressionCards();
  }

  function toggleCard(id) {
    id = String(id);
    if (_selected.has(id)) _selected.delete(id);
    else _selected.add(id);
    renderCards();
  }

  function selectAll() {
    _cards.forEach(c => _selected.add(String(c.list_id)));
    renderCards();
  }

  function selectNone() {
    _selected.clear();
    renderCards();
  }

  async function discover() {
    const urlInput = document.getElementById("ab-event-url");
    const eventUrl = ((urlInput && urlInput.value) || "").trim();
    if (!eventUrl || !/^https?:\/\//i.test(eventUrl)) {
      showError("ab-discover-status", "Please enter a valid URL starting with http:// or https://");
      return;
    }
    clearStatus("ab-discover-status");

    _cards = [];
    _selected = new Set();
    _suppressionCards = [];
    _suppressionSelected = new Set();
    _brandShort = "";
    _eventName = "";
    _lastSent = [];
    _lastSentIncludedIds = new Set();
    _lastSentSuppressionIds = new Set();
    renderCards();
    renderSuppressionCards();
    renderMissingSignals([]);
    renderLastSent();
    document.getElementById("ab-results").classList.add("hidden");

    const discoverBtn = document.getElementById("ab-discover-btn");
    const ticker = document.getElementById("ab-discover-ticker");
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
      showError("ab-discover-status", e.message);
      if (discoverBtn) discoverBtn.disabled = false;
      return;
    }

    if (_discoverES) _discoverES.close();
    _discoverES = new EventSource(`${API}/audience-builder/discover-stream/${jobId}`);

    _discoverES.onmessage = (evt) => {
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
        _cards = found.concat(uncertain);
        _brandShort = msg.brand_short || "";
        _eventName = msg.event_name || "";
        document.getElementById("ab-results").classList.remove("hidden");
        renderCards();
        renderMissingSignals(msg.missing_signals);
        loadSuppressionLists();
        loadLastSent(_eventName, _brandShort);
      }

      if (msg.done) {
        _discoverES.close();
        _discoverES = null;
        if (discoverBtn) discoverBtn.disabled = false;
        renderMissingSignals(msg.missing_signals);
        if (msg.success === false && !_cards.length) {
          showError("ab-discover-status", "Discovery finished without finding any lists — see the log above.");
        }
      }
    };

    _discoverES.onerror = () => {
      if (_discoverES) { _discoverES.close(); _discoverES = null; }
      if (discoverBtn) discoverBtn.disabled = false;
    };
  }

  async function onSearch(query) {
    const dropdown = document.getElementById("ab-search-dropdown");
    if (!dropdown) return;
    if (!query || query.length < 2) {
      dropdown.classList.add("hidden");
      return;
    }
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(async () => {
      try {
        const resp = await fetch(`${API}/audience-builder/lists/search?q=${encodeURIComponent(query)}`);
        const data = await resp.json();
        const results = data.results || [];
        if (!results.length) {
          dropdown.innerHTML = `<div class="list-dropdown-item" style="color:var(--gray-400)">No lists found</div>`;
        } else {
          dropdown.innerHTML = results.map(l => `
            <div class="list-dropdown-item" onclick="AudienceBuilder.addFromSearch('${l.listId}','${escapeHtml(l.name)}',${l.size || 0})">
              <span>${escapeHtml(l.name)}</span>
              <span class="list-count">${l.size ? Number(l.size).toLocaleString() + " contacts" : ""}</span>
            </div>`).join("");
        }
        dropdown.classList.remove("hidden");
      } catch (_) {}
    }, 300);
  }

  function addFromSearch(id, name, size) {
    id = String(id);
    if (!_cards.some(c => String(c.list_id) === id)) {
      _cards.push({ list_id: id, name, signal: "added", size, reason: "Manually added" });
    }
    _selected.add(id);

    const input = document.getElementById("ab-search-input");
    if (input) input.value = "";
    const dropdown = document.getElementById("ab-search-dropdown");
    if (dropdown) dropdown.classList.add("hidden");

    document.getElementById("ab-results").classList.remove("hidden");
    renderCards();
  }

  async function buildMaster() {
    if (!_selected.size) return;
    const buildBtn = document.getElementById("ab-build-master-btn");
    if (buildBtn) buildBtn.disabled = true;
    setLoading("ab-build-status", "Building master list in HubSpot…");

    const urlInput = document.getElementById("ab-event-url");
    const eventUrl = ((urlInput && urlInput.value) || "").trim();

    // Guard against a list being both an inclusion and a suppression at once
    // (e.g. Current Registrants happens to point at the same list ID as a
    // selected Event Registration card) — that would zero out its own branch.
    const excludeIds = Array.from(_suppressionSelected).filter(id => !_selected.has(id));

    try {
      const resp = await fetch(`${API}/audience-builder/compose-master`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ list_ids: Array.from(_selected), event_url: eventUrl, exclude_list_ids: excludeIds }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || "Failed to build master list");
      }
      const data = await resp.json();
      const el = document.getElementById("ab-build-status");
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
    } catch (e) {
      showError("ab-build-status", e.message);
    } finally {
      if (buildBtn) buildBtn.disabled = _selected.size === 0;
    }
  }

  function discardCustomPlan() {
    _pendingMissingSignal = null;
    const planActions = document.getElementById("ab-custom-plan-actions");
    if (planActions) planActions.classList.add("hidden");
    clearAudienceQuestions("builder");

    const ticker = document.getElementById("ab-custom-ticker");
    if (ticker) { ticker.textContent = ""; ticker.classList.add("hidden"); }

    clearStatus("ab-custom-result");
    clearStatus("ab-custom-status");

    const badge = document.getElementById("ab-custom-status-badge");
    if (badge) { badge.textContent = "— describe an audience in your own words"; badge.style.color = "var(--gray-400)"; }

    const buildBtn = document.getElementById("ab-custom-build-btn");
    if (buildBtn) buildBtn.disabled = false;
  }

  return {
    discover, selectAll, selectNone, toggleCard, onSearch, addFromSearch, buildMaster,
    discardCustomPlan, createMissingSignal, onCustomListBuilt, onCustomBuildFailed,
    toggleSuppressionCard, getExactCount, getSuppressionExactCount, useLastSentSelection,
  };
})();
