'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  audienceLists: [],      // [{ list_id, name, size }]
  suppressionLists: [],   // [{ list_id, name, size }]
  subscriptionTypes: [],  // [{ id, name }]
  pendingDeleteId: null,
  pendingDeleteName: null,
};

// ── Utilities ─────────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  return res.json();
}

function showResult(elId, type, html) {
  const el = document.getElementById(elId);
  el.className = `result-area ${type}`;
  el.innerHTML = html;
}

function statusIcon(status) {
  return { pass: '✅', fail: '❌', warn: '⚠️', info: 'ℹ️' }[status] || status;
}

function severityClass(sev) {
  return `sev-${sev || 'info'}`;
}

// ── Tab Navigation ────────────────────────────────────────────────────────────

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
  });
});

// ── Character Counters ────────────────────────────────────────────────────────

function setupCounter(inputId, counterId, max) {
  const input = document.getElementById(inputId);
  const counter = document.getElementById(counterId);
  if (!input || !counter) return;
  const update = () => {
    const len = input.value.length;
    counter.textContent = `${len} / ${max}`;
    counter.classList.toggle('over', len > max);
  };
  input.addEventListener('input', update);
  update();
}
setupCounter('subject', 'subject-counter', 60);
setupCounter('preheader', 'preheader-counter', 100);

// ── Load Subscription Types ───────────────────────────────────────────────────

async function loadSubscriptionTypes() {
  const select = document.getElementById('subscription-type');
  try {
    const res = await api('GET', '/api/hubspot/subscription-types');
    if (res.success && res.data) {
      state.subscriptionTypes = res.data;
      select.innerHTML = '<option value="">— Select subscription type —</option>' +
        res.data.map(t =>
          `<option value="${t.id}">${t.name}${t.description ? ` — ${t.description}` : ''}</option>`
        ).join('');
    } else {
      select.innerHTML = '<option value="">Failed to load — check credentials</option>';
    }
  } catch (e) {
    select.innerHTML = '<option value="">Connection error</option>';
  }
}

// ── List Search & Selection ───────────────────────────────────────────────────

function renderSelectedLists(containerId, lists) {
  const container = document.getElementById(containerId);
  if (!lists.length) {
    container.innerHTML = '<p class="empty-hint">No lists selected.</p>';
    return;
  }
  container.innerHTML = lists.map(lst =>
    `<span class="selected-list-tag" data-id="${lst.list_id}">
      ${lst.name} <span class="list-meta">(${lst.size >= 0 ? lst.size.toLocaleString() : '?'})</span>
      <button type="button" data-remove="${lst.list_id}" aria-label="Remove">×</button>
    </span>`
  ).join('');
  container.querySelectorAll('[data-remove]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.remove;
      if (containerId === 'audience-selected') {
        state.audienceLists = state.audienceLists.filter(l => String(l.list_id) !== id);
        renderSelectedLists('audience-selected', state.audienceLists);
      } else {
        state.suppressionLists = state.suppressionLists.filter(l => String(l.list_id) !== id);
        renderSelectedLists('suppression-selected', state.suppressionLists);
      }
    });
  });
}

async function searchLists(query, resultsId, stateKey, selectedId) {
  const resultsEl = document.getElementById(resultsId);
  resultsEl.innerHTML = '<div style="padding:0.5rem;color:#718096">Searching…</div>';
  resultsEl.classList.add('visible');
  try {
    const res = await api('GET', `/api/hubspot/lists/search?q=${encodeURIComponent(query)}&limit=15`);
    if (!res.success || !res.data?.length) {
      resultsEl.innerHTML = '<div style="padding:0.5rem;color:#718096">No lists found.</div>';
      return;
    }
    resultsEl.innerHTML = res.data.map(lst =>
      `<div class="list-result-item" data-id="${lst.list_id}" data-name="${lst.name}" data-size="${lst.size ?? -1}">
        <span>${lst.name}</span>
        <span class="list-meta">${lst.list_type} · ${lst.size >= 0 ? lst.size.toLocaleString() : '?'} contacts</span>
      </div>`
    ).join('');
    resultsEl.querySelectorAll('.list-result-item').forEach(item => {
      item.addEventListener('click', () => {
        const entry = { list_id: item.dataset.id, name: item.dataset.name, size: parseInt(item.dataset.size) };
        const arr = stateKey === 'audience' ? state.audienceLists : state.suppressionLists;
        if (!arr.find(l => String(l.list_id) === String(entry.list_id))) {
          arr.push(entry);
        }
        renderSelectedLists(selectedId, arr);
        resultsEl.classList.remove('visible');
      });
    });
  } catch (e) {
    resultsEl.innerHTML = '<div style="padding:0.5rem;color:#e53e3e">Error fetching lists.</div>';
  }
}

document.getElementById('btn-audience-search').addEventListener('click', () => {
  const q = document.getElementById('audience-search').value.trim();
  if (q) searchLists(q, 'audience-results', 'audience', 'audience-selected');
});
document.getElementById('btn-suppression-search').addEventListener('click', () => {
  const q = document.getElementById('suppression-search').value.trim();
  if (q) searchLists(q, 'suppression-results', 'suppression', 'suppression-selected');
});

// ── Build Draft Spec from Form ────────────────────────────────────────────────

function buildDraftSpec() {
  const utmCampaign = document.getElementById('utm-campaign').value.trim();
  const utmContent = document.getElementById('utm-content').value.trim();
  return {
    name: document.getElementById('email-name').value.trim(),
    subject: document.getElementById('subject').value.trim(),
    preheader: document.getElementById('preheader').value.trim(),
    from_name: document.getElementById('from-name').value.trim(),
    from_email: document.getElementById('from-email').value.trim(),
    reply_to: document.getElementById('reply-to').value.trim(),
    body_html: document.getElementById('body-html').value.trim(),
    subscription_type_id: document.getElementById('subscription-type').value,
    utm_spec: utmCampaign ? {
      source: 'hubspot',
      medium: 'email',
      campaign: utmCampaign,
      content: utmContent,
      term: '',
    } : null,
    audience_list_ids: state.audienceLists.map(l => String(l.list_id)),
    suppression_list_ids: state.suppressionLists.map(l => String(l.list_id)),
  };
}

// ── Run QA ────────────────────────────────────────────────────────────────────

function renderQAReport(report) {
  const container = document.getElementById('qa-result-container');
  container.classList.remove('hidden');

  const verdict = report.verdict;
  const verdictEl = document.getElementById('qa-verdict-banner');
  verdictEl.textContent = `${verdict === 'READY_TO_SEND' ? '✅' : verdict === 'NEEDS_CHANGES' ? '⚠️' : '🚫'} ${report.summary}`;
  verdictEl.className = 'verdict-banner ' + { READY_TO_SEND: 'ready', NEEDS_CHANGES: 'needs', BLOCKED: 'blocked' }[verdict];

  // Checks table
  const tableEl = document.getElementById('qa-checks-table');
  const rows = (report.checks || []).map(c =>
    `<tr>
      <td>${c.section}</td>
      <td>${c.check}</td>
      <td class="status-${c.status}">${statusIcon(c.status)}</td>
      <td>${c.issue || '—'}</td>
      <td class="${severityClass(c.severity)}">${c.severity || '—'}</td>
      <td>${c.fix || '—'}</td>
    </tr>`
  ).join('');
  tableEl.innerHTML = `
    <div class="card" style="overflow-x:auto">
      <table class="qa-table">
        <thead>
          <tr>
            <th>Section</th><th>Check</th><th>Status</th>
            <th>Issue</th><th>Severity</th><th>Fix</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;

  // Action plan
  const planEl = document.getElementById('qa-action-plan');
  const claudeFixes = (report.claude_can_fix || []).map(f => `<li>${f}</li>`).join('');
  const manualFixes = (report.manual_actions || []).map(f => `<li>${f}</li>`).join('');
  planEl.innerHTML = `
    <h2>Action Plan</h2>
    ${claudeFixes ? `<p style="margin-bottom:0.4rem"><strong>Claude can fix:</strong></p><ul style="margin-left:1.2rem;font-size:13px">${claudeFixes}</ul>` : ''}
    ${manualFixes ? `<p style="margin:0.6rem 0 0.4rem"><strong>You need to do manually:</strong></p><ul style="margin-left:1.2rem;font-size:13px">${manualFixes}</ul>` : ''}
    ${!claudeFixes && !manualFixes ? '<p style="color:#38a169;font-size:13px">No action items — all checks passed.</p>' : ''}
  `;
}

document.getElementById('btn-run-qa').addEventListener('click', async () => {
  const spec = buildDraftSpec();
  showResult('compose-result', 'info', 'Running QA…');
  try {
    const res = await api('POST', '/api/hubspot/emails/qa', {
      draft: spec,
      audience_list_ids: spec.audience_list_ids,
      suppression_list_ids: spec.suppression_list_ids,
    });
    if (res.success) {
      showResult('compose-result', res.data.verdict === 'READY_TO_SEND' ? 'success' : 'error',
        `QA Verdict: ${res.data.verdict} — ${res.data.summary}. See QA Review tab for details.`);
      renderQAReport(res.data);
      // Switch to QA tab
      document.querySelector('[data-tab="qa"]').click();
    } else {
      showResult('compose-result', 'error', 'QA error: ' + (res.error || 'Unknown error'));
    }
  } catch (e) {
    showResult('compose-result', 'error', 'Network error: ' + e.message);
  }
});

document.getElementById('btn-qa-from-compose').addEventListener('click', () => {
  document.querySelector('[data-tab="compose"]').click();
  document.getElementById('btn-run-qa').click();
});

// ── Create Draft ──────────────────────────────────────────────────────────────

document.getElementById('btn-create-draft').addEventListener('click', async () => {
  const spec = buildDraftSpec();

  // Client-side guard: require subscription type
  if (!spec.subscription_type_id) {
    showResult('compose-result', 'error', '⚠️ Select a subscription type before creating the draft.');
    return;
  }
  if (!spec.name || !spec.subject || !spec.from_email || !spec.body_html) {
    showResult('compose-result', 'error', '⚠️ Fill in all required fields (name, subject, from email, body).');
    return;
  }

  showResult('compose-result', 'info', 'Creating draft…');
  try {
    const res = await api('POST', '/api/hubspot/emails', spec);
    if (res.success) {
      const d = res.data;
      const warnHtml = d.warnings?.length
        ? `<br><br>⚠️ Warnings (${d.warnings.length}):<br>` + d.warnings.map(w => `• ${w.issue}`).join('<br>')
        : '';
      showResult('compose-result', 'success',
        `✅ Draft created: <a href="${d.hubspot_url}" target="_blank">${d.name}</a>${warnHtml}`);
    } else {
      const issues = res.data?.issues?.map(i => `• [${i.severity}] ${i.issue}`).join('\n') || '';
      showResult('compose-result', 'error', `❌ ${res.error}\n${issues}`);
    }
  } catch (e) {
    showResult('compose-result', 'error', 'Network error: ' + e.message);
  }
});

// ── Reset Compose ─────────────────────────────────────────────────────────────

document.getElementById('btn-reset-compose').addEventListener('click', () => {
  ['email-name','subject','preheader','from-name','from-email','reply-to','body-html','utm-campaign','utm-content']
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  document.getElementById('subscription-type').selectedIndex = 0;
  state.audienceLists = [];
  state.suppressionLists = [];
  renderSelectedLists('audience-selected', []);
  renderSelectedLists('suppression-selected', []);
  document.getElementById('compose-result').className = 'result-area hidden';
  document.getElementById('qa-result-container').classList.add('hidden');
});

// ── Drafts Tab ────────────────────────────────────────────────────────────────

async function loadDrafts(query = '') {
  const list = document.getElementById('drafts-list');
  list.innerHTML = '<p class="empty-hint">Loading…</p>';
  try {
    const res = await api('GET', `/api/hubspot/emails?q=${encodeURIComponent(query)}&limit=30`);
    if (!res.success || !res.data?.length) {
      list.innerHTML = '<p class="empty-hint">No drafts found.</p>';
      return;
    }
    list.innerHTML = res.data.map(d =>
      `<div class="draft-row" data-id="${d.id}" data-name="${d.name}">
        <div class="draft-info">
          <div class="draft-name">${d.name}</div>
          <div class="draft-subject">${d.subject || '(no subject)'}</div>
          <div class="draft-meta">Status: ${d.status} · Updated: ${d.updated_at ? new Date(d.updated_at).toLocaleDateString() : '—'}</div>
        </div>
        <div class="draft-actions">
          <a href="${d.hubspot_url}" target="_blank" class="btn-secondary" style="padding:0.3rem 0.6rem;font-size:12px">Open ↗</a>
          <button class="btn-danger btn-delete-draft" data-id="${d.id}" data-name="${d.name}" style="padding:0.3rem 0.6rem;font-size:12px">Delete</button>
        </div>
      </div>`
    ).join('');

    list.querySelectorAll('.btn-delete-draft').forEach(btn => {
      btn.addEventListener('click', () => {
        state.pendingDeleteId = btn.dataset.id;
        state.pendingDeleteName = btn.dataset.name;
        document.getElementById('delete-confirm-card').style.display = 'block';
        document.getElementById('delete-confirm-checkbox').checked = false;
        document.getElementById('btn-delete-draft').disabled = true;
        document.getElementById('delete-result').className = 'result-area hidden';
        window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
      });
    });
  } catch (e) {
    list.innerHTML = `<p class="empty-hint" style="color:#e53e3e">Error loading drafts: ${e.message}</p>`;
  }
}

document.getElementById('btn-drafts-refresh').addEventListener('click', () => loadDrafts());
document.getElementById('btn-drafts-search').addEventListener('click', () => {
  loadDrafts(document.getElementById('drafts-search').value.trim());
});

document.getElementById('delete-confirm-checkbox').addEventListener('change', e => {
  document.getElementById('btn-delete-draft').disabled = !e.target.checked;
});

document.getElementById('btn-cancel-delete').addEventListener('click', () => {
  document.getElementById('delete-confirm-card').style.display = 'none';
  state.pendingDeleteId = null;
});

document.getElementById('btn-delete-draft').addEventListener('click', async () => {
  if (!state.pendingDeleteId) return;
  showResult('delete-result', 'info', 'Deleting…');
  try {
    const res = await api('DELETE',
      `/api/hubspot/emails/${state.pendingDeleteId}?confirmed_name=${encodeURIComponent(state.pendingDeleteName || '')}`
    );
    if (res.success) {
      showResult('delete-result', 'success', `✅ Deleted: ${state.pendingDeleteName}`);
      document.getElementById('delete-confirm-card').style.display = 'none';
      state.pendingDeleteId = null;
      setTimeout(() => loadDrafts(), 1200);
    } else {
      showResult('delete-result', 'error', '❌ ' + res.error);
    }
  } catch (e) {
    showResult('delete-result', 'error', 'Network error: ' + e.message);
  }
});

// ── QA — Fetch existing draft ──────────────────────────────────────────────────

document.getElementById('btn-fetch-draft-qa').addEventListener('click', async () => {
  const val = document.getElementById('qa-draft-id').value.trim();
  if (!val) return;
  try {
    const res = await api('GET', `/api/hubspot/emails/${encodeURIComponent(val)}`);
    if (res.success) {
      const draft = res.data;
      const qaRes = await api('POST', '/api/hubspot/emails/qa', {
        draft: {
          name: draft.name,
          subject: draft.subject,
          preheader: draft.preheader,
          from_name: draft.from_name,
          from_email: draft.from_email,
          reply_to: draft.reply_to,
          body_html: '',  // body not returned in list endpoint
          subscription_type_id: draft.subscription_id || '',
        },
        audience_list_ids: [],
        suppression_list_ids: [],
      });
      if (qaRes.success) renderQAReport(qaRes.data);
    } else {
      alert('Draft not found: ' + val);
    }
  } catch (e) {
    alert('Error: ' + e.message);
  }
});

// ── Initialise ────────────────────────────────────────────────────────────────

loadSubscriptionTypes();
renderSelectedLists('audience-selected', []);
renderSelectedLists('suppression-selected', []);
