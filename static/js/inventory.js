/* ============================================================
   inventory.js — Inventory management page
   ============================================================ */

let allItems = [];

const SECTIONS = ['Shirting', 'Suiting', 'Readymade', 'Gift Sets', 'Accessories'];

function sKey(name) {
  return 'sec_' + name.replace(/\s+/g, '_');
}

// ----------------------------------------------------------------
// Init
// ----------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  loadInventory();
  loadClothTypesForSelect();
  loadCsClothTypesForSelect();
  loadSuppliersForSelect();
});

async function loadInventory() {
  setLoading(true);
  try {
    const res = await fetch('/api/inventory');
    allItems = await res.json();
    renderSections(allItems);
    renderStats(allItems);
  } catch (e) {
    showError('Failed to load inventory: ' + e.message);
  } finally {
    setLoading(false);
  }
}

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

async function loadCsClothTypesForSelect(restoreValue) {
  return populateClothTypeSelect('cs-cloth', restoreValue);
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

async function loadCsCompaniesForSelect(clothType, restoreValue) {
  return populateCompanySelect('cs-company', clothType, restoreValue);
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
// CS QR modal — cloth type + company selects
// ----------------------------------------------------------------
function onCsClothChange() {
  const sel    = document.getElementById('cs-cloth');
  const addRow = document.getElementById('cs-cloth-add-row');
  if (sel.value === '__add__') {
    addRow.style.display = '';
    document.getElementById('cs-cloth-new').focus();
  } else {
    addRow.style.display = 'none';
    loadCsCompaniesForSelect(sel.value);
  }
}

async function saveCsNewClothType() {
  const input = document.getElementById('cs-cloth-new');
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
    document.getElementById('cs-cloth-add-row').style.display = 'none';
    await Promise.all([
      loadCsClothTypesForSelect(data.type_name),
      loadClothTypesForSelect(),
    ]);
    loadCsCompaniesForSelect(data.type_name);
  } catch (e) { alert('Network error: ' + e.message); }
}

function cancelCsClothAdd() {
  document.getElementById('cs-cloth-new').value = '';
  document.getElementById('cs-cloth-add-row').style.display = 'none';
  document.getElementById('cs-cloth').value = '';
  loadCsCompaniesForSelect('');
}

function onCsCompanyChange() {
  const sel    = document.getElementById('cs-company');
  const addRow = document.getElementById('cs-company-add-row');
  if (sel.value === '__add__') {
    addRow.style.display = '';
    document.getElementById('cs-company-new').focus();
  } else {
    addRow.style.display = 'none';
  }
}

async function saveCsNewCompany() {
  const cloth = document.getElementById('cs-cloth').value;
  const input = document.getElementById('cs-company-new');
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
    document.getElementById('cs-company-add-row').style.display = 'none';
    await loadCsCompaniesForSelect(cloth, data.company_name);
    const aiCloth = document.getElementById('ai-cloth').value;
    if (aiCloth === cloth) await loadCompaniesForSelect(cloth);
  } catch (e) { alert('Network error: ' + e.message); }
}

function cancelCsCompanyAdd() {
  document.getElementById('cs-company-new').value = '';
  document.getElementById('cs-company-add-row').style.display = 'none';
  document.getElementById('cs-company').value = '';
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
// Render
// ----------------------------------------------------------------
function renderStats(items) {
  const total    = items.length;
  const negative = items.filter(i => i.current_stock < 0).length;
  const low      = items.filter(i => i.current_stock >= 0 && i.current_stock <= i.min_stock_alert).length;
  const instock  = total - negative - low;

  document.getElementById('stat-total').textContent    = total;
  document.getElementById('stat-instock').textContent  = instock;
  document.getElementById('stat-low').textContent      = low;
  document.getElementById('stat-negative').textContent = negative;
}

function renderSections(items) {
  const container = document.getElementById('sections-container');
  const emptyEl   = document.getElementById('inv-empty');
  container.innerHTML = '';

  if (!items.length) {
    emptyEl.style.display = '';
    return;
  }
  emptyEl.style.display = 'none';

  const groups = {};
  SECTIONS.forEach(s => { groups[s] = []; });
  groups['Others'] = [];

  items.forEach(item => {
    const key = SECTIONS.includes(item.cloth_type) ? item.cloth_type : 'Others';
    groups[key].push(item);
  });

  [...SECTIONS, 'Others'].forEach(section => {
    const sectionItems = groups[section];
    if (!sectionItems.length) return;

    const sid      = sKey(section);
    const isOthers = section === 'Others';
    const lowCount = sectionItems.filter(i => i.current_stock < 0 || i.current_stock <= i.min_stock_alert).length;
    const alertBadge = lowCount > 0
      ? `<span style="font-size:12px;background:#fffbeb;color:#f59e0b;padding:2px 8px;border-radius:10px;margin-left:8px;">${lowCount} alert${lowCount !== 1 ? 's' : ''}</span>`
      : '';

    const rows = sectionItems.map(item => {
      const code = item.item_code || `#${item.id}`;
      const stockClass = item.current_stock < 0
        ? 'style="color:var(--danger,#ef4444);font-weight:700;"'
        : item.current_stock <= item.min_stock_alert
          ? 'style="color:var(--warning,#f59e0b);font-weight:700;"'
          : '';
      const stockBadge = item.current_stock < 0
        ? `<span style="font-size:10px;background:#fef2f2;color:#ef4444;padding:1px 5px;border-radius:4px;margin-left:4px;">NEG</span>`
        : item.current_stock <= item.min_stock_alert
          ? `<span style="font-size:10px;background:#fffbeb;color:#f59e0b;padding:1px 5px;border-radius:4px;margin-left:4px;">LOW</span>`
          : '';
      const clothCol    = isOthers ? `<td>${esc(item.cloth_type)}</td>` : '';
      const supplierCell = item.supplier_name
        ? `<td style="font-size:12px;">${esc(item.supplier_name)}</td>`
        : `<td style="color:var(--text-muted);font-size:12px;">—</td>`;
      return `<tr data-id="${item.id}">
        <td style="text-align:center;font-weight:700;color:var(--text-muted);font-size:12px;white-space:nowrap;">${esc(code)}</td>
        ${clothCol}
        <td>${esc(item.company_name)}</td>
        ${supplierCell}
        <td>${esc(item.quality_number) || '<span style="color:var(--text-muted);">—</span>'}</td>
        <td>${esc(item.unit_label)}</td>
        <td class="text-right">&#8377;${Number(item.mrp).toFixed(2)}</td>
        <td class="text-right" ${stockClass}>${Number(item.current_stock).toFixed(2)}${stockBadge}</td>
        <td class="text-right">${Number(item.min_stock_alert).toFixed(2)}</td>
        <td style="text-align:center;white-space:nowrap;">
          <button class="btn btn-sm btn-secondary" onclick="openQrViewModal(${item.id})" title="QR">&#128246; QR</button>
          <button class="btn btn-sm btn-secondary" onclick="openRestockModal(${item.id})" title="Restock" style="margin-left:4px;">&#8679; Stock</button>
          <button class="btn btn-sm btn-secondary" onclick="openAdjustModal(${item.id})" title="Adjust" style="margin-left:4px;">&#8651; Adjust</button>
          <button class="btn btn-sm btn-secondary" onclick="openTxnModal(${item.id})" title="History" style="margin-left:4px;">&#128196;</button>
          <button class="btn btn-sm btn-secondary" onclick="openEditItemModal(${item.id})" title="Edit" style="margin-left:4px;">&#9998;</button>
          <button class="btn btn-sm" style="margin-left:4px;color:var(--danger,#ef4444);" onclick="deleteItem(${item.id})" title="Delete">&#215;</button>
        </td>
      </tr>`;
    }).join('');

    const card = document.createElement('div');
    card.className = 'card';
    card.style.marginBottom = '12px';
    card.innerHTML = `
      <div class="card-header" style="cursor:pointer;user-select:none;" onclick="toggleSection('${sid}')">
        <span class="card-title">${esc(section)}</span>
        <span style="font-size:13px;color:var(--text-muted);margin-left:8px;">${sectionItems.length} item${sectionItems.length !== 1 ? 's' : ''}</span>
        ${alertBadge}
        <span id="toggle-${sid}" style="margin-left:auto;color:var(--text-muted);font-size:13px;">&#9650;</span>
      </div>
      <div id="body-${sid}" style="overflow-x:auto;">
        <table class="items-table">
          <thead>
            <tr>
              <th style="width:80px;text-align:center;">ID</th>
              ${isOthers ? '<th>Cloth Type</th>' : ''}
              <th>Company</th>
              <th>Supplier</th>
              <th>Quality No.</th>
              <th>Unit</th>
              <th class="text-right">MRP (&#8377;)</th>
              <th class="text-right">Stock</th>
              <th class="text-right">Alert</th>
              <th style="text-align:center;">Actions</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
    container.appendChild(card);
  });
}

function toggleSection(sid) {
  const body   = document.getElementById('body-' + sid);
  const toggle = document.getElementById('toggle-' + sid);
  if (!body) return;
  const collapsed = body.style.display === 'none';
  body.style.display = collapsed ? '' : 'none';
  toggle.innerHTML   = collapsed ? '&#9650;' : '&#9660;';
}

function esc(str) {
  return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function setLoading(on) {
  document.getElementById('inv-loading').style.display = on ? '' : 'none';
  if (on) {
    document.getElementById('sections-container').innerHTML = '';
    document.getElementById('inv-empty').style.display = 'none';
  }
}

function showError(msg) {
  document.getElementById('inv-empty').textContent = msg;
  document.getElementById('inv-empty').style.display = '';
}

// ----------------------------------------------------------------
// Filter
// ----------------------------------------------------------------
function filterItems() {
  const q      = document.getElementById('filter-input').value.toLowerCase();
  const status = document.getElementById('filter-status').value;

  const filtered = allItems.filter(item => {
    const matchText = !q ||
      item.cloth_type.toLowerCase().includes(q) ||
      item.company_name.toLowerCase().includes(q) ||
      (item.quality_number || '').toLowerCase().includes(q) ||
      (item.item_code || '').toLowerCase().includes(q);

    let matchStatus = true;
    if (status === 'negative') matchStatus = item.current_stock < 0;
    else if (status === 'low')  matchStatus = item.current_stock >= 0 && item.current_stock <= item.min_stock_alert;
    else if (status === 'ok')   matchStatus = item.current_stock > item.min_stock_alert;

    return matchText && matchStatus;
  });

  renderSections(filtered);
}

// ----------------------------------------------------------------
// Add Item Modal
// ----------------------------------------------------------------
function openAddItemModal() {
  document.getElementById('ai-cloth').value   = '';
  document.getElementById('ai-company').innerHTML = '<option value="">— Select cloth type first —</option>';
  document.getElementById('ai-supplier').value = '';
  ['ai-quality','ai-mrp','ai-opening','ai-notes',
   'ai-cloth-new','ai-company-new','ai-supplier-new'].forEach(id => {
    document.getElementById(id).value = '';
  });
  ['ai-cloth-add-row','ai-company-add-row','ai-supplier-add-row'].forEach(id => {
    document.getElementById(id).style.display = 'none';
  });
  document.getElementById('ai-alert').value = '5';
  document.getElementById('ai-unit').value  = 'm';
  document.getElementById('ai-error').textContent = '';
  document.getElementById('add-item-modal').classList.remove('hidden');
  document.getElementById('ai-cloth').focus();
}

function closeAddItemModal() {
  document.getElementById('add-item-modal').classList.add('hidden');
}

async function saveNewItem() {
  const cloth      = document.getElementById('ai-cloth').value;
  const company    = document.getElementById('ai-company').value;
  const suppRaw    = document.getElementById('ai-supplier').value;
  const errEl      = document.getElementById('ai-error');
  const saveBtn    = document.getElementById('btn-ai-save');

  errEl.textContent = '';
  if (!cloth   || cloth   === '__add__') { errEl.textContent = 'Select a cloth type.'; return; }
  if (!company || company === '__add__') { errEl.textContent = 'Select a company.'; return; }

  const mrp = parseFloat(document.getElementById('ai-mrp').value);
  if (isNaN(mrp) || mrp < 0) { errEl.textContent = 'Enter a valid MRP.'; return; }

  const supplierId = (suppRaw && suppRaw !== '__add__') ? parseInt(suppRaw) : null;

  saveBtn.disabled = true;
  try {
    const res = await fetch('/api/inventory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cloth_type:      cloth,
        company_name:    company,
        quality_number:  document.getElementById('ai-quality').value.trim(),
        unit_label:      document.getElementById('ai-unit').value,
        mrp:             mrp,
        opening_stock:   parseFloat(document.getElementById('ai-opening').value) || 0,
        min_stock_alert: parseFloat(document.getElementById('ai-alert').value) || 5,
        notes:           document.getElementById('ai-notes').value.trim(),
        supplier_id:     supplierId,
      }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error || 'Save failed.'; return; }
    closeAddItemModal();
    await loadInventory();
  } catch (e) {
    errEl.textContent = 'Network error: ' + e.message;
  } finally {
    saveBtn.disabled = false;
  }
}

document.getElementById('add-item-modal').addEventListener('click', function(e) {
  if (e.target === this) closeAddItemModal();
});

// ----------------------------------------------------------------
// Edit Item Modal
// ----------------------------------------------------------------
function openEditItemModal(id) {
  const item = allItems.find(i => i.id === id);
  if (!item) return;
  document.getElementById('ei-id').value    = item.id;
  document.getElementById('ei-mrp').value   = item.mrp;
  document.getElementById('ei-alert').value = item.min_stock_alert;
  document.getElementById('ei-notes').value = item.notes || '';
  document.getElementById('ei-error').textContent = '';
  document.getElementById('edit-item-title').textContent =
    `Edit — ${item.cloth_type} / ${item.company_name}${item.quality_number ? ' / ' + item.quality_number : ''}`;
  document.getElementById('edit-item-modal').classList.remove('hidden');
}

function closeEditItemModal() {
  document.getElementById('edit-item-modal').classList.add('hidden');
}

async function saveEditItem() {
  const id    = parseInt(document.getElementById('ei-id').value);
  const errEl = document.getElementById('ei-error');
  const btn   = document.getElementById('btn-ei-save');

  errEl.textContent = '';
  btn.disabled = true;
  try {
    const res = await fetch(`/api/inventory/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mrp:             parseFloat(document.getElementById('ei-mrp').value) || 0,
        min_stock_alert: parseFloat(document.getElementById('ei-alert').value) || 5,
        notes:           document.getElementById('ei-notes').value.trim(),
      }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error || 'Save failed.'; return; }
    closeEditItemModal();
    await loadInventory();
  } catch (e) {
    errEl.textContent = 'Network error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('edit-item-modal').addEventListener('click', function(e) {
  if (e.target === this) closeEditItemModal();
});

// ----------------------------------------------------------------
// Restock Modal
// ----------------------------------------------------------------
function openRestockModal(id) {
  const item = allItems.find(i => i.id === id);
  if (!item) return;
  document.getElementById('rs-id').value = id;
  document.getElementById('rs-qty').value = '';
  document.getElementById('rs-notes').value = '';
  document.getElementById('rs-error').textContent = '';
  document.getElementById('rs-type').value = 'purchase';
  document.getElementById('restock-title').textContent =
    `Restock — ${item.cloth_type} / ${item.company_name}${item.quality_number ? ' / ' + item.quality_number : ''}`;
  document.getElementById('restock-modal').classList.remove('hidden');
  document.getElementById('rs-qty').focus();
}

function closeRestockModal() {
  document.getElementById('restock-modal').classList.add('hidden');
}

async function saveRestock() {
  const id    = parseInt(document.getElementById('rs-id').value);
  const qty   = parseFloat(document.getElementById('rs-qty').value);
  const errEl = document.getElementById('rs-error');
  const btn   = document.getElementById('btn-rs-save');

  errEl.textContent = '';
  if (isNaN(qty) || qty <= 0) { errEl.textContent = 'Enter a valid quantity.'; return; }

  btn.disabled = true;
  try {
    const res = await fetch(`/api/inventory/${id}/restock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        quantity: qty,
        txn_type: document.getElementById('rs-type').value,
        notes:    document.getElementById('rs-notes').value.trim(),
      }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error || 'Failed.'; return; }
    closeRestockModal();
    await loadInventory();
  } catch (e) {
    errEl.textContent = 'Network error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('restock-modal').addEventListener('click', function(e) {
  if (e.target === this) closeRestockModal();
});

// ----------------------------------------------------------------
// Adjust Modal
// ----------------------------------------------------------------
function openAdjustModal(id) {
  const item = allItems.find(i => i.id === id);
  if (!item) return;
  document.getElementById('adj-id').value = id;
  document.getElementById('adj-qty').value = '';
  document.getElementById('adj-notes').value = '';
  document.getElementById('adj-error').textContent = '';
  document.getElementById('adjust-title').textContent =
    `Adjust — ${item.cloth_type} / ${item.company_name} (Current: ${item.current_stock} ${item.unit_label})`;
  document.getElementById('adjust-modal').classList.remove('hidden');
  document.getElementById('adj-qty').focus();
}

function closeAdjustModal() {
  document.getElementById('adjust-modal').classList.add('hidden');
}

async function saveAdjust() {
  const id    = parseInt(document.getElementById('adj-id').value);
  const qty   = parseFloat(document.getElementById('adj-qty').value);
  const errEl = document.getElementById('adj-error');
  const btn   = document.getElementById('btn-adj-save');

  errEl.textContent = '';
  if (isNaN(qty) || qty === 0) { errEl.textContent = 'Enter a non-zero quantity.'; return; }

  btn.disabled = true;
  try {
    const res = await fetch(`/api/inventory/${id}/adjust`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        quantity: qty,
        notes:    document.getElementById('adj-notes').value.trim(),
      }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error || 'Failed.'; return; }
    closeAdjustModal();
    await loadInventory();
  } catch (e) {
    errEl.textContent = 'Network error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('adjust-modal').addEventListener('click', function(e) {
  if (e.target === this) closeAdjustModal();
});

// ----------------------------------------------------------------
// Delete
// ----------------------------------------------------------------
async function deleteItem(id) {
  const item = allItems.find(i => i.id === id);
  if (!item) return;
  if (!confirm(`Delete "${item.cloth_type} / ${item.company_name}" from inventory? This cannot be undone.`)) return;

  try {
    const res  = await fetch(`/api/inventory/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) { alert(data.error || 'Delete failed.'); return; }
    await loadInventory();
  } catch (e) {
    alert('Network error: ' + e.message);
  }
}

// ----------------------------------------------------------------
// QR View Modal (Inventory QR)
// ----------------------------------------------------------------
function openQrViewModal(id) {
  const item = allItems.find(i => i.id === id);
  if (!item) return;
  const url = `/api/inventory/${id}/qr`;
  document.getElementById('qr-view-title').textContent =
    `QR — ${item.cloth_type} / ${item.company_name}${item.quality_number ? ' / ' + item.quality_number : ''}`;
  document.getElementById('qr-view-img').src = url;
  document.getElementById('qr-download-link').href = url;
  document.getElementById('qr-view-modal').classList.remove('hidden');
}

function closeQrViewModal() {
  document.getElementById('qr-view-modal').classList.add('hidden');
}

document.getElementById('qr-view-modal').addEventListener('click', function(e) {
  if (e.target === this) closeQrViewModal();
});

// ----------------------------------------------------------------
// Current Stock QR Modal
// ----------------------------------------------------------------
function openCurrentStockQrModal() {
  document.getElementById('cs-cloth').value = '';
  document.getElementById('cs-company').innerHTML = '<option value="">— Select cloth type first —</option>';
  ['cs-quality','cs-mrp','cs-cloth-new','cs-company-new'].forEach(id => {
    document.getElementById(id).value = '';
  });
  ['cs-cloth-add-row','cs-company-add-row'].forEach(id => {
    document.getElementById(id).style.display = 'none';
  });
  document.getElementById('cs-unit').value = 'm';
  document.getElementById('cs-error').textContent = '';
  document.getElementById('cs-qr-result').style.display = 'none';
  document.getElementById('cs-qr-modal').classList.remove('hidden');
}

function closeCsQrModal() {
  document.getElementById('cs-qr-modal').classList.add('hidden');
}

async function generateCsQr() {
  const cloth   = document.getElementById('cs-cloth').value;
  const company = document.getElementById('cs-company').value;
  const errEl   = document.getElementById('cs-error');
  const btn     = document.getElementById('btn-cs-generate');

  errEl.textContent = '';
  document.getElementById('cs-qr-result').style.display = 'none';
  if (!cloth || cloth === '__add__') { errEl.textContent = 'Select a cloth type.'; return; }

  btn.disabled = true;
  try {
    const res = await fetch('/api/inventory/current-stock-qr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cloth_type:     cloth,
        company_name:   (company && company !== '__add__') ? company : '',
        quality_number: document.getElementById('cs-quality').value.trim(),
        mrp:            parseFloat(document.getElementById('cs-mrp').value) || 0,
        unit_label:     document.getElementById('cs-unit').value,
      }),
    });
    if (!res.ok) { errEl.textContent = 'Failed to generate QR.'; return; }

    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    document.getElementById('cs-qr-img').src       = url;
    document.getElementById('cs-qr-download').href = url;
    document.getElementById('cs-qr-result').style.display = '';
  } catch (e) {
    errEl.textContent = 'Network error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('cs-qr-modal').addEventListener('click', function(e) {
  if (e.target === this) closeCsQrModal();
});

// ----------------------------------------------------------------
// Transactions Modal
// ----------------------------------------------------------------
async function openTxnModal(id) {
  const item = allItems.find(i => i.id === id);
  if (!item) return;
  document.getElementById('txn-title').textContent =
    `History — ${item.cloth_type} / ${item.company_name}${item.quality_number ? ' / ' + item.quality_number : ''}`;
  document.getElementById('txn-loading').style.display = '';
  document.getElementById('txn-table').style.display   = 'none';
  document.getElementById('txn-empty').style.display   = 'none';
  document.getElementById('txn-modal').classList.remove('hidden');

  try {
    const res  = await fetch(`/api/inventory/${id}/transactions`);
    const txns = await res.json();
    document.getElementById('txn-loading').style.display = 'none';

    if (!txns.length) {
      document.getElementById('txn-empty').style.display = '';
      return;
    }

    const tbody = document.getElementById('txn-tbody');
    tbody.innerHTML = '';
    txns.forEach(t => {
      const tr   = document.createElement('tr');
      const qty  = Number(t.quantity);
      const sign = qty >= 0 ? '+' : '';
      const col  = qty >= 0
        ? 'color:var(--success,#22c55e);'
        : 'color:var(--danger,#ef4444);';
      const label = {
        opening: 'Opening', purchase: 'Purchase',
        sale: 'Sale', sale_reversal: 'Reversal', adjustment: 'Adjustment',
      }[t.txn_type] || t.txn_type;

      tr.innerHTML = `
        <td style="font-size:12px;">${(t.created_at || '').slice(0,16)}</td>
        <td>${label}</td>
        <td class="text-right" style="${col}font-weight:600;">${sign}${qty.toFixed(2)}</td>
        <td style="font-size:12px;">${t.reference_type === 'bill' ? 'Bill #' + t.reference_id : 'Manual'}</td>
        <td style="font-size:12px;">${esc(t.notes) || '—'}</td>
        <td style="font-size:12px;">${esc(t.created_by) || '—'}</td>
      `;
      tbody.appendChild(tr);
    });
    document.getElementById('txn-table').style.display = '';
  } catch (e) {
    document.getElementById('txn-loading').style.display = 'none';
    document.getElementById('txn-empty').textContent     = 'Failed to load: ' + e.message;
    document.getElementById('txn-empty').style.display   = '';
  }
}

function closeTxnModal() {
  document.getElementById('txn-modal').classList.add('hidden');
}

document.getElementById('txn-modal').addEventListener('click', function(e) {
  if (e.target === this) closeTxnModal();
});
