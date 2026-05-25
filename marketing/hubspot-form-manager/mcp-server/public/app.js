/* HubSpot Form Manager — Web UI JavaScript */
'use strict';

// ── Utilities ─────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const show = el => { if (el) el.style.display = ''; };
const hide = el => { if (el) el.style.display = 'none'; };

async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  return res.json();
}

function showResult(el, { success, data, error }, successFn) {
  el.className = 'result-area ' + (success ? 'success' : 'error');
  if (success && successFn) {
    el.innerHTML = successFn(data);
  } else if (success) {
    el.textContent = JSON.stringify(data, null, 2);
  } else {
    el.textContent = '❌ ' + (error || 'Unknown error');
  }
}

// ── Tab switching ─────────────────────────────────────────────────────────────

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    $('tab-' + btn.dataset.tab).classList.add('active');
  });
});

// ── Modal helper ─────────────────────────────────────────────────────────────

let _modalResolve = null;
function openModal(title, bodyText) {
  return new Promise(resolve => {
    $('modal-title').textContent = title;
    $('modal-body').textContent = bodyText;
    $('confirm-modal').classList.add('open');
    _modalResolve = resolve;
  });
}
$('modal-cancel').addEventListener('click', () => {
  $('confirm-modal').classList.remove('open');
  if (_modalResolve) _modalResolve(false);
});
$('modal-confirm').addEventListener('click', () => {
  $('confirm-modal').classList.remove('open');
  if (_modalResolve) _modalResolve(true);
});

// ── Autocomplete helper ────────────────────────────────────────────────────────

function setupAutocomplete({ inputId, listId, searchFn, onSelect }) {
  const input = $(inputId);
  const list = $(listId);
  let debounce = null;

  input.addEventListener('input', () => {
    clearTimeout(debounce);
    const q = input.value.trim();
    if (q.length < 2) { hide(list); list.innerHTML = ''; return; }
    debounce = setTimeout(async () => {
      const items = await searchFn(q);
      if (!items.length) { hide(list); return; }
      list.innerHTML = items.map(it =>
        `<li data-id="${it.id}" data-name="${encodeURIComponent(it.name)}">${it.name}<br><small>${it.id}</small></li>`
      ).join('');
      show(list);
    }, 280);
  });

  list.addEventListener('click', e => {
    const li = e.target.closest('li');
    if (!li) return;
    const id = li.dataset.id;
    const name = decodeURIComponent(li.dataset.name);
    input.value = name;
    hide(list);
    list.innerHTML = '';
    onSelect(id, name);
  });

  document.addEventListener('click', e => {
    if (!input.contains(e.target) && !list.contains(e.target)) {
      hide(list); list.innerHTML = '';
    }
  });
}

// ── Field builder (HubSpot property picker) ───────────────────────────────────

let hsProperties = [];   // [{name, label, type, fieldType, groupName}]
let fieldCounter  = 0;

async function loadHubSpotProperties() {
  const loadingEl = $('fields-loading');
  try {
    const res = await api('GET', '/api/hubspot/properties');
    if (res.success && res.data.length) {
      hsProperties = res.data;
      if (loadingEl) loadingEl.style.display = 'none';
    } else {
      if (loadingEl) loadingEl.textContent = '⚠️ Could not load properties — field names will be free-text.';
    }
  } catch {
    if (loadingEl) loadingEl.textContent = '⚠️ Could not load properties — field names will be free-text.';
  }
  // Render default fields after properties are loaded
  const DEFAULTS = [
    { name: 'firstname',  label: 'First Name',    type: 'text',  required: true  },
    { name: 'lastname',   label: 'Last Name',      type: 'text',  required: true  },
    { name: 'email',      label: 'Email Address',  type: 'email', required: true  },
    { name: 'company',    label: 'Company',        type: 'text',  required: false },
  ];
  DEFAULTS.forEach(d => addField(d));
}

function addField(data = {}) {
  fieldCounter++;
  const uid = `field-${fieldCounter}`;
  const row = document.createElement('div');
  row.className = 'field-row';
  row.dataset.id = uid;

  // Build dropdown options from loaded properties, or fall back to a text input
  const useDropdown = hsProperties.length > 0;

  row.innerHTML = `
    <div class="f-prop-wrapper" style="flex:2; position:relative;">
      ${useDropdown
        ? `<input type="text" class="f-label-search" placeholder="Search property…"
              value="${data.label || data.name || ''}" autocomplete="off"
              style="width:100%">
           <input type="hidden" class="f-name" value="${data.name || ''}">
           <ul class="autocomplete-list f-prop-list" style="display:none"></ul>`
        : `<input type="text" class="f-label-search f-name" placeholder="Field name"
              value="${data.name || ''}" style="width:100%">`
      }
    </div>
    <input type="text" class="f-type-display" value="${data.type || 'text'}"
           readonly style="flex:0.8; background:#f7fafc; color:#718096; font-size:12px; cursor:default"
           title="Field type (auto-set from HubSpot property)">
    <label class="required-toggle" style="flex:0 0 auto">
      <input type="checkbox" class="f-required" ${data.required ? 'checked' : ''}> Required
    </label>
    <button type="button" class="btn-remove" title="Remove field">✕</button>
  `;

  row.querySelector('.btn-remove').addEventListener('click', () => row.remove());

  if (useDropdown) {
    const searchInput = row.querySelector('.f-label-search');
    const hiddenName  = row.querySelector('.f-name');
    const typeDisplay = row.querySelector('.f-type-display');
    const list        = row.querySelector('.f-prop-list');
    let debounce      = null;

    searchInput.addEventListener('input', () => {
      clearTimeout(debounce);
      const q = searchInput.value.trim().toLowerCase();
      if (q.length < 1) { hide(list); list.innerHTML = ''; return; }
      debounce = setTimeout(() => {
        const matches = hsProperties
          .filter(p => p.label.toLowerCase().includes(q) || p.name.toLowerCase().includes(q))
          .slice(0, 12);
        if (!matches.length) { hide(list); return; }
        list.innerHTML = matches.map(p =>
          `<li data-name="${p.name}" data-label="${encodeURIComponent(p.label)}" data-type="${p.type}">
             <span style="font-weight:500">${p.label}</span>
             <small style="color:#718096; margin-left:6px">${p.name}</small>
           </li>`
        ).join('');
        show(list);
      }, 200);
    });

    list.addEventListener('click', e => {
      const li = e.target.closest('li');
      if (!li) return;
      searchInput.value   = decodeURIComponent(li.dataset.label);
      hiddenName.value    = li.dataset.name;
      typeDisplay.value   = li.dataset.type;
      hide(list); list.innerHTML = '';
    });

    document.addEventListener('click', e => {
      if (!row.contains(e.target)) { hide(list); list.innerHTML = ''; }
    });
  }

  $('fields-list').appendChild(row);
}

$('btn-add-field').addEventListener('click', () => addField());

function getFields() {
  return Array.from($('fields-list').querySelectorAll('.field-row')).map(row => {
    const nameEl  = row.querySelector('.f-name');
    const typeEl  = row.querySelector('.f-type-display');
    const name    = nameEl ? nameEl.value.trim() : '';
    const type    = typeEl ? typeEl.value.trim() : 'text';
    const required = row.querySelector('.f-required').checked;
    return { name, type, required };
  }).filter(f => f.name);
}

// Load properties then render default fields
loadHubSpotProperties();

// ── Brand / Business Unit dropdown ────────────────────────────────────────────

async function loadBrands() {
  const sel = $('brand-select');
  const customInput = $('brand-custom');
  const hidden = $('brand');

  function syncHidden() {
    if (sel.value === '__other__') {
      hidden.value = customInput.value.trim();
    } else {
      hidden.value = sel.value;
    }
  }

  try {
    const res = await api('GET', '/api/hubspot/brands');
    const brands = res.success && res.data.brands ? res.data.brands : [];

    if (brands.length) {
      sel.innerHTML =
        '<option value="">— Select brand / business unit —</option>' +
        brands.map(b => `<option value="${b}">${b}</option>`).join('') +
        '<option value="__other__">✏️ Other (type manually)…</option>';
    } else {
      // No brands from API — fall straight to free-text
      sel.style.display = 'none';
      customInput.style.display = '';
      customInput.required = true;
      customInput.addEventListener('input', () => { hidden.value = customInput.value.trim(); });
      return;
    }
  } catch {
    sel.innerHTML = '<option value="">— Could not load brands —</option>' +
      '<option value="__other__">✏️ Type manually…</option>';
  }

  sel.addEventListener('change', () => {
    if (sel.value === '__other__') {
      customInput.style.display = '';
      customInput.required = true;
      customInput.focus();
    } else {
      customInput.style.display = 'none';
      customInput.required = false;
      customInput.value = '';
    }
    syncHidden();
  });

  customInput.addEventListener('input', syncHidden);
}
loadBrands();

// ── Subscription types dropdown ────────────────────────────────────────────────

async function loadSubscriptionTypes() {
  const sel = $('subscription-type');
  try {
    const res = await api('GET', '/api/hubspot/subscription-types');
    if (res.success && res.data.length) {
      sel.innerHTML = '<option value="">— Select subscription type —</option>' +
        res.data.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
    } else {
      sel.innerHTML = '<option value="">— Could not load types —</option>';
    }
  } catch {
    sel.innerHTML = '<option value="">— Error loading types —</option>';
  }
}
loadSubscriptionTypes();

// ── Reference form autocomplete ────────────────────────────────────────────────

setupAutocomplete({
  inputId: 'reference-form',
  listId: 'reference-form-list',
  searchFn: async q => {
    const res = await api('GET', `/api/hubspot/forms/search?q=${encodeURIComponent(q)}&limit=10`);
    return res.success ? res.data : [];
  },
  onSelect: async (id, name) => {
    $('reference-form-id').value = id;
    // Fetch the form and populate thank-you message
    const res = await api('GET', `/api/hubspot/forms/${id}`);
    if (res.success) {
      const msg = res.data?.configuration?.thankYouMessageJson?.richText || '';
      if (msg && !$('thank-you').value.trim()) {
        $('thank-you').value = msg;
      }
    }
  },
});

// ── Workflow autocomplete ──────────────────────────────────────────────────────

setupAutocomplete({
  inputId: 'workflow-search',
  listId: 'workflow-list',
  searchFn: async q => {
    const res = await api('GET', `/api/hubspot/workflows/search?q=${encodeURIComponent(q)}`);
    return res.success ? res.data : [];
  },
  onSelect: (id, name) => {
    $('workflow-id').value = id;
    $('workflow-name').value = name;
  },
});

// ── Asana pre-fill ─────────────────────────────────────────────────────────────

$('btn-prefill').addEventListener('click', async () => {
  const url = $('asana-url').value.trim();
  if (!url) return;
  const btn = $('btn-prefill');
  btn.textContent = 'Loading…';
  btn.disabled = true;

  try {
    const res = await api('POST', '/api/asana/task', { url });
    const banner = $('prefill-banner');
    if (!res.success) {
      banner.className = 'hint-banner';
      banner.style.background = '#fff1f1';
      banner.textContent = '❌ ' + res.error;
      show(banner);
      return;
    }

    const { data } = res;
    const p = data.prefill || {};
    const hints = [];

    if (p.form_name_hint) {
      $('form-name').value = p.form_name_hint;
      hints.push(`Form name: ${p.form_name_hint}`);
    }
    if (p.from_address_hint) {
      $('ar-from-email').value = p.from_address_hint;
      hints.push(`From address: ${p.from_address_hint}`);
    }
    if (p.workflow_hint) {
      $('workflow-search').value = p.workflow_hint;
      hints.push(`Workflow: ${p.workflow_hint} (confirm below)`);
    }
    if (p.brand_hint) {
      // Try to match the hint against the select options; fall back to "Other"
      const sel = $('brand-select');
      const customInput = $('brand-custom');
      const matched = sel ? Array.from(sel.options).find(o => o.value.toLowerCase() === p.brand_hint.toLowerCase()) : null;
      if (sel && matched) {
        sel.value = matched.value;
        $('brand').value = matched.value;
        if (customInput) { customInput.style.display = 'none'; customInput.value = ''; }
      } else if (sel) {
        sel.value = '__other__';
        if (customInput) { customInput.style.display = ''; customInput.value = p.brand_hint; }
        $('brand').value = p.brand_hint;
      } else {
        $('brand').value = p.brand_hint;
      }
      hints.push(`Brand hint: ${p.brand_hint} ⚠️ confirm this`);
    }

    banner.innerHTML = `
      <strong>✅ Pre-filled from Asana: "${data.name}"</strong><br>
      ${hints.length ? hints.map(h => `• ${h}`).join('<br>') : 'No matching fields detected.'}<br>
      <em style="color:#b45309">These are suggestions — review and confirm all fields before creating the form.</em>
    `;
    banner.style.background = '#fffbf0';
    show(banner);
  } catch (err) {
    alert('Error fetching Asana task: ' + err.message);
  } finally {
    btn.textContent = 'Pre-fill';
    btn.disabled = false;
  }
});

// ── Create Form ────────────────────────────────────────────────────────────────

$('btn-create-form').addEventListener('click', async () => {
  const brand = $('brand').value.trim();
  const formName = $('form-name').value.trim();
  const subscriptionTypeId = $('subscription-type').value;
  const result = $('create-result');

  if (!brand) {
    result.className = 'result-area error';
    result.textContent = '❌ Brand / Business Unit is required.';
    return;
  }
  if (!formName) {
    result.className = 'result-area error';
    result.textContent = '❌ Form name is required.';
    return;
  }
  if (!subscriptionTypeId) {
    result.className = 'result-area error';
    result.textContent = '❌ Please select a subscription type.';
    return;
  }

  const fields = getFields();
  if (!fields.length) {
    result.className = 'result-area error';
    result.textContent = '❌ Add at least one field.';
    return;
  }

  // Show confirmation modal
  const confirmText = [
    `Form name:     ${formName}`,
    `Brand:         ${brand}`,
    `Fields:        ${fields.map(f => f.name + (f.required ? '*' : '')).join(', ')}`,
    `Subscription:  ${$('subscription-type').options[$('subscription-type').selectedIndex].text}`,
    `Notifications: ${$('notification-emails').value.trim() || 'none'}`,
    $('ar-subject').value.trim() ? `Autoresponder: ${$('ar-subject').value.trim()}` : '',
    $('workflow-name').value ? `Workflow:      ${$('workflow-name').value}` : '',
  ].filter(Boolean).join('\n');

  const confirmed = await openModal('Confirm Form Creation', confirmText);
  if (!confirmed) return;

  const btn = $('btn-create-form');
  btn.disabled = true;
  btn.textContent = 'Creating…';
  result.className = 'result-area info';
  result.textContent = 'Creating form…';

  try {
    const payload = {
      name: formName,
      brand,
      fields,
      submit_button_text: $('submit-text').value.trim() || 'Submit',
      thank_you_message: $('thank-you').value.trim() || 'Thank you for your submission.',
      subscription_type_id: subscriptionTypeId,
      notification_emails: $('notification-emails').value
        .split(',').map(e => e.trim()).filter(Boolean),
    };

    if ($('ar-subject').value.trim()) {
      payload.autoresponder_subject = $('ar-subject').value.trim();
      payload.autoresponder_from_name = $('ar-from-name').value.trim();
      payload.autoresponder_from_email = $('ar-from-email').value.trim();
      payload.autoresponder_body_html = $('ar-body').value.trim();
    }

    if ($('workflow-name').value) {
      payload.workflow_name_query = $('workflow-name').value;
    }

    const res = await api('POST', '/api/hubspot/forms/create', payload);
    showResult(result, res, data => `
✅ Form created successfully!

📋 Form name:      ${data.form_name}
🏷️  Brand:          ${data.brand}
🔗 HubSpot URL:    <a href="${data.hubspot_form_url}" target="_blank">${data.hubspot_form_url}</a>
${data.email_preview_url ? `📧 Autoresponder:  <a href="${data.email_preview_url}" target="_blank">${data.email_preview_url}</a>` : ''}
${data.workflow_status ? `⚙️  Workflow:        ${data.workflow_status}` : ''}
    `.trim());
  } catch (err) {
    result.className = 'result-area error';
    result.textContent = '❌ Network error: ' + err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create Form';
  }
});

$('btn-reset-create').addEventListener('click', () => {
  ['brand','form-name','submit-text','thank-you','notification-emails',
   'ar-subject','ar-from-name','ar-from-email','ar-body',
   'workflow-search','workflow-id','workflow-name','asana-url','reference-form','reference-form-id']
    .forEach(id => { const el = $(id); if (el) el.value = ''; });
  // Reset brand select back to placeholder
  const sel = $('brand-select');
  if (sel) sel.selectedIndex = 0;
  const cust = $('brand-custom');
  if (cust) { cust.value = ''; cust.style.display = 'none'; }
  hide($('prefill-banner'));
  $('fields-list').innerHTML = '';
  fieldCounter = 0;
  [
    { name: 'firstname', label: 'First Name',   type: 'text',  required: true  },
    { name: 'lastname',  label: 'Last Name',     type: 'text',  required: true  },
    { name: 'email',     label: 'Email Address', type: 'email', required: true  },
    { name: 'company',   label: 'Company',       type: 'text',  required: false },
  ].forEach(d => addField(d));
  $('create-result').className = 'result-area hidden';
});

// ── Delete Forms ──────────────────────────────────────────────────────────────

let deleteResults = [];

async function runDeleteSearch() {
  const q = $('delete-search').value.trim();
  const list = $('delete-checklist');
  const card = $('delete-confirm-card');
  if (!q) return;

  list.innerHTML = '<p style="color:#718096; font-size:13px">Searching…</p>';
  const res = await api('GET', `/api/hubspot/forms/search?q=${encodeURIComponent(q)}&limit=30`);

  if (!res.success || !res.data.length) {
    list.innerHTML = '<p style="color:#718096; font-size:13px">No forms found matching your search.</p>';
    hide(card);
    return;
  }

  deleteResults = res.data;
  list.innerHTML = res.data.map(f => `
    <label class="form-check-item" data-id="${f.id}" data-name="${encodeURIComponent(f.name)}">
      <input type="checkbox" class="del-check" value="${f.id}">
      <span style="flex:1">
        <strong>${f.name}</strong><br>
        <small>${f.id}</small>
      </span>
    </label>
  `).join('');

  show(card);
  updateDeleteCount();

  list.querySelectorAll('.del-check').forEach(cb => {
    cb.addEventListener('change', updateDeleteCount);
  });
}

function updateDeleteCount() {
  const checked = document.querySelectorAll('.del-check:checked').length;
  $('delete-selected-count').textContent = checked ? `${checked} form(s) selected` : '';
  const btn = $('btn-delete-forms');
  btn.disabled = !(checked > 0 && $('delete-confirm-checkbox').checked);
}

$('btn-delete-search').addEventListener('click', runDeleteSearch);
$('delete-search').addEventListener('keydown', e => { if (e.key === 'Enter') runDeleteSearch(); });
$('delete-confirm-checkbox').addEventListener('change', updateDeleteCount);

$('btn-delete-forms').addEventListener('click', async () => {
  const checked = Array.from(document.querySelectorAll('.del-check:checked'));
  if (!checked.length) return;

  const formIds = checked.map(cb => cb.value);
  const formNames = checked.map(cb => {
    const label = cb.closest('label');
    return decodeURIComponent(label?.dataset.name || cb.value);
  });

  const confirmText = `PERMANENTLY DELETE ${formIds.length} form(s):\n\n${formNames.join('\n')}\n\nThis cannot be undone.`;
  const confirmed = await openModal('⚠️ Confirm Permanent Deletion', confirmText);
  if (!confirmed) return;

  const btn = $('btn-delete-forms');
  const result = $('delete-result');
  btn.disabled = true;
  btn.textContent = 'Deleting…';
  result.className = 'result-area info';
  result.textContent = 'Deleting forms…';

  try {
    const res = await api('POST', '/api/hubspot/forms/delete', {
      form_ids: formIds,
      confirmed_names: formNames,
    });
    showResult(result, res, data => {
      return data.map(r =>
        r.status === 'deleted' ? `✅ Deleted: ${r.name}` :
        r.status === 'not_found' ? `⚠️ Not found: ${r.name}` :
        `❌ Error: ${r.name} — ${r.error}`
      ).join('\n');
    });
  } catch (err) {
    result.className = 'result-area error';
    result.textContent = '❌ Network error: ' + err.message;
  } finally {
    btn.textContent = '🗑️ Delete Selected Forms';
    updateDeleteCount();
  }
});

// ── Disable Notifications ─────────────────────────────────────────────────────

let notifResults = [];

async function runNotifSearch() {
  const q = $('notif-search').value.trim();
  const list = $('notif-checklist');
  const card = $('notif-action-card');
  if (!q) return;

  list.innerHTML = '<p style="color:#718096; font-size:13px">Searching…</p>';
  const res = await api('GET', `/api/hubspot/forms/search?q=${encodeURIComponent(q)}&limit=30`);

  if (!res.success || !res.data.length) {
    list.innerHTML = '<p style="color:#718096; font-size:13px">No forms found.</p>';
    hide(card);
    return;
  }

  notifResults = res.data;
  list.innerHTML = res.data.map(f => `
    <label class="form-check-item" data-id="${f.id}" data-name="${encodeURIComponent(f.name)}">
      <input type="checkbox" class="notif-check" value="${f.id}">
      <span style="flex:1">
        <strong>${f.name}</strong><br>
        <small>${f.id}</small>
      </span>
    </label>
  `).join('');

  show(card);
  updateNotifCount();
  list.querySelectorAll('.notif-check').forEach(cb => cb.addEventListener('change', updateNotifCount));
}

function updateNotifCount() {
  const checked = document.querySelectorAll('.notif-check:checked').length;
  $('notif-selected-count').textContent = checked ? `${checked} form(s) selected` : '';
}

$('btn-notif-search').addEventListener('click', runNotifSearch);
$('notif-search').addEventListener('keydown', e => { if (e.key === 'Enter') runNotifSearch(); });

$('btn-disable-notifs').addEventListener('click', async () => {
  const checked = Array.from(document.querySelectorAll('.notif-check:checked'));
  if (!checked.length) return;

  const btn = $('btn-disable-notifs');
  const result = $('notif-result');
  btn.disabled = true;
  btn.textContent = 'Updating…';
  result.className = 'result-area info';
  result.textContent = 'Disabling notifications…';

  const results = [];
  for (const cb of checked) {
    const formId = cb.value;
    const name = decodeURIComponent(cb.closest('label')?.dataset.name || formId);
    try {
      const res = await api('PATCH', '/api/hubspot/forms/notifications', {
        form_id: formId,
        notification_emails: [],
      });
      results.push(res.success ? `🔕 Disabled: ${name}` : `❌ Error: ${name} — ${res.error}`);
    } catch (err) {
      results.push(`❌ Error: ${name} — ${err.message}`);
    }
  }

  result.className = 'result-area success';
  result.textContent = results.join('\n');
  btn.disabled = false;
  btn.textContent = '🔕 Disable Notifications on Selected';
  updateNotifCount();
});
