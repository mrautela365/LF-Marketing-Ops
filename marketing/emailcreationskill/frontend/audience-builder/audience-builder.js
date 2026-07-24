// ── Audience Builder tab: existing-list discovery + master-list composer ──
// Uses globals defined in app.js (API, setLoading, clearStatus, showError,
// escapeHtml, clearAudienceQuestions) — this file is loaded after app.js.
const AudienceBuilder = (() => {
  const SIGNAL_LABELS = {
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
    "event_registration",
    "project_opt_in",
    "lf_newsletter_opt_in",
    "education_enrollment",
    "page_view",
    "uncertain",
    "added",
  ];
  const SIGNAL_DESC = {
    project_opt_in: "Opted into this project's own subscription type",
    lf_newsletter_opt_in: "Opted into the Linux Foundation newsletter",
    event_registration: "All-time registrants for this event",
    education_enrollment: "Enrolled in related education content",
    page_view: "Viewed this event's page",
    uncertain: "Needs manual review before including",
    added: "Manually added via search",
  };
  const SIGNAL_ACCENT = {
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

  function _cardHtml(c) {
    const id = String(c.list_id);
    const selected = _selected.has(id);
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
        <div class="ab-card-meta"><span>ID ${escapeHtml(id)}</span></div>
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

    const totalContacts = _cards.reduce((sum, c) => sum + (typeof c.size === "number" ? c.size : 0), 0);
    const totalEl = document.getElementById("ab-stat-contacts");
    if (totalEl) totalEl.textContent = totalContacts ? totalContacts.toLocaleString() : "—";

    const selEl = document.getElementById("ab-stat-selected");
    if (selEl) selEl.textContent = String(_selected.size);

    const buildBtn = document.getElementById("ab-build-master-btn");
    if (buildBtn) buildBtn.disabled = _selected.size === 0;
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
    renderCards();
    renderMissingSignals([]);
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
        document.getElementById("ab-results").classList.remove("hidden");
        renderCards();
        renderMissingSignals(msg.missing_signals);
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

    try {
      const resp = await fetch(`${API}/audience-builder/compose-master`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ list_ids: Array.from(_selected), event_url: eventUrl }),
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
        el.innerHTML = `<div class="success-box">✅ Master list ready — <a href="${escapeHtml(data.hubspot_url || "#")}" target="_blank" rel="noopener">${escapeHtml(data.name || "view in HubSpot")}</a> (List ID ${escapeHtml(String(data.list_id))}${sizeText})</div>`;
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
  };
})();
