/* ============================================================
   inventory.js — Inventory management page (core)

   The page script is split into parts that share one global scope and load in this
   order (see inventory.html): inventory.js (this file: state + list + modals),
   inventory-selects.js, inventory-add.js, inventory-qr.js, inventory-scan.js.
   ============================================================ */

let allItems = [];
let selectMode = false;
const selectedIds = new Set();
let lastSelectedId = null;
let baGroupCounter = 0;
let baRowCounters  = {};
let csGroupCounter = 0;
let csRowCounters  = {};

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
  loadSuppliersForSelect();
  loadInvoicesForSelect();
});

async function loadInventory() {
  setLoading(true);
  try {
    const res = await fetch('/api/inventory');
    allItems = await res.json();
    populateFilterOptions();
    filterItems();
    renderStats(allItems);
  } catch (e) {
    showError('Failed to load inventory: ' + e.message);
  } finally {
    setLoading(false);
  }
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
    syncSectionHeaderChecks();
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
      ? `<span class="pill pill-warning" style="margin-left:8px;">${lowCount} alert${lowCount !== 1 ? 's' : ''}</span>`
      : '';

    const rows = sectionItems.map(item => {
      const code = item.item_code || `#${item.id}`;
      const selectCell = selectMode
        ? `<td style="text-align:center;"><input type="checkbox" class="row-select" data-id="${item.id}" onclick="onRowSelectClick(event, ${item.id})" ${selectedIds.has(item.id) ? 'checked' : ''} aria-label="Select for label printing" /></td>`
        : '';
      const stockClass = item.current_stock < 0
        ? 'style="color:var(--danger);font-weight:700;"'
        : item.current_stock <= item.min_stock_alert
          ? 'style="color:var(--warning);font-weight:700;"'
          : '';
      const stockBadge = item.current_stock < 0
        ? `<span class="pill pill-danger" style="margin-left:4px;">NEG</span>`
        : item.current_stock <= item.min_stock_alert
          ? `<span class="pill pill-warning" style="margin-left:4px;">LOW</span>`
          : '';
      const clothCol    = isOthers ? `<td>${esc(item.cloth_type)}</td>` : '';
      const invoiceCell = item.invoice_number
        ? `<td style="font-size:12px;"><span style="font-weight:600;">${esc(item.invoice_number)}</span><br><span style="color:var(--text-muted);">${esc(item.invoice_date || '')}</span></td>`
        : `<td style="color:var(--text-muted);font-size:12px;">—</td>`;
      return `<tr data-id="${item.id}">
        ${selectCell}
        <td style="text-align:center;font-weight:700;color:var(--text-muted);font-size:12px;white-space:nowrap;">${esc(code)}</td>
        ${clothCol}
        <td>${esc(item.company_name)}</td>
        <td>${esc(item.item_name) || '<span style="color:var(--text-muted);">—</span>'}</td>
        ${invoiceCell}
        <td>${esc(item.quality_number) || '<span style="color:var(--text-muted);">—</span>'}</td>
        <td>${esc(item.shade_number) || '<span style="color:var(--text-muted);">—</span>'}</td>
        <td>${esc(item.unit_label)}</td>
        <td class="text-right">&#8377;${Number(item.mrp).toFixed(2)}</td>
        <td class="text-right" ${stockClass}>${Number(item.current_stock).toFixed(2)}${stockBadge}</td>
        <td class="text-right">${Number(item.min_stock_alert).toFixed(2)}</td>
        <td style="text-align:center;white-space:nowrap;">
          <button class="btn btn-sm btn-secondary" onclick="openQrViewModal(${item.id})" title="QR"><svg class="ico" aria-hidden="true"><use href="#i-qrcode"/></svg> QR</button>
          <button class="btn btn-sm btn-secondary" onclick="openAdjustModal(${item.id})" title="Adjust" style="margin-left:4px;">&#8651; Adjust</button>
          <button class="btn btn-sm btn-secondary" onclick="openTxnModal(${item.id})" title="History" aria-label="Transaction history" style="margin-left:4px;"><svg class="ico" aria-hidden="true"><use href="#i-file-text"/></svg></button>
          <button class="btn btn-sm btn-secondary" onclick="openEditItemModal(${item.id})" title="Edit" aria-label="Edit item" style="margin-left:4px;"><svg class="ico" aria-hidden="true"><use href="#i-pencil"/></svg></button>
          <button class="btn btn-sm btn-secondary" onclick="openInfoModal(${item.id})" title="More Info" aria-label="More info" style="margin-left:4px;"><svg class="ico" aria-hidden="true"><use href="#i-info"/></svg></button>
          <button class="btn btn-sm" style="margin-left:4px;color:var(--danger);" onclick="deleteItem(${item.id})" title="Delete" aria-label="Delete item"><svg class="ico" aria-hidden="true"><use href="#i-x"/></svg></button>
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
              ${selectMode ? `<th style="width:34px;text-align:center;"><input type="checkbox" id="sec-check-${sid}" onchange="onSectionSelectAll('${sid}', this.checked)" title="Select all in this section" aria-label="Select all in ${esc(section)}" /></th>` : ''}
              <th style="width:80px;text-align:center;">ID</th>
              ${isOthers ? '<th>Cloth Type</th>' : ''}
              <th>Company</th>
              <th>Item Name</th>
              <th>Invoice</th>
              <th>Quality No.</th>
              <th>Shade No.</th>
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

  syncSectionHeaderChecks();
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
function populateFilterOptions() {
  const distinct = key => [...new Set(allItems.map(i => i[key]).filter(Boolean))]
    .sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }));

  const fill = (id, values, allLabel) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '';
    const o0 = document.createElement('option');
    o0.value = '';
    o0.textContent = allLabel;
    sel.appendChild(o0);
    values.forEach(v => {
      const o = document.createElement('option');
      o.value = v;
      o.textContent = v;
      sel.appendChild(o);
    });
    sel.value = values.includes(cur) ? cur : '';
  };

  fill('filter-cloth',    distinct('cloth_type'),     'All cloth types');
  fill('filter-company',  distinct('company_name'),   'All companies');
  fill('filter-supplier', distinct('supplier_name'),  'All suppliers');
  fill('filter-invoice',  distinct('invoice_number'), 'All invoices');
}

function filterItems() {
  const q        = document.getElementById('filter-input').value.toLowerCase();
  // "sut001" should find "SUT-001": compare codes with hyphens/spaces removed
  const qCode    = q.replace(/[-\s]/g, '');
  // "sut4" lists every SUT code whose number contains a 4 (SUT-004, -040…-049, -054…)
  const qParts   = q.trim().match(/^([a-z]+)[-\s]*(\d+)$/);
  const status = document.getElementById('filter-status').value;
  const cloth    = document.getElementById('filter-cloth').value;
  const company  = document.getElementById('filter-company').value;
  const supplier = document.getElementById('filter-supplier').value;
  const invoice  = document.getElementById('filter-invoice').value;

  const filtered = allItems.filter(item => {
    const matchText = !q ||
      item.cloth_type.toLowerCase().includes(q) ||
      item.company_name.toLowerCase().includes(q) ||
      (item.item_name     || '').toLowerCase().includes(q) ||
      (item.shade_number  || '').toLowerCase().includes(q) ||
      (item.quality_number || '').toLowerCase().includes(q) ||
      (item.invoice_number || '').toLowerCase().includes(q) ||
      (item.item_code      || '').toLowerCase().includes(q) ||
      (qCode && (item.item_code || '').toLowerCase().replace(/[-\s]/g, '').includes(qCode)) ||
      (qParts && (() => {
        const [pre, num] = (item.item_code || '').toLowerCase().split('-');
        return num !== undefined && pre.includes(qParts[1]) && num.includes(qParts[2]);
      })());

    let matchStatus = true;
    if (status === 'negative') matchStatus = item.current_stock < 0;
    else if (status === 'low')  matchStatus = item.current_stock >= 0 && item.current_stock <= item.min_stock_alert;
    else if (status === 'ok')   matchStatus = item.current_stock > item.min_stock_alert;

    const matchCloth    = !cloth    || item.cloth_type     === cloth;
    const matchCompany  = !company  || item.company_name   === company;
    const matchSupplier = !supplier || item.supplier_name  === supplier;
    const matchInvoice  = !invoice  || item.invoice_number === invoice;

    return matchText && matchStatus && matchCloth && matchCompany && matchSupplier && matchInvoice;
  });

  const countEl = document.getElementById('filter-count');
  if (countEl) {
    countEl.textContent = filtered.length === allItems.length
      ? `${allItems.length} item${allItems.length !== 1 ? 's' : ''}`
      : `${filtered.length} of ${allItems.length} items`;
  }

  renderSections(filtered);
}

// ----------------------------------------------------------------
// Select mode — pick items, print their QR labels on an A4 sheet
// ----------------------------------------------------------------
function toggleSelectMode() {
  selectMode = !selectMode;
  lastSelectedId = null;
  if (!selectMode) selectedIds.clear();

  document.getElementById('select-toggle-label').textContent = selectMode ? 'Done' : 'Select';
  document.getElementById('btn-select-toggle').classList.toggle('btn-primary', selectMode);
  document.getElementById('btn-select-toggle').classList.toggle('btn-secondary', !selectMode);
  document.getElementById('label-select-bar').style.display = selectMode ? 'flex' : 'none';

  filterItems();
  updateLabelBar();
}

function onRowSelectClick(evt, id) {
  const checked = evt.target.checked;

  // Shift-click selects/deselects every row between the last clicked
  // checkbox and this one, in on-screen order (spans section boundaries).
  if (evt.shiftKey && lastSelectedId !== null) {
    const boxes   = [...document.querySelectorAll('input.row-select')];
    const ids     = boxes.map(cb => parseInt(cb.dataset.id));
    const lastIdx = ids.indexOf(lastSelectedId);
    const curIdx  = ids.indexOf(id);
    if (lastIdx !== -1 && curIdx !== -1) {
      const [start, end] = lastIdx < curIdx ? [lastIdx, curIdx] : [curIdx, lastIdx];
      for (let i = start; i <= end; i++) {
        boxes[i].checked = checked;
        if (checked) selectedIds.add(ids[i]);
        else selectedIds.delete(ids[i]);
      }
    }
  } else {
    if (checked) selectedIds.add(id);
    else selectedIds.delete(id);
  }

  lastSelectedId = id;
  syncSectionHeaderChecks();
  updateLabelBar();
}

function onSectionSelectAll(sid, checked) {
  document.querySelectorAll(`#body-${sid} input.row-select`).forEach(cb => {
    cb.checked = checked;
    const id = parseInt(cb.dataset.id);
    if (checked) selectedIds.add(id);
    else selectedIds.delete(id);
  });
  updateLabelBar();
}

function syncSectionHeaderChecks() {
  document.querySelectorAll('[id^="sec-check-"]').forEach(hdr => {
    const boxes = hdr.closest('table').querySelectorAll('input.row-select');
    if (!boxes.length) { hdr.checked = false; hdr.indeterminate = false; return; }
    const checkedCount = [...boxes].filter(b => b.checked).length;
    hdr.checked = checkedCount === boxes.length;
    hdr.indeterminate = checkedCount > 0 && checkedCount < boxes.length;
  });
}

function updateLabelBar() {
  const n = selectedIds.size;
  document.getElementById('lsb-count').textContent =
    `${n} selected`;
  document.getElementById('lsb-print').disabled = n === 0;
}

function clearLabelSelection() {
  selectedIds.clear();
  lastSelectedId = null;
  document.querySelectorAll('input.row-select').forEach(cb => { cb.checked = false; });
  syncSectionHeaderChecks();
  updateLabelBar();
}

function printSelectedLabels() {
  const ids = [...selectedIds];
  if (!ids.length) return;
  window.open(`/inventory/labels?ids=${ids.join(',')}`, '_blank');
}

// ----------------------------------------------------------------
// Info Modal
// ----------------------------------------------------------------
function openInfoModal(id) {
  const item = allItems.find(i => i.id === id);
  if (!item) return;

  document.getElementById('info-title').textContent =
    `${item.cloth_type} / ${item.company_name}` + (item.item_code ? ` — ${item.item_code}` : '');

  function row(label, value) {
    if (value === null || value === undefined || value === '') return '';
    return `<div style="display:flex;gap:8px;font-size:13px;">
      <span style="color:var(--text-muted);min-width:140px;flex-shrink:0;">${label}</span>
      <span style="font-weight:500;">${esc(String(value))}</span>
    </div>`;
  }

  const stockStyle = item.current_stock < 0
    ? 'color:var(--danger);font-weight:700;'
    : item.current_stock <= item.min_stock_alert
      ? 'color:var(--warning);font-weight:700;'
      : 'font-weight:700;';

  const invoiceText = item.invoice_number
    ? `${item.invoice_number}${item.invoice_date ? ' (' + item.invoice_date + ')' : ''}`
    : null;

  document.getElementById('info-body').innerHTML = [
    row('Item Code',      item.item_code),
    row('Cloth Type',     item.cloth_type),
    row('Company',        item.company_name),
    row('Item Name',      item.item_name),
    row('Quality No.',    item.quality_number),
    row('Shade No.',      item.shade_number),
    row('Unit',           item.unit_label),
    `<div style="display:flex;gap:8px;font-size:13px;"><span style="color:var(--text-muted);min-width:140px;flex-shrink:0;">MRP</span><span style="font-weight:500;">&#8377;${Number(item.mrp).toFixed(2)}</span></div>`,
    `<div style="display:flex;gap:8px;font-size:13px;"><span style="color:var(--text-muted);min-width:140px;flex-shrink:0;">Cost Price</span><span style="font-weight:500;">&#8377;${Number(item.cost_price || 0).toFixed(2)}</span></div>`,
    `<div style="display:flex;gap:8px;font-size:13px;"><span style="color:var(--text-muted);min-width:140px;flex-shrink:0;">Current Stock</span><span style="${stockStyle}">${Number(item.current_stock).toFixed(2)} ${esc(item.unit_label)}</span></div>`,
    `<div style="display:flex;gap:8px;font-size:13px;"><span style="color:var(--text-muted);min-width:140px;flex-shrink:0;">Low Stock Alert</span><span style="font-weight:500;">${Number(item.min_stock_alert).toFixed(2)}</span></div>`,
    row('Special Code',   item.special_code),
    row('Supplier',       item.supplier_name),
    row('Invoice',        invoiceText),
    row('Notes',          item.notes),
    row('Added',          item.created_at),
    row('Last Updated',   item.updated_at),
  ].filter(Boolean).join('');

  document.getElementById('info-modal').classList.remove('hidden');
}

function closeInfoModal() {
  document.getElementById('info-modal').classList.add('hidden');
}

document.getElementById('info-modal').addEventListener('click', function(e) {
  if (e.target === this) closeInfoModal();
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
        ? 'color:var(--success);'
        : 'color:var(--danger);';
      const label = {
        opening: 'Opening', purchase: 'Purchase',
        sale: 'Sale', sale_reversal: 'Reversal', adjustment: 'Adjustment',
      }[t.txn_type] || t.txn_type;

      tr.innerHTML = `
        <td style="font-size:12px;">${(t.created_at || '').slice(0,16)}</td>
        <td>${label}</td>
        <td class="text-right" style="${col}font-weight:600;">${sign}${qty.toFixed(2)}</td>
        <td style="font-size:12px;">${t.reference_type === 'bill' ? (t.bill_number || 'Bill #' + t.reference_id) : 'Manual'}</td>
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

