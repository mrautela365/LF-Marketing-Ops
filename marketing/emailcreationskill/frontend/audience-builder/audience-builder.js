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

  let _cards = [];
  let _selected = new Set();
  let _searchTimer = null;
  let _discoverES = null;

  function _signalBadge(signal) {
    const label = SIGNAL_LABELS[signal] || signal;
    return `<span class="ab-signal-badge ab-signal-${escapeHtml(signal)}">${escapeHtml(label)}</span>`;
  }

  function renderCards() {
    const grid = document.getElementById("ab-card-grid");
    if (!grid) return;
    grid.innerHTML = _cards.map(c => {
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
            ${_signalBadge(c.signal || "uncertain")}
          </div>
          <div class="ab-card-name">${escapeHtml(c.name || "(untitled list)")}</div>
          <div class="ab-card-meta"><span>ID ${escapeHtml(id)}</span></div>
          <div class="ab-stat-row">${statsHtml}</div>
          ${c.reason ? `<div class="ab-card-reason">${escapeHtml(c.reason)}</div>` : ""}
        </div>`;
    }).join("");
    updateSummary();
  }

  function updateSummary() {
    const summary = document.getElementById("ab-summary");
    if (summary) summary.textContent = `${_cards.length} list(s) found — ${_selected.size} selected`;
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
        if (ticker) {
          ticker.textContent += (ticker.textContent ? "\n" : "") + (msg.text || "");
          ticker.scrollTop = ticker.scrollHeight;
        }
      } else if (msg.type === "discovered") {
        const found = (msg.lists || []).map(l => ({ ...l }));
        const uncertain = (msg.uncertain || []).map(l => ({ ...l, signal: "uncertain" }));
        _cards = found.concat(uncertain);
        document.getElementById("ab-results").classList.remove("hidden");
        renderCards();
      }

      if (msg.done) {
        _discoverES.close();
        _discoverES = null;
        if (discoverBtn) discoverBtn.disabled = false;
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
        el.innerHTML = `<span style="color:#166534">✅ Master list ready — <a href="${escapeHtml(data.hubspot_url || "#")}" target="_blank" rel="noopener">${escapeHtml(data.name || "view in HubSpot")}</a> (List ID ${escapeHtml(String(data.list_id))})</span>`;
      }
    } catch (e) {
      showError("ab-build-status", e.message);
    } finally {
      if (buildBtn) buildBtn.disabled = _selected.size === 0;
    }
  }

  function discardCustomPlan() {
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

  return { discover, selectAll, selectNone, toggleCard, onSearch, addFromSearch, buildMaster, discardCustomPlan };
})();
