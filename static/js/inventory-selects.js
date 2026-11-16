/* ============================================================
   inventory-selects.js — Inventory page - the cloth type / company / supplier / invoice dropdowns (with their inline 'add new'), the special-code cipher, and the Manage Companies modal.
   Part of the Inventory page; shares globals with inventory.js (load order matters:
   see inventory.html). Code moved here unchanged from the old single inventory.js.
   ============================================================ */

// ----------------------------------------------------------------
// Cloth type select + inline add
// ----------------------------------------------------------------
async function populateClothTypeSelect(selId, restoreValue) {
  try {
    const res  = await fetch('/api/cloth-types');
    const list = await res.json();
    const sel  = document.getElementById(selId);
    sel.innerHTML = '<option value="">— Select cloth type —</option>';
    list.forEach(ct => {
      const opt = document.createElement('option');
      opt.value = ct.type_name;
      opt.textContent = ct.type_name;
      sel.appendChild(opt);
    });
    const addOpt = document.createElement('option');
    addOpt.value = '__add__';
    addOpt.textContent = '+ Add new cloth type…';
    sel.appendChild(addOpt);
    if (restoreValue) sel.value = restoreValue;
  } catch (_) {}
}

async function loadClothTypesForSelect(restoreValue) {
  return populateClothTypeSelect('ai-cloth', restoreValue);
}

function onAiClothChange() {
  const sel    = document.getElementById('ai-cloth');
  const addRow = document.getElementById('ai-cloth-add-row');
  if (sel.value === '__add__') {
    addRow.style.display = '';
    document.getElementById('ai-cloth-new').focus();
  } else {
    addRow.style.display = 'none';
    loadCompaniesForSelect(sel.value);
  }
}

async function saveNewClothType() {
  const input = document.getElementById('ai-cloth-new');
  const name  = input.value.trim();
  if (!name) { input.focus(); return; }
  try {
    const res  = await fetch('/api/cloth-types', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type_name: name }),
    });
    const data = await res.json();
    if (!res.ok) { alert(data.error || 'Failed to add cloth type.'); return; }
    input.value = '';
    document.getElementById('ai-cloth-add-row').style.display = 'none';
    await loadClothTypesForSelect(data.type_name);
    loadCompaniesForSelect(data.type_name);
  } catch (e) { alert('Network error: ' + e.message); }
}

function cancelAiClothAdd() {
  document.getElementById('ai-cloth-new').value = '';
  document.getElementById('ai-cloth-add-row').style.display = 'none';
  document.getElementById('ai-cloth').value = '';
  loadCompaniesForSelect('');
}

// ----------------------------------------------------------------
// Company select + inline add
// ----------------------------------------------------------------
async function populateCompanySelect(selId, clothType, restoreValue) {
  const sel = document.getElementById(selId);
  if (!clothType) {
    sel.innerHTML = '<option value="">— Select cloth type first —</option>';
    return;
  }
  sel.innerHTML = '<option value="">— Select company —</option>';
  try {
    const res  = await fetch(`/api/companies?clothType=${encodeURIComponent(clothType)}`);
    const list = await res.json();
    list.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.company_name;
      opt.textContent = c.company_name;
      sel.appendChild(opt);
    });
    const addOpt = document.createElement('option');
    addOpt.value = '__add__';
    addOpt.textContent = '+ Add new company…';
    sel.appendChild(addOpt);
    if (restoreValue) sel.value = restoreValue;
  } catch (_) {}
}

async function loadCompaniesForSelect(clothType, restoreValue) {
  return populateCompanySelect('ai-company', clothType, restoreValue);
}

function onAiCompanyChange() {
  const sel    = document.getElementById('ai-company');
  const addRow = document.getElementById('ai-company-add-row');
  if (sel.value === '__add__') {
    addRow.style.display = '';
    document.getElementById('ai-company-new').focus();
  } else {
    addRow.style.display = 'none';
  }
}

async function saveNewCompany() {
  const cloth = document.getElementById('ai-cloth').value;
  const input = document.getElementById('ai-company-new');
  const name  = input.value.trim();
  if (!cloth || cloth === '__add__') { alert('Select a cloth type first.'); return; }
  if (!name) { input.focus(); return; }
  try {
    const res  = await fetch('/api/companies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cloth_type: cloth, company_name: name }),
    });
    const data = await res.json();
    if (!res.ok) { alert(data.error || 'Failed to add company.'); return; }
    input.value = '';
    document.getElementById('ai-company-add-row').style.display = 'none';
    await loadCompaniesForSelect(cloth, data.company_name);
  } catch (e) { alert('Network error: ' + e.message); }
}

function cancelAiCompanyAdd() {
  document.getElementById('ai-company-new').value = '';
  document.getElementById('ai-company-add-row').style.display = 'none';
  document.getElementById('ai-company').value = '';
}

// ----------------------------------------------------------------
// Supplier select + inline add
// ----------------------------------------------------------------
async function loadSuppliersForSelect(restoreId) {
  try {
    const res  = await fetch('/api/suppliers');
    const list = await res.json();

    const sel  = document.getElementById('ai-supplier');
    sel.innerHTML = '<option value="">— None —</option>';
    list.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.id;
      opt.textContent = s.name;
      sel.appendChild(opt);
    });
    const addOpt = document.createElement('option');
    addOpt.value = '__add__';
    addOpt.textContent = '+ Add new supplier…';
    sel.appendChild(addOpt);
    if (restoreId) sel.value = restoreId;

    const eiSel = document.getElementById('ei-supplier');
    eiSel.innerHTML = '<option value="">— None —</option>';
    list.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.id;
      opt.textContent = s.name;
      eiSel.appendChild(opt);
    });
  } catch (_) {}
}

function onAiSupplierChange() {
  const sel    = document.getElementById('ai-supplier');
  const addRow = document.getElementById('ai-supplier-add-row');
  if (sel.value === '__add__') {
    addRow.style.display = '';
    document.getElementById('ai-supplier-new').focus();
  } else {
    addRow.style.display = 'none';
  }
  updateAiSpecialCode();
}

// ----------------------------------------------------------------
// Special Code (RAYMONDSUI cipher)
// ----------------------------------------------------------------
const _CIPHER = 'RAYMONDSUI'; // index = digit 0-9

function _encodeCp(cp) {
  const n = Math.round(Math.abs(parseFloat(cp) || 0));
  return String(n).split('').map(d => _CIPHER[parseInt(d)]).join('');
}

function _supplierInitials(name) {
  return (name || '').trim().split(/\s+/).filter(Boolean)
    .map(w => w[0].toUpperCase()).join('');
}

function computeSpecialCode(cp, supplierName) {
  const encoded  = _encodeCp(cp);
  const initials = _supplierInitials(supplierName);
  return initials ? `${initials}-${encoded}` : encoded;
}

function updateAiSpecialCode() {
  const cp = document.getElementById('ai-cp').value;

  // Prefer directly selected supplier; fall back to invoice's supplier
  const supSel = document.getElementById('ai-supplier');
  const supOpt = supSel.options[supSel.selectedIndex];
  let supName  = (supSel.value && supSel.value !== '__add__') ? (supOpt ? supOpt.textContent : '') : '';

  if (!supName) {
    const invSel = document.getElementById('ai-invoice');
    const invOpt = invSel.options[invSel.selectedIndex];
    supName = (invSel.value && invOpt) ? (invOpt.dataset.supplierName || '') : '';
  }

  document.getElementById('ai-special-code').value = computeSpecialCode(cp, supName) || '';
}

async function saveNewSupplier() {
  const input = document.getElementById('ai-supplier-new');
  const name  = input.value.trim();
  if (!name) { input.focus(); return; }
  try {
    const res  = await fetch('/api/suppliers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (!res.ok) { alert(data.error || 'Failed to add supplier.'); return; }
    input.value = '';
    document.getElementById('ai-supplier-add-row').style.display = 'none';
    await loadSuppliersForSelect(data.id);
  } catch (e) { alert('Network error: ' + e.message); }
}

function cancelAiSupplierAdd() {
  document.getElementById('ai-supplier-new').value = '';
  document.getElementById('ai-supplier-add-row').style.display = 'none';
  document.getElementById('ai-supplier').value = '';
}

// ----------------------------------------------------------------
// Invoice select
// ----------------------------------------------------------------
async function loadInvoicesForSelect(restoreId) {
  try {
    const res  = await fetch('/api/invoices');
    const list = await res.json();
    const sel  = document.getElementById('ai-invoice');
    const prev = sel.value;
    sel.innerHTML = '<option value="">— No Invoice —</option>';
    list.forEach(inv => {
      const opt = document.createElement('option');
      opt.value = inv.id;
      opt.textContent = `${inv.invoice_number} (${inv.invoice_date})${inv.supplier_name ? ' — ' + inv.supplier_name : ''}`;
      opt.dataset.supplierName  = inv.supplier_name  || '';
      opt.dataset.supplierId    = inv.supplier_id    || '';
      opt.dataset.invoiceNumber = inv.invoice_number || '';
      opt.dataset.invoiceDate   = inv.invoice_date   || '';
      sel.appendChild(opt);
    });
    if (restoreId) sel.value = restoreId;
    else if (prev)  sel.value = prev;
  } catch (_) {}
}

function onAiInvoiceChange() {
  const sel        = document.getElementById('ai-invoice');
  const infoEl     = document.getElementById('ai-invoice-info');
  const editFields = document.getElementById('ai-invoice-edit-fields');
  const statusEl   = document.getElementById('ai-invoice-edit-status');
  const opt        = sel.options[sel.selectedIndex];
  statusEl.textContent = '';
  if (sel.value && opt.dataset.supplierName) {
    infoEl.textContent = `Supplier: ${opt.dataset.supplierName}`;
    infoEl.style.display = '';
  } else {
    infoEl.style.display = 'none';
  }
  if (sel.value) {
    document.getElementById('ai-invoice-number-edit').value = opt.dataset.invoiceNumber || '';
    document.getElementById('ai-invoice-date-edit').value   = opt.dataset.invoiceDate   || '';
    editFields.style.display = 'grid';
  } else {
    editFields.style.display = 'none';
  }
  updateAiSpecialCode();
}

async function saveAiInvoiceEdits() {
  const sel      = document.getElementById('ai-invoice');
  const invoiceId = sel.value;
  const statusEl = document.getElementById('ai-invoice-edit-status');
  if (!invoiceId) return;

  const invNum  = document.getElementById('ai-invoice-number-edit').value.trim();
  const invDate = document.getElementById('ai-invoice-date-edit').value.trim();
  if (!invNum)  { statusEl.textContent = 'Invoice number is required.'; statusEl.className = 'text-danger'; return; }
  if (!invDate) { statusEl.textContent = 'Invoice date is required.';   statusEl.className = 'text-danger'; return; }

  statusEl.textContent = 'Saving…';
  statusEl.className = '';
  try {
    const res  = await fetch(`/api/invoices/${invoiceId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ invoice_number: invNum, invoice_date: invDate }),
    });
    const data = await res.json();
    if (!res.ok) { statusEl.textContent = data.error || 'Save failed.'; statusEl.className = 'text-danger'; return; }
    await loadInvoicesForSelect(invoiceId);
    statusEl.textContent = 'Invoice updated.';
    statusEl.className = 'text-success';
  } catch (e) {
    statusEl.textContent = 'Network error: ' + e.message;
    statusEl.className = 'text-danger';
  }
}

async function loadInvoicesForBatchSelect(restoreId) {
  try {
    const res  = await fetch('/api/invoices');
    const list = await res.json();
    const sel  = document.getElementById('ba-invoice');
    sel.innerHTML = '<option value="">— No Invoice —</option>';
    list.forEach(inv => {
      const opt = document.createElement('option');
      opt.value = inv.id;
      opt.textContent = `${inv.invoice_number} (${inv.invoice_date})${inv.supplier_name ? ' — ' + inv.supplier_name : ''}`;
      opt.dataset.supplierName = inv.supplier_name || '';
      sel.appendChild(opt);
    });
    if (restoreId) sel.value = restoreId;
  } catch (_) {}
}

function onBaInvoiceChange() {
  const sel    = document.getElementById('ba-invoice');
  const infoEl = document.getElementById('ba-invoice-info');
  const opt    = sel.options[sel.selectedIndex];
  if (sel.value && opt && opt.dataset.supplierName) {
    infoEl.textContent = `Supplier: ${opt.dataset.supplierName}`;
    infoEl.style.display = '';
  } else {
    infoEl.style.display = 'none';
  }
}

// ----------------------------------------------------------------
// Manage Companies Modal
// ----------------------------------------------------------------
async function openManageCompaniesModal() {
  document.getElementById('mc-companies-section').style.display = 'none';
  document.getElementById('mc-companies-items').innerHTML = '';
  document.getElementById('mc-new-name').value = '';
  document.getElementById('mc-error').textContent = '';

  try {
    const res  = await fetch('/api/cloth-types');
    const list = await res.json();
    const sel  = document.getElementById('mc-cloth');
    sel.innerHTML = '<option value="">— Select cloth type —</option>';
    list.forEach(ct => {
      const opt = document.createElement('option');
      opt.value = ct.type_name;
      opt.textContent = ct.type_name;
      sel.appendChild(opt);
    });
  } catch (_) {}

  document.getElementById('manage-companies-modal').classList.remove('hidden');
}

function closeManageCompaniesModal() {
  document.getElementById('manage-companies-modal').classList.add('hidden');
}

async function onMcClothChange() {
  const cloth   = document.getElementById('mc-cloth').value;
  const section = document.getElementById('mc-companies-section');
  const errEl   = document.getElementById('mc-error');

  document.getElementById('mc-new-name').value = '';
  errEl.textContent = '';
  section.style.display = 'none';
  if (!cloth) return;

  try {
    const res  = await fetch(`/api/companies?clothType=${encodeURIComponent(cloth)}`);
    const list = await res.json();
    renderMcCompanies(list);
    section.style.display = '';
  } catch (e) {
    errEl.textContent = 'Failed to load: ' + e.message;
  }
}

function renderMcCompanies(list) {
  const el = document.getElementById('mc-companies-items');
  if (!list.length) {
    el.innerHTML = '<div style="font-size:13px;color:var(--text-muted);padding:4px 0;">No companies yet.</div>';
    return;
  }
  el.innerHTML = '';
  list.forEach(c => {
    const row = document.createElement('div');
    row.id = `mc-company-${c.id}`;
    row.dataset.name = c.company_name;
    row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);';
    row.innerHTML = `
      <span style="flex:1;font-size:14px;">${esc(c.company_name)}</span>
      <button type="button" class="btn btn-sm" style="color:var(--danger);" onclick="deleteMcCompany(${c.id})">Delete</button>
    `;
    el.appendChild(row);
  });
}

async function deleteMcCompany(id) {
  const rowEl = document.getElementById(`mc-company-${id}`);
  const name  = rowEl ? rowEl.dataset.name : 'this company';
  if (!confirm(`Delete company "${name}"?\n\nIt will be removed from dropdowns. Existing bills and inventory items using this company name are not affected.`)) return;
  const errEl = document.getElementById('mc-error');
  errEl.textContent = '';
  try {
    const res  = await fetch(`/api/companies/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error || 'Delete failed.'; return; }
    const rowEl = document.getElementById(`mc-company-${id}`);
    if (rowEl) rowEl.remove();
    const remaining = document.querySelectorAll('[id^="mc-company-"]').length;
    if (!remaining) {
      document.getElementById('mc-companies-items').innerHTML =
        '<div style="font-size:13px;color:var(--text-muted);padding:4px 0;">No companies yet.</div>';
    }
    const cloth = document.getElementById('mc-cloth').value;
    const aiCloth = document.getElementById('ai-cloth').value;
    if (aiCloth === cloth) loadCompaniesForSelect(cloth);
  } catch (e) {
    errEl.textContent = 'Network error: ' + e.message;
  }
}

async function saveMcNewCompany() {
  const cloth = document.getElementById('mc-cloth').value;
  const input = document.getElementById('mc-new-name');
  const name  = input.value.trim();
  const errEl = document.getElementById('mc-error');

  errEl.textContent = '';
  if (!name) { input.focus(); return; }
  try {
    const res  = await fetch('/api/companies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cloth_type: cloth, company_name: name }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error || 'Failed to add company.'; return; }
    input.value = '';
    await onMcClothChange();
    const aiCloth = document.getElementById('ai-cloth').value;
    if (aiCloth === cloth) loadCompaniesForSelect(cloth);
  } catch (e) { errEl.textContent = 'Network error: ' + e.message; }
}

document.getElementById('manage-companies-modal').addEventListener('click', function(e) {
  if (e.target === this) closeManageCompaniesModal();
});

