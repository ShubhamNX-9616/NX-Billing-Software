/* ============================================================
   bill.js — New Bill / Edit Bill page logic
   ============================================================ */

// ---- Edit mode (set by edit_bill.html before this script loads) ----
const BILL_ID   = window.BILL_ID || null;
const EDIT_MODE = !!BILL_ID;

// ---- Global state ----
let rowCounter       = 0;
let savedBillId      = null;
let currentMode      = 'Cash';
let addCompanyCtx    = null;
let addClothTypeCtx  = null;
let salespersons     = [];
let comboLastChanged = null;
let clothTypes       = [];        // [{ id, type_name, has_company }, ...]
let activeItemIds    = [];        // ordered list of live item IDs
const itemDataStore  = {};        // { id: { lineTotal, discPerUnit, rateAfterDisc, discAmt, finalAmt, inventoryItemId } }
let lastIsMobile     = window.innerWidth <= 768;
let advancePaidUserModified = false;
let billSaved = false;  // set true on successful save to suppress beforeunload

// ----------------------------------------------------------------
// Unsaved-changes guard
// ----------------------------------------------------------------
function isBillDirty() {
  if (billSaved) return false;
  const mobile = (document.getElementById('customer-mobile')?.value || '').trim();
  const name   = (document.getElementById('customer-name')?.value   || '').trim();
  if (mobile.length > 0 || name.length > 0) return true;
  return activeItemIds.some(id => {
    const qty = (document.getElementById(`qty-${id}`)?.value || '').trim();
    const mrp = (document.getElementById(`mrp-${id}`)?.value || '').trim();
    return qty !== '' || mrp !== '';
  });
}

window.addEventListener('beforeunload', e => {
  if (isBillDirty()) {
    e.preventDefault();
    e.returnValue = '';
  }
});

// QR scanner state
let html5QrScanner  = null;
let qrScanLock      = false;   // prevents duplicate scans of the same code

const companyCache = {};          // { clothType: [company, ...] }

// ----------------------------------------------------------------
// Utilities
// ----------------------------------------------------------------
function fmt(amount) {
  return Number(amount || 0).toLocaleString('en-IN', {
    style: 'currency', currency: 'INR',
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

function round2(n) {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

function getRoundedTotals(amount) {
  const grossFinal = round2(amount);
  const netPayable = Math.floor(grossFinal);
  const roundOff = round2(grossFinal - netPayable);
  return { grossFinal, roundOff, netPayable };
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

function normalizeMobile(raw) {
  let digits = (raw || '').replace(/\D/g, '');
  if (digits.startsWith('91') && digits.length === 12) digits = digits.slice(2);
  if (digits.startsWith('0')  && digits.length === 11) digits = digits.slice(1);
  return digits;
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function isMobile() {
  return window.innerWidth <= 768;
}

// ----------------------------------------------------------------
// Page init
// ----------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
  if (EDIT_MODE) {
    await Promise.all([loadClothTypes(), loadSalespersons()]);
    await prefillEditForm();
  } else {
    document.getElementById('bill-date').value = todayISO();
    await Promise.all([loadNextBillNumber(), loadClothTypes(), loadSalespersons()]);
    addItemRow();
  }
  setupMobileSearch();
  setupPaymentTabs();
  window.addEventListener('resize', debounce(handleResponsiveItemsLayout, 150));
  lastIsMobile = isMobile();
});

async function loadClothTypes() {
  try {
    const res = await fetch('/api/cloth-types');
    clothTypes = await res.json();
  } catch {
    clothTypes = [
      { type_name: 'Shirting',  has_company: 1 },
      { type_name: 'Suiting',   has_company: 1 },
      { type_name: 'Readymade', has_company: 1 },
      { type_name: 'Stitching', has_company: 1 },
    ];
  }
}

async function loadSalespersons() {
  const select = document.getElementById('salesperson-name');
  if (!select) return;
  try {
    const res = await fetch('/api/salespersons');
    salespersons = await res.json();
  } catch {
    salespersons = [{ name: 'Self' }, { name: 'Geetesh' }];
  }
  renderSalespersonOptions('Self');
}

function renderSalespersonOptions(selectedName = '') {
  const select = document.getElementById('salesperson-name');
  if (!select) return;
  const options = salespersons.map(sp =>
    `<option value="${sp.name}"${sp.name === selectedName ? ' selected' : ''}>${sp.name}</option>`
  ).join('');
  select.innerHTML = `<option value="">-- Select --</option>${options}`;
  if (selectedName) select.value = selectedName;
}

function buildClothOptions(selected) {
  return clothTypes.map(ct =>
    `<option value="${ct.type_name}"${ct.type_name === selected ? ' selected' : ''}>${ct.type_name}</option>`
  ).join('') + '<option value="__add_new__">+ Add new cloth type</option>';
}

function getUnitLabel(clothType) {
  if (clothType === 'Shirting' || clothType === 'Suiting') return 'm';
  return 'pcs';
}

function getQtyStep(unit) { return unit === 'm' ? '0.01' : '1'; }
function getQtyMin(unit)  { return unit === 'm' ? '0.01' : '1'; }

async function loadNextBillNumber() {
  try {
    const res   = await fetch('/api/bills');
    const bills = await res.json();
    let next = 'SHN-0001';
    if (bills.length) {
      const last = bills.sort((a, b) => b.bill_number.localeCompare(a.bill_number))[0].bill_number;
      const num  = parseInt(last.split('-')[1] || '0', 10);
      next = `SHN-${String(num + 1).padStart(4, '0')}`;
    }
    document.getElementById('bill-number').value = next;
  } catch {
    document.getElementById('bill-number').value = 'SHN-0001';
  }
}

// ----------------------------------------------------------------
// Mobile search
// ----------------------------------------------------------------
function setupMobileSearch() {
  const input = document.getElementById('customer-mobile');
  input.addEventListener('input', debounce(doMobileSearch, 300));
}

async function doMobileSearch() {
  const raw      = document.getElementById('customer-mobile').value.trim();
  const norm     = normalizeMobile(raw);
  const statusEl = document.getElementById('customer-status');
  const nameEl   = document.getElementById('customer-name');
  const spinner  = document.getElementById('mobile-spinner');
  const errEl    = document.getElementById('mobile-error');

  errEl.textContent    = '';
  statusEl.textContent = '';

  if (norm.length < 10) { if (raw.length > 0) nameEl.value = ''; return; }
  if (norm.length > 10) { errEl.textContent = 'Enter a valid 10-digit mobile number.'; return; }

  spinner.style.display = 'inline-block';
  try {
    const res  = await fetch(`/api/customers/search?mobile=${norm}`);
    const data = await res.json();
    if (data.found) {
      nameEl.value = data.customer.name;
      // Brief yellow flash so staff can see the field was auto-filled
      nameEl.style.transition = 'background 0.15s';
      nameEl.style.background = '#fef9c3';
      setTimeout(() => {
        nameEl.style.background = '';
        setTimeout(() => { nameEl.style.transition = ''; }, 300);
      }, 700);
      statusEl.innerHTML = '<span class="badge badge-success">&#10003; Existing Customer</span>';
    } else {
      nameEl.value = '';
      statusEl.innerHTML = '<span class="badge badge-info">New Customer</span>';
      nameEl.focus();
    }
  } catch {
    statusEl.innerHTML = '<span class="text-danger">Search failed</span>';
  } finally {
    spinner.style.display = 'none';
  }
}

// ----------------------------------------------------------------
// Company fetching (with cache)
// ----------------------------------------------------------------
async function fetchCompanies(clothType) {
  if (companyCache[clothType]) return companyCache[clothType];
  try {
    const res  = await fetch(`/api/companies?clothType=${encodeURIComponent(clothType)}`);
    const list = await res.json();
    companyCache[clothType] = list;
    return list;
  } catch { return []; }
}

function invalidateCompanyCache(clothType) { delete companyCache[clothType]; }

function rebuildCompanySelect(selectEl, list, selectedName) {
  selectEl.innerHTML = '<option value="">— Select —</option>';
  list.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.company_name;
    opt.textContent = c.company_name;
    if (c.company_name === selectedName) opt.selected = true;
    selectEl.appendChild(opt);
  });
}

// ----------------------------------------------------------------
// Cloth type change → reload company dropdown + update unit
// Works for both table rows and cards (same input IDs)
// ----------------------------------------------------------------
async function onClothChange(id) {
  const sel       = document.getElementById(`cloth-${id}`);
  const clothType = sel.value;

  if (clothType === '__add_new__') {
    sel.value = sel.dataset.prev || (clothTypes[0]?.type_name || 'Shirting');
    openAddClothTypeModal(id);
    return;
  }

  sel.dataset.prev = clothType;

  const ct       = clothTypes.find(t => t.type_name === clothType);
  const hasCo    = ct ? ct.has_company !== 0 : true;
  const unit     = getUnitLabel(clothType);
  const unitEl   = document.getElementById(`unit-${id}`);
  const compWrap = document.getElementById(`company-wrap-${id}`);
  const compSel  = document.getElementById(`company-${id}`);
  const qtyEl    = document.getElementById(`qty-${id}`);

  if (unitEl) unitEl.textContent = unit;
  if (qtyEl) { qtyEl.step = getQtyStep(unit); qtyEl.min = getQtyMin(unit); }
  if (compWrap) compWrap.style.display = hasCo ? '' : 'none';

  const mrpHintEl    = document.getElementById(`mrp-label-${id}`);
  const mrpCardLblEl = document.getElementById(`mrp-field-label-${id}`);
  if (mrpHintEl)    mrpHintEl.textContent    = clothType === 'Stitching' ? 'Price' : 'MRP';
  if (mrpCardLblEl) mrpCardLblEl.textContent = clothType === 'Stitching' ? 'Price (₹)' : 'MRP (₹)';

  if (!hasCo || !compSel) {
    if (compSel) compSel.innerHTML = '';
    recalcRow(id);
    return;
  }

  compSel.innerHTML = '<option value="">Loading…</option>';
  const list = await fetchCompanies(clothType);
  rebuildCompanySelect(compSel, list, '');
  recalcRow(id);
}

// Variant used on resize re-render: restores previously selected company
async function onClothChangeRestoring(id, clothType, selectedCompany) {
  const sel      = document.getElementById(`cloth-${id}`);
  const unitEl   = document.getElementById(`unit-${id}`);
  const compWrap = document.getElementById(`company-wrap-${id}`);
  const compSel  = document.getElementById(`company-${id}`);

  if (!unitEl) return;

  const ct    = clothTypes.find(t => t.type_name === clothType);
  const hasCo = ct ? ct.has_company !== 0 : true;
  const unit  = getUnitLabel(clothType);
  const qtyEl = document.getElementById(`qty-${id}`);

  unitEl.textContent = unit;
  if (qtyEl) { qtyEl.step = getQtyStep(unit); qtyEl.min = getQtyMin(unit); }
  if (sel) { sel.value = clothType; sel.dataset.prev = clothType; }
  if (compWrap) compWrap.style.display = hasCo ? '' : 'none';

  const mrpHintEl    = document.getElementById(`mrp-label-${id}`);
  const mrpCardLblEl = document.getElementById(`mrp-field-label-${id}`);
  if (mrpHintEl)    mrpHintEl.textContent    = clothType === 'Stitching' ? 'Price' : 'MRP';
  if (mrpCardLblEl) mrpCardLblEl.textContent = clothType === 'Stitching' ? 'Price (₹)' : 'MRP (₹)';

  if (!hasCo || !compSel) {
    if (compSel) compSel.innerHTML = '';
    recalcRow(id);
    return;
  }

  compSel.innerHTML = '<option value="">Loading…</option>';
  const list = await fetchCompanies(clothType);
  rebuildCompanySelect(compSel, list, selectedCompany);
  recalcRow(id);
}

// ----------------------------------------------------------------
// ----------------------------------------------------------------
// Keyboard nav inside an item row: Enter moves qty→mrp→disc→next row
// ----------------------------------------------------------------
function setupRowEnterNav(id) {
  function focusAndSelect(fieldId) {
    const el = document.getElementById(fieldId);
    if (!el) return;
    el.focus();
    if (el.select) el.select();
  }

  const qtyEl  = document.getElementById(`qty-${id}`);
  const mrpEl  = document.getElementById(`mrp-${id}`);
  const discEl = document.getElementById(`disc-${id}`);

  if (qtyEl) qtyEl.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); focusAndSelect(`mrp-${id}`); }
  });
  if (mrpEl) mrpEl.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); focusAndSelect(`disc-${id}`); }
  });
  if (discEl) discEl.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const idx  = activeItemIds.indexOf(id);
      const next = activeItemIds[idx + 1];
      if (next !== undefined) {
        focusAndSelect(`cloth-${next}`);
      } else {
        addItemRow();
        requestAnimationFrame(() => focusAndSelect(`cloth-${rowCounter}`));
      }
    }
  });
}

// addItemRow — entry point, branches on layout
// ----------------------------------------------------------------
function addItemRow() {
  const id = ++rowCounter;
  activeItemIds.push(id);
  itemDataStore[id] = { lineTotal: 0, discPerUnit: 0, rateAfterDisc: 0, discAmt: 0, finalAmt: 0, inventoryItemId: null };

  if (isMobile()) {
    appendCard(id, {});
    updateCardNumbers();
  } else {
    appendTableRow(id, {});
    updateRowNumbers();
  }
}

// ----------------------------------------------------------------
// Desktop: append a table row for item `id`
// vals: { clothType, companyName, qualityNumber, quantity, mrp, discPct }
// ----------------------------------------------------------------
function appendTableRow(id, vals = {}) {
  const clothType = vals.clothType || 'Shirting';
  const unit      = getUnitLabel(clothType);
  const qtyStep   = getQtyStep(unit);
  const mrpLabel  = clothType === 'Stitching' ? 'Price' : 'MRP';
  const tbody = document.getElementById('items-body');
  const tr    = document.createElement('tr');
  tr.id       = `row-${id}`;

  tr.innerHTML = `
    <td style="text-align:center;color:var(--text-muted);font-size:12px;" class="row-num"></td>
    <td>
      <select class="cell-input select col-cloth" id="cloth-${id}"
              data-prev="${clothType}"
              onchange="onClothChange(${id})">
        ${buildClothOptions(clothType)}
      </select>
      <div id="inv-badge-${id}" style="display:none;margin-top:2px;font-size:9px;background:#eff6ff;color:#2563eb;padding:1px 5px;border-radius:3px;text-align:center;cursor:pointer;" onclick="clearInventoryLink(${id})" title="Linked to inventory — click to unlink">&#128230; INV</div>
    </td>
    <td id="company-wrap-${id}" style="min-width:140px;">
      <div style="display:flex;gap:4px;align-items:center;">
        <select class="cell-input select" id="company-${id}" style="flex:1;min-width:90px;">
          <option value="">Loading…</option>
        </select>
        <button type="button" class="btn btn-sm"
                style="padding:3px 6px;font-size:11px;flex-shrink:0;"
                onclick="openAddCompanyModal(${id})" title="Add company">+</button>
      </div>
    </td>
    <td>
      <input type="text" class="cell-input col-quality" id="quality-${id}"
             placeholder="Optional" value="${vals.qualityNumber || ''}" />
    </td>
    <td>
      <input type="number" class="cell-input col-qty" id="qty-${id}"
             min="${qtyStep}" step="${qtyStep}" placeholder="0"
             value="${vals.quantity || ''}"
             oninput="recalcRow(${id})" />
    </td>
    <td>
      <span id="unit-${id}" style="font-size:12.5px;color:var(--text-muted);padding:0 4px;">${unit}</span>
    </td>
    <td>
      <input type="number" class="cell-input col-mrp" id="mrp-${id}"
             min="0" step="0.01" placeholder="0.00"
             value="${vals.mrp || ''}"
             oninput="recalcRow(${id})" />
      <div id="mrp-label-${id}" style="font-size:9px;color:var(--text-muted);text-align:center;margin-top:1px;">${mrpLabel}</div>
    </td>
    <td>
      <input type="number" class="cell-input col-disc" id="disc-${id}"
             min="0" max="100" step="0.01" placeholder="%"
             value="${vals.discPct !== undefined ? vals.discPct : ''}"
             oninput="recalcRow(${id})" />
      <input type="number" class="cell-input col-disc" id="discamt-${id}"
             min="0" step="0.01" placeholder="₹"
             value="${vals.discAmt || ''}"
             oninput="recalcRow(${id})" style="margin-top:3px;" />
    </td>
    <td class="item-line-total" id="rateafterdisc-${id}">₹0.00</td>
    <td class="item-line-total" id="finalamt-${id}">₹0.00</td>
    <td style="text-align:center;">
      <button type="button" class="btn-remove-row" onclick="removeRow(${id})"
              title="Remove row">&#215;</button>
    </td>
  `;

  tbody.appendChild(tr);
  onClothChangeRestoring(id, clothType, vals.companyName || '');
  setupRowEnterNav(id);
}

// ----------------------------------------------------------------
// Mobile: append a card for item `id`
// ----------------------------------------------------------------
function appendCard(id, vals = {}) {
  const clothType = vals.clothType || 'Shirting';
  const unit      = getUnitLabel(clothType);
  const qtyStep   = getQtyStep(unit);
  const mrpLabel  = clothType === 'Stitching' ? 'Price (₹)' : 'MRP (₹)';
  const mrpFooterLabel = clothType === 'Stitching' ? 'Price' : 'MRP';
  const ct    = clothTypes.find(t => t.type_name === clothType);
  const hasCo = ct ? ct.has_company !== 0 : true;

  const companyFieldHtml = hasCo
    ? `<div class="item-card-field" id="company-wrap-${id}">
        <span class="item-card-label">Company</span>
        <div style="display:flex;gap:6px;align-items:center;">
          <select class="input select" id="company-${id}" style="flex:1;">
            <option value="">Loading…</option>
          </select>
          <button type="button" class="btn btn-sm btn-secondary"
                  onclick="openAddCompanyModal(${id})">+</button>
        </div>
      </div>`
    : `<div id="company-wrap-${id}" style="display:none;"></div>`;

  const container = document.getElementById('items-cards-wrapper');
  const card      = document.createElement('div');
  card.className  = 'item-card';
  card.id         = `item-card-${id}`;

  card.innerHTML = `
    <div class="item-card-header">
      <span id="card-header-${id}">Item</span>
      <div style="display:flex;align-items:center;gap:6px;">
        <span id="inv-badge-${id}" style="display:none;font-size:9px;background:#eff6ff;color:#2563eb;padding:2px 6px;border-radius:3px;cursor:pointer;" onclick="clearInventoryLink(${id})" title="Linked to inventory — click to unlink">&#128230; INV</span>
        <button type="button" class="btn-remove-row" onclick="removeRow(${id})">&#215;</button>
      </div>
    </div>

    <div class="item-card-field">
      <span class="item-card-label">Cloth Type</span>
      <select class="input select" id="cloth-${id}"
              data-prev="${clothType}"
              onchange="onClothChange(${id})">
        ${buildClothOptions(clothType)}
      </select>
    </div>

    ${companyFieldHtml}

    <div class="item-card-field">
      <span class="item-card-label">Quality No.</span>
      <input type="text" class="input" id="quality-${id}"
             placeholder="Optional" value="${vals.qualityNumber || ''}" />
    </div>

    <div class="item-card-field">
      <span class="item-card-label">Qty &amp; Unit</span>
      <div style="display:flex;gap:8px;align-items:center;">
        <input type="number" class="input" id="qty-${id}"
               min="${qtyStep}" step="${qtyStep}" placeholder="0"
               value="${vals.quantity || ''}"
               oninput="recalcRow(${id})" style="flex:1;" />
        <span id="unit-${id}"
              style="font-size:14px;color:var(--text-muted);min-width:28px;">${unit}</span>
      </div>
    </div>

    <div class="item-card-field">
      <span class="item-card-label" id="mrp-field-label-${id}">${mrpLabel}</span>
      <input type="number" class="input" id="mrp-${id}"
             min="0" step="0.01" placeholder="0.00"
             value="${vals.mrp || ''}"
             oninput="recalcRow(${id})" />
    </div>

    <div class="item-card-field">
      <span class="item-card-label">Discount</span>
      <div style="display:flex;gap:8px;">
        <input type="number" class="input" id="disc-${id}"
               min="0" max="100" step="0.01" placeholder="Disc %"
               value="${vals.discPct !== undefined ? vals.discPct : ''}"
               oninput="recalcRow(${id})" style="flex:1;" />
        <input type="number" class="input" id="discamt-${id}"
               min="0" step="0.01" placeholder="Disc ₹"
               value="${vals.discAmt || ''}"
               oninput="recalcRow(${id})" style="flex:1;" />
      </div>
    </div>

    <div class="item-card-footer" style="flex-direction:column;gap:6px;">
      <div style="display:flex;gap:12px;flex-wrap:wrap;font-size:12.5px;">
        <span><span id="card-mrp-footer-lbl-${id}">${mrpFooterLabel}</span>: <strong id="card-mrp-${id}">₹0.00</strong></span>
        <span>Disc: <strong id="card-disc-${id}">—</strong></span>
        <span>Rate: <strong id="card-rate-${id}">₹0.00</strong>/<span id="card-rate-unit-${id}">${unit}</span></span>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:12.5px;color:var(--text-muted);">
          Qty: <strong id="card-qty-disp-${id}" style="color:var(--text);">0</strong>
          <span id="card-qty-unit-${id}">${unit}</span>
        </span>
        <span class="item-card-final" style="font-size:14px;">
          Amt: <strong id="card-finalamt-${id}">₹0.00</strong>
        </span>
      </div>
    </div>
  `;

  container.appendChild(card);
  onClothChangeRestoring(id, clothType, vals.companyName || '');
}

// ----------------------------------------------------------------
// Remove item — works for both table rows and cards
// ----------------------------------------------------------------
function removeRow(id) {
  if (activeItemIds.length <= 1) return; // keep at least 1

  const tableRow = document.getElementById(`row-${id}`);
  const card     = document.getElementById(`item-card-${id}`);
  if (tableRow) tableRow.remove();
  if (card)     card.remove();

  activeItemIds = activeItemIds.filter(i => i !== id);
  delete itemDataStore[id];

  updateRowNumbers();
  updateCardNumbers();
  updateSummary();
}

function updateRowNumbers() {
  document.querySelectorAll('#items-body tr').forEach((tr, i) => {
    const cell = tr.querySelector('.row-num');
    if (cell) cell.textContent = i + 1;
  });
}

function updateCardNumbers() {
  activeItemIds.forEach((id, idx) => {
    const el = document.getElementById(`card-header-${id}`);
    if (el) el.textContent = `Item ${idx + 1}`;
  });
}

// ----------------------------------------------------------------
// Row / card calculations — same input IDs in both layouts
// ----------------------------------------------------------------
function recalcRow(id) {
  const mrp        = parseFloat(document.getElementById(`mrp-${id}`)?.value)     || 0;
  const discPct    = parseFloat(document.getElementById(`disc-${id}`)?.value)    || 0;
  const discAmtRaw = parseFloat(document.getElementById(`discamt-${id}`)?.value);
  const qty        = parseFloat(document.getElementById(`qty-${id}`)?.value)     || 0;

  // Compute effective discount per unit
  const discByPct     = round2(mrp * discPct / 100);
  const hasDiscPct    = discPct > 0;
  const hasDiscAmt    = !isNaN(discAmtRaw) && discAmtRaw > 0;
  let discPerUnit;
  if (hasDiscPct && hasDiscAmt) {
    discPerUnit = Math.min(discByPct, discAmtRaw);  // both filled: use smaller discount
  } else if (hasDiscAmt) {
    discPerUnit = discAmtRaw;
  } else {
    discPerUnit = discByPct;
  }
  discPerUnit = round2(Math.min(discPerUnit, mrp));  // cap at MRP

  const effectiveDiscPct = mrp > 0 ? discPerUnit / mrp * 100 : 0;
  const rateAfterDisc    = round2(mrp - discPerUnit);
  const finalAmt         = round2(rateAfterDisc * qty);
  const lineTotal        = round2(mrp * qty);
  const discAmt          = round2(lineTotal - finalAmt);

  itemDataStore[id] = { lineTotal, discPerUnit, rateAfterDisc, discAmt, finalAmt, effectiveDiscPct };
  updateItemDisplay(id, mrp, discPerUnit, rateAfterDisc, finalAmt);
  updateSummary();
}

// Update display elements — tries both table and card element IDs
function updateItemDisplay(id, mrp, discPerUnit, rateAfterDisc, finalAmt) {
  // Table display elements
  const rateEl  = document.getElementById(`rateafterdisc-${id}`);
  const finalEl = document.getElementById(`finalamt-${id}`);
  if (rateEl)  rateEl.textContent  = fmt(rateAfterDisc);
  if (finalEl) finalEl.textContent = fmt(finalAmt);

  // Card display elements
  const cardMrpEl   = document.getElementById(`card-mrp-${id}`);
  const cardDiscEl  = document.getElementById(`card-disc-${id}`);
  const cardRateEl  = document.getElementById(`card-rate-${id}`);
  const cardFinalEl = document.getElementById(`card-finalamt-${id}`);
  if (cardMrpEl)   cardMrpEl.textContent   = fmt(mrp);
  if (cardDiscEl)  cardDiscEl.textContent  = discPerUnit > 0 ? `−${fmt(discPerUnit)}` : '—';
  if (cardRateEl)  cardRateEl.textContent  = fmt(rateAfterDisc);
  if (cardFinalEl) cardFinalEl.textContent = fmt(finalAmt);

  // Card footer dynamic labels
  const unit          = (document.getElementById(`unit-${id}`)?.textContent || '').trim();
  const clothTypeVal  = document.getElementById(`cloth-${id}`)?.value || '';
  const qty           = parseFloat(document.getElementById(`qty-${id}`)?.value) || 0;
  const qtyDisplay    = qty % 1 === 0 ? String(qty) : qty.toFixed(2);

  const cardMrpFooterLblEl = document.getElementById(`card-mrp-footer-lbl-${id}`);
  const cardRateUnitEl     = document.getElementById(`card-rate-unit-${id}`);
  const cardQtyDispEl      = document.getElementById(`card-qty-disp-${id}`);
  const cardQtyUnitEl      = document.getElementById(`card-qty-unit-${id}`);

  if (cardMrpFooterLblEl) cardMrpFooterLblEl.textContent = clothTypeVal === 'Stitching' ? 'Price' : 'MRP';
  if (cardRateUnitEl)     cardRateUnitEl.textContent      = unit;
  if (cardQtyDispEl)      cardQtyDispEl.textContent       = qtyDisplay;
  if (cardQtyUnitEl)      cardQtyUnitEl.textContent       = unit;
}

// ----------------------------------------------------------------
// Summary totals — reads from itemDataStore (layout-agnostic)
// ----------------------------------------------------------------
function updateSummary() {
  let totalDisc = 0;
  let grossFinal = 0;

  activeItemIds.forEach(id => {
    const d = itemDataStore[id] || {};
    totalDisc += d.discAmt || 0;
    grossFinal += d.finalAmt || 0;
  });

  totalDisc  = round2(totalDisc);
  grossFinal = round2(grossFinal);

  const roundOff    = round2(parseFloat(document.getElementById('sum-roundoff')?.value) || 0);
  const netPayable  = round2(grossFinal - roundOff);
  const roErrEl     = document.getElementById('roundoff-error');

  if (roErrEl) {
    if (roundOff < 0) {
      roErrEl.textContent = 'R/O cannot be negative.';
    } else if (grossFinal > 0 && roundOff > grossFinal) {
      roErrEl.textContent = 'R/O cannot exceed bill total.';
    } else {
      roErrEl.textContent = '';
    }
  }

  document.getElementById('sum-savings').textContent     = fmt(round2(totalDisc + roundOff));
  document.getElementById('sum-final').textContent       = fmt(grossFinal);
  const fpEl = document.getElementById('sum-finalpayable');
  if (fpEl) fpEl.textContent = fmt(netPayable);

  // Advance paid / remaining balance — auto-fill with total unless user has changed it
  const advEl2 = document.getElementById('advance-paid');
  if (advEl2 && !advancePaidUserModified) advEl2.value = netPayable.toFixed(2);
  const advancePaid = round2(parseFloat(document.getElementById('advance-paid')?.value) || 0);
  const advErrEl    = document.getElementById('advance-error');

  if (advErrEl) {
    if (advancePaid < 0) {
      advErrEl.textContent = 'Advance cannot be negative.';
    } else if (netPayable > 0 && advancePaid > netPayable) {
      advErrEl.textContent = 'Advance cannot exceed total payable.';
    } else {
      advErrEl.textContent = '';
    }
  }

  if (currentMode !== 'Combination') {
    document.getElementById('payment-single-amount').value = netPayable.toFixed(2);
  } else {
    syncComboAutoFill();
  }
}

function getFinalTotal() {
  const grossFinal = round2(activeItemIds.reduce((s, id) => s + (itemDataStore[id]?.finalAmt || 0), 0));
  const roundOff   = round2(parseFloat(document.getElementById('sum-roundoff')?.value) || 0);
  return round2(grossFinal - roundOff);
}

// ----------------------------------------------------------------
// Responsive: re-render items when crossing the 768px boundary
// ----------------------------------------------------------------
function handleResponsiveItemsLayout() {
  const mobile = isMobile();
  if (mobile === lastIsMobile) return;
  lastIsMobile = mobile;

  // Snapshot current input values (same IDs in both layouts)
  const snapshots = activeItemIds.map(id => ({
    id,
    clothType:     document.getElementById(`cloth-${id}`)?.value      || 'Shirting',
    companyName:   document.getElementById(`company-${id}`)?.value    || '',
    qualityNumber: document.getElementById(`quality-${id}`)?.value    || '',
    quantity:      document.getElementById(`qty-${id}`)?.value        || '',
    mrp:           document.getElementById(`mrp-${id}`)?.value        || '',
    discPct:       document.getElementById(`disc-${id}`)?.value       || '',
    discAmt:       document.getElementById(`discamt-${id}`)?.value    || '',
  }));

  // Clear both containers
  document.getElementById('items-body').innerHTML        = '';
  document.getElementById('items-cards-wrapper').innerHTML = '';

  // Re-render in new layout, restoring all values
  snapshots.forEach(snap => {
    if (mobile) {
      appendCard(snap.id, snap);
    } else {
      appendTableRow(snap.id, snap);
    }
    recalcRow(snap.id);
    // Restore INV badge visibility if item was linked
    if (itemDataStore[snap.id]?.inventoryItemId) {
      showInventoryBadge(snap.id, true);
    }
  });

  if (mobile) {
    updateCardNumbers();
  } else {
    updateRowNumbers();
  }
}

// ----------------------------------------------------------------
// Payment tabs
// ----------------------------------------------------------------
function setupPaymentTabs() {
  document.querySelectorAll('.payment-mode-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.payment-mode-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentMode = btn.dataset.mode;
      onPaymentModeChange(currentMode);
    });
  });
}

function onPaymentModeChange(mode) {
  const singleWrap = document.getElementById('payment-single-wrap');
  const comboWrap  = document.getElementById('payment-combo-wrap');
  const labelEl    = document.getElementById('single-payment-label');
  const amountEl   = document.getElementById('payment-single-amount');
  const total      = getFinalTotal();

  if (mode === 'Combination') {
    singleWrap.style.display = 'none';
    comboWrap.style.display  = 'block';
    syncComboAutoFill();
  } else {
    singleWrap.style.display = 'block';
    comboWrap.style.display  = 'none';
    labelEl.textContent      = `${mode} Amount (₹)`;
    amountEl.value           = total.toFixed(2);
  }
  document.getElementById('payment-error').textContent = '';
}

// ----------------------------------------------------------------
// Combination payment
// ----------------------------------------------------------------
function onComboCheckChange() {
  const methods = ['Cash', 'Card', 'UPI'];
  const checked = methods.filter(m => document.getElementById(`combo-chk-${m}`).checked);

  methods.forEach(m => {
    const amtEl  = document.getElementById(`combo-amt-${m}`);
    const isChkd = document.getElementById(`combo-chk-${m}`).checked;
    amtEl.disabled = !isChkd;
    if (!isChkd) amtEl.value = '';
  });

  comboLastChanged = null;
  syncComboAutoFill();
}

function onComboAmtInput(method) {
  comboLastChanged = method;
  syncComboAutoFill();
}

function syncComboAutoFill() {
  if (currentMode !== 'Combination') return;
  const methods = ['Cash', 'Card', 'UPI'];
  const checked = methods.filter(m => document.getElementById(`combo-chk-${m}`).checked);
  if (checked.length < 2) {
    document.getElementById('combo-remaining').textContent = '';
    return;
  }

  const total          = getFinalTotal();
  const autoFillMethod = checked[checked.length - 1];
  const manualMethods  = checked.filter(m => m !== autoFillMethod);
  const manualSum      = manualMethods.reduce((s, m) =>
    s + (parseFloat(document.getElementById(`combo-amt-${m}`).value) || 0), 0);

  const remaining = round2(total - manualSum);
  const remEl     = document.getElementById(`combo-amt-${autoFillMethod}`);
  if (!remEl.disabled) remEl.value = remaining >= 0 ? remaining.toFixed(2) : '';

  const remMsg = document.getElementById('combo-remaining');
  const allSum = round2(checked.reduce((s, m) =>
    s + (parseFloat(document.getElementById(`combo-amt-${m}`).value) || 0), 0));
  const diff   = round2(allSum - total);

  if (Math.abs(diff) <= 0.01) {
    remMsg.textContent = 'Payment balanced ✓';
    remMsg.className   = 'payment-remaining is-ok';
  } else {
    remMsg.textContent = `Remaining: ${fmt(round2(total - allSum))}`;
    remMsg.className   = 'payment-remaining is-error';
  }
}

// ----------------------------------------------------------------
// Add Company modal
// ----------------------------------------------------------------
function openAddCompanyModal(rowId) {
  const clothType = document.getElementById(`cloth-${rowId}`).value;
  addCompanyCtx   = { rowId, clothType };
  document.getElementById('add-company-title').textContent = `Add Company — ${clothType}`;
  document.getElementById('add-company-name').value        = '';
  document.getElementById('add-company-error').textContent = '';
  document.getElementById('add-company-modal').classList.remove('hidden');
  document.getElementById('add-company-name').focus();
}

function closeAddCompanyModal() {
  document.getElementById('add-company-modal').classList.add('hidden');
  addCompanyCtx = null;
}

async function saveNewCompany() {
  if (!addCompanyCtx) return;
  const { rowId, clothType } = addCompanyCtx;
  const nameVal = document.getElementById('add-company-name').value.trim();
  const errEl   = document.getElementById('add-company-error');
  const saveBtn = document.getElementById('btn-add-company-save');

  errEl.textContent = '';
  if (!nameVal) { errEl.textContent = 'Company name is required.'; return; }

  saveBtn.disabled    = true;
  saveBtn.textContent = 'Saving…';

  try {
    const res  = await fetch('/api/companies', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ cloth_type: clothType, company_name: nameVal }),
    });
    const data = await res.json();

    if (res.status === 409) { errEl.textContent = 'Company already exists under this cloth type.'; return; }
    if (!res.ok)            { errEl.textContent = data.error || 'Failed to save company.'; return; }

    invalidateCompanyCache(clothType);
    const list    = await fetchCompanies(clothType);
    const compSel = document.getElementById(`company-${rowId}`);
    rebuildCompanySelect(compSel, list, nameVal);
    closeAddCompanyModal();
  } catch (err) {
    errEl.textContent = 'Network error: ' + err.message;
  } finally {
    saveBtn.disabled    = false;
    saveBtn.textContent = 'Save Company';
  }
}

document.getElementById('add-company-modal').addEventListener('click', function (e) {
  if (e.target === this) closeAddCompanyModal();
});

// ----------------------------------------------------------------
// Add Cloth Type modal
// ----------------------------------------------------------------
function openAddClothTypeModal(rowId) {
  addClothTypeCtx = { rowId };
  document.getElementById('add-cloth-type-name').value        = '';
  document.getElementById('add-cloth-type-error').textContent = '';
  document.getElementById('add-cloth-type-modal').classList.remove('hidden');
  document.getElementById('add-cloth-type-name').focus();
}

function closeAddClothTypeModal() {
  document.getElementById('add-cloth-type-modal').classList.add('hidden');
  addClothTypeCtx = null;
}

function refreshAllClothSelects() {
  activeItemIds.forEach(id => {
    const sel = document.getElementById(`cloth-${id}`);
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML    = buildClothOptions(cur);
    sel.dataset.prev = cur;
  });
}

async function saveNewClothType() {
  if (!addClothTypeCtx) return;
  const { rowId } = addClothTypeCtx;
  const nameVal = document.getElementById('add-cloth-type-name').value.trim();
  const errEl   = document.getElementById('add-cloth-type-error');
  const saveBtn = document.getElementById('btn-add-cloth-type-save');

  errEl.textContent = '';
  if (!nameVal) { errEl.textContent = 'Cloth type name is required.'; return; }

  saveBtn.disabled    = true;
  saveBtn.textContent = 'Saving…';

  try {
    const res  = await fetch('/api/cloth-types', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ type_name: nameVal }),
    });
    const data = await res.json();

    if (res.status === 409) { errEl.textContent = 'Cloth type already exists.'; return; }
    if (!res.ok)            { errEl.textContent = data.error || 'Failed to save cloth type.'; return; }

    clothTypes.push({ id: data.id, type_name: data.type_name, has_company: data.has_company });
    refreshAllClothSelects();

    const sel = document.getElementById(`cloth-${rowId}`);
    if (sel) {
      sel.value        = data.type_name;
      sel.dataset.prev = data.type_name;
    }
    closeAddClothTypeModal();
    await onClothChangeRestoring(rowId, data.type_name, '');
  } catch (err) {
    errEl.textContent = 'Network error: ' + err.message;
  } finally {
    saveBtn.disabled    = false;
    saveBtn.textContent = 'Save';
  }
}

document.getElementById('add-cloth-type-modal').addEventListener('click', function (e) {
  if (e.target === this) closeAddClothTypeModal();
});

document.getElementById('btn-add-item').addEventListener('click', () => {
  addItemRow();
  requestAnimationFrame(() => {
    const clothSel = document.getElementById(`cloth-${rowCounter}`);
    if (clothSel) clothSel.focus();
  });
});

// ----------------------------------------------------------------
// Validation helpers
// ----------------------------------------------------------------
function setError(elId, msg) {
  const el = document.getElementById(elId);
  if (el) el.textContent = msg;
}

function clearErrors() {
  ['mobile-error','name-error','salesperson-error','items-error','payment-error','save-error','advance-error','roundoff-error'].forEach(id => setError(id, ''));
}

// ----------------------------------------------------------------
// Collect bill data — reads by input ID (layout-agnostic)
// ----------------------------------------------------------------
function collectBillData() {
  const mobile = normalizeMobile(document.getElementById('customer-mobile').value.trim());
  const name   = document.getElementById('customer-name').value.trim();
  const date   = document.getElementById('bill-date').value;
  const salespersonName = document.getElementById('salesperson-name').value;
  const mode   = currentMode;

  const items = activeItemIds.map(id => ({
    cloth_type:        document.getElementById(`cloth-${id}`).value,
    company_name:      document.getElementById(`company-${id}`)?.value || '',
    quality_number:    document.getElementById(`quality-${id}`).value.trim() || null,
    quantity:          parseFloat(document.getElementById(`qty-${id}`).value)   || 0,
    unit_label:        (document.getElementById(`unit-${id}`).textContent || 'm').trim(),
    mrp:               parseFloat(document.getElementById(`mrp-${id}`).value)   || 0,
    discount_percent:  itemDataStore[id]?.effectiveDiscPct || 0,
    inventory_item_id: itemDataStore[id]?.inventoryItemId || null,
  }));

  const payments = [];
  if (mode === 'Combination') {
    ['Cash','Card','UPI'].forEach(m => {
      if (document.getElementById(`combo-chk-${m}`).checked) {
        payments.push({ payment_method: m,
                        amount: parseFloat(document.getElementById(`combo-amt-${m}`).value) || 0 });
      }
    });
  } else {
    payments.push({ payment_method: mode,
                    amount: parseFloat(document.getElementById('payment-single-amount').value) || 0 });
  }

  const roundOff    = round2(parseFloat(document.getElementById('sum-roundoff')?.value) || 0);
  const advancePaid = round2(parseFloat(document.getElementById('advance-paid')?.value) || 0);
  const remaining   = round2(getFinalTotal() - advancePaid);

  return { customer_name: name, customer_mobile: mobile, bill_date: date,
           salesperson_name: salespersonName,
           payment_mode_type: mode, items, payments,
           round_off:    Math.max(0, roundOff),
           advance_paid: Math.max(0, advancePaid),
           remaining:    Math.max(0, remaining) };
}

// ----------------------------------------------------------------
// Client-side validation
// ----------------------------------------------------------------
function validateBillData(data) {
  clearErrors();
  let valid = true;

  if (!/^[6-9]\d{9}$/.test(data.customer_mobile)) {
    setError('mobile-error', 'Enter a valid 10-digit Indian mobile number.');
    valid = false;
  }
  if (!data.customer_name) {
    setError('name-error', 'Customer name is required.');
    valid = false;
  }
  if (!data.bill_date) {
    setError('save-error', 'Bill date is required.');
    valid = false;
  }
  if (!data.salesperson_name) {
    setError('salesperson-error', 'Sales person is required.');
    valid = false;
  }

  if (!data.items.length) {
    setError('items-error', 'Add at least one item.');
    valid = false;
  } else {
    for (let i = 0; i < data.items.length; i++) {
      const item    = data.items[i];
      const itemCt  = clothTypes.find(t => t.type_name === item.cloth_type);
      const itemHasCo = itemCt ? itemCt.has_company !== 0 : true;
      if (itemHasCo && !item.company_name) {
        setError('items-error', `Item ${i+1}: Select a company.`); valid = false; break;
      }
      if (item.quantity <= 0) {
        setError('items-error', `Item ${i+1}: Quantity must be > 0.`); valid = false; break;
      }
      if (item.mrp < 0) {
        setError('items-error', `Item ${i+1}: MRP cannot be negative.`); valid = false; break;
      }
      if (item.discount_percent < 0 || item.discount_percent > 100) {
        setError('items-error', `Item ${i+1}: Discount must be 0–100.`); valid = false; break;
      }
    }
  }

  const finalTotal  = getFinalTotal();
  const advancePaid = data.advance_paid || 0;
  if (advancePaid < 0) {
    setError('advance-error', 'Advance paid cannot be negative.');
    valid = false;
  } else if (advancePaid > finalTotal) {
    setError('advance-error', 'Advance paid cannot exceed total payable.');
    valid = false;
  }

  if (data.payment_mode_type === 'Combination') {
    const checked = ['Cash','Card','UPI'].filter(m =>
      document.getElementById(`combo-chk-${m}`).checked);
    if (checked.length < 2) {
      setError('payment-error', 'Select at least 2 methods for Combination.');
      valid = false;
    } else {
      const sum = round2(data.payments.reduce((s, p) => s + p.amount, 0));
      if (Math.abs(sum - finalTotal) > 0.01) {
        setError('payment-error', `Payment sum (${fmt(sum)}) must equal final total (${fmt(finalTotal)}).`);
        valid = false;
      }
    }
  }

  return valid;
}

// ----------------------------------------------------------------
// Edit mode: pre-fill all fields from existing bill
// ----------------------------------------------------------------
async function prefillEditForm() {
  try {
    const res = await fetch(`/api/bills/${BILL_ID}`);
    if (!res.ok) throw new Error('Failed to load bill for editing.');
    const bill = await res.json();

    // Bill info bar
    document.getElementById('bill-number').value = bill.bill_number;
    document.getElementById('bill-date').value   = bill.bill_date;
    renderSalespersonOptions(bill.salesperson_name || 'Self');

    // Warning banner
    const bnEl = document.getElementById('edit-warning-bill-num');
    if (bnEl) bnEl.textContent = bill.bill_number;

    // Customer
    document.getElementById('customer-mobile').value = bill.customer_mobile_snapshot;
    document.getElementById('customer-name').value   = bill.customer_name_snapshot;
    const statusEl = document.getElementById('customer-status');
    if (statusEl) statusEl.innerHTML = '<span class="badge badge-success">Existing Customer</span>';

    // Items — add a row per item and fill values
    for (const item of bill.items) {
      addItemRow();
      const id = activeItemIds[activeItemIds.length - 1];
      await setItemRowValues(id, item);
    }

    // Payment mode and amounts
    setPaymentMode(bill.payment_mode_type, bill.payments || []);

    // Round-off (user-entered)
    const roEl = document.getElementById('sum-roundoff');
    if (roEl) roEl.value = (bill.round_off || 0) > 0 ? Number(bill.round_off).toFixed(2) : '';

    // Advance paid
    const advEl = document.getElementById('advance-paid');
    if (advEl) advEl.value = (bill.advance_paid || 0).toFixed(2);
    advancePaidUserModified = true;

    // Update save button label
    const saveBtn = document.getElementById('btn-save');
    if (saveBtn) saveBtn.textContent = '\u2713 Update Bill';

    updateSummary();
  } catch (err) {
    document.getElementById('save-error').textContent = 'Failed to load bill data: ' + err.message;
  }
}

async function setItemRowValues(id, item) {
  // Set numeric inputs first so recalcRow (called inside onClothChangeRestoring) reads them
  const qtyEl     = document.getElementById(`qty-${id}`);
  const mrpEl     = document.getElementById(`mrp-${id}`);
  const discEl    = document.getElementById(`disc-${id}`);
  const discAmtEl = document.getElementById(`discamt-${id}`);
  const qualEl    = document.getElementById(`quality-${id}`);
  if (qtyEl)  qtyEl.value  = item.quantity;
  if (mrpEl)  mrpEl.value  = item.mrp;
  // Restore discount as a flat ₹ amount (mrp − rate_after_disc) to avoid
  // the lossy percentage round-trip that causes payment-sum mismatches.
  const discPerUnit = round2((item.mrp || 0) - (item.rate_after_disc || 0));
  if (discEl)    discEl.value    = '';
  if (discAmtEl) discAmtEl.value = discPerUnit > 0 ? discPerUnit : '';
  if (qualEl)    qualEl.value    = item.quality_number || '';
  // Restore inventory link if present
  if (item.inventory_item_id) {
    itemDataStore[id].inventoryItemId = item.inventory_item_id;
    showInventoryBadge(id, true);
  }
  // Set cloth type and company (also calls recalcRow internally)
  await onClothChangeRestoring(id, item.cloth_type, item.company_name || '');
}

function setPaymentMode(mode, payments) {
  currentMode = mode;
  document.querySelectorAll('.payment-mode-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
  onPaymentModeChange(mode);

  if (mode === 'Combination') {
    // Reset first
    ['Cash', 'Card', 'UPI'].forEach(m => {
      const chk = document.getElementById(`combo-chk-${m}`);
      const amt = document.getElementById(`combo-amt-${m}`);
      if (chk) chk.checked = false;
      if (amt) { amt.disabled = true; amt.value = ''; }
    });
    // Apply saved amounts
    payments.forEach(p => {
      const chk = document.getElementById(`combo-chk-${p.payment_method}`);
      const amt = document.getElementById(`combo-amt-${p.payment_method}`);
      if (chk) {
        chk.checked = true;
        if (amt) { amt.disabled = false; amt.value = parseFloat(p.amount).toFixed(2); }
      }
    });
    syncComboAutoFill();
  }
}

function openAddSalespersonModal() {
  document.getElementById('add-salesperson-name').value = '';
  document.getElementById('add-salesperson-error').textContent = '';
  document.getElementById('add-salesperson-modal').classList.remove('hidden');
  document.getElementById('add-salesperson-name').focus();
}

function closeAddSalespersonModal() {
  document.getElementById('add-salesperson-modal').classList.add('hidden');
}

async function saveNewSalesperson() {
  const nameVal = document.getElementById('add-salesperson-name').value.trim();
  const errEl = document.getElementById('add-salesperson-error');
  const saveBtn = document.getElementById('btn-add-salesperson-save');

  errEl.textContent = '';
  if (!nameVal) {
    errEl.textContent = 'Sales person name is required.';
    return;
  }

  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving...';
  try {
    const res = await fetch('/api/salespersons', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: nameVal }),
    });
    const data = await res.json();
    if (res.status === 409) {
      errEl.textContent = 'Sales person already exists.';
      return;
    }
    if (!res.ok) {
      errEl.textContent = data.error || 'Failed to save sales person.';
      return;
    }
    salespersons.push({ id: data.id, name: data.name });
    salespersons.sort((a, b) => a.name.localeCompare(b.name));
    renderSalespersonOptions(data.name);
    closeAddSalespersonModal();
  } catch (err) {
    errEl.textContent = 'Network error: ' + err.message;
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save';
  }
}

document.getElementById('add-salesperson-modal').addEventListener('click', function (e) {
  if (e.target === this) closeAddSalespersonModal();
});

// ----------------------------------------------------------------
// WhatsApp / share post-save actions
// ----------------------------------------------------------------
function formatDate(isoStr) {
  if (!isoStr) return '';
  const [y, m, d] = isoStr.split('-');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${parseInt(d, 10)} ${months[parseInt(m, 10) - 1]} ${y}`;
}

function formatCurrency(amount) {
  return fmt(amount);
}

function buildWhatsAppMessage(bill) {
  const shopName    = 'SHUBHAM NX';
  const shopAddress = 'Krishna Chowk, New Sangvi, Pune - 411061';
  const shopPhone   = '+91 9284630254';

  const dateStr = bill.bill_date
    ? formatDate(bill.bill_date)
    : new Date().toLocaleDateString('en-IN');

  const total     = formatCurrency(bill.final_total);
  const advance   = bill.advance_paid > 0 ? formatCurrency(bill.advance_paid) : null;
  const remaining = bill.remaining > 0    ? formatCurrency(bill.remaining)    : null;
  const shareLink = window.location.origin + '/bill/share/' + bill.bill_number;

  const lines = [];
  lines.push('Dear ' + bill.customer_name + ',');
  lines.push('');
  lines.push('Thank you for shopping at *' + shopName + '*! 🙏');
  lines.push('');
  lines.push('*Bill Details:*');
  lines.push('Bill No : ' + bill.bill_number);
  lines.push('Date    : ' + dateStr);
  lines.push('Amount  : ' + total);
  if (advance)   lines.push('Advance : ' + advance);
  if (remaining) lines.push('Balance : ' + remaining + ' (pending)');
  lines.push('');
  lines.push('📄 View your bill here:');
  lines.push(shareLink);
  lines.push('');
  lines.push('📍 ' + shopAddress);
  lines.push('📞 ' + shopPhone);
  lines.push('');
  lines.push('⭐ Loved your purchase? Please leave us a review:');
  lines.push('https://maps.app.goo.gl/YjTCZZNLWwbjWZDH8');
  lines.push('');
  lines.push('We look forward to serving you again!');

  return lines.join('\n');
}

function buildWhatsAppURL(mobile, message) {
  let m = mobile.replace(/\D/g, '');
  if (m.length === 10)                          m = '91' + m;
  else if (m.length === 11 && m.startsWith('0')) m = '91' + m.slice(1);
  return 'https://wa.me/' + m + '?text=' + encodeURIComponent(message);
}

function buildShareLink(billNumber) {
  const base = window.SHARE_BASE_URL || window.location.origin;
  return base + '/bill/share/' + billNumber;
}

function showPostSaveActions(bill) {
  const waBtn = document.getElementById('whatsapp-btn');
  if (waBtn) waBtn.href = buildWhatsAppURL(bill.customer_mobile, buildWhatsAppMessage(bill));

  const shareBtn = document.getElementById('share-link-btn');
  if (shareBtn) {
    shareBtn.onclick = function () {
      copyToClipboard(buildShareLink(bill.bill_number));
      const msg = document.getElementById('link-copied-msg');
      if (msg) {
        msg.style.display = 'inline-flex';
        setTimeout(() => { msg.style.display = 'none'; }, 3000);
      }
    };
  }

  const section = document.getElementById('post-save-actions');
  if (section) section.style.display = 'flex';
}

function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).catch(() => { fallbackCopy(text); });
  } else {
    fallbackCopy(text);
  }
}

function fallbackCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0;';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try { document.execCommand('copy'); } catch (e) { console.warn('Copy failed:', e); }
  document.body.removeChild(ta);
}

// ----------------------------------------------------------------
// Save bill
// ----------------------------------------------------------------
async function saveBill() {
  const data = collectBillData();
  if (!validateBillData(data)) return;

  const saveBtn = document.getElementById('btn-save');
  saveBtn.disabled    = true;
  saveBtn.textContent = 'Saving…';
  document.getElementById('save-error').textContent      = '';
  document.getElementById('save-success').style.display = 'none';

  try {
    const url    = EDIT_MODE ? `/api/bills/${BILL_ID}` : '/api/bills';
    const method = EDIT_MODE ? 'PUT' : 'POST';

    const res    = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(data),
    });
    const result = await res.json();

    if (!res.ok) {
      document.getElementById('save-error').textContent = result.error || 'Failed to save bill.';
      saveBtn.disabled    = false;
      saveBtn.textContent = EDIT_MODE ? '\u2713 Update Bill' : '\u2713 Save Bill';
      return;
    }

    billSaved = true;  // disable beforeunload guard

    if (EDIT_MODE) {
      const successEl         = document.getElementById('save-success');
      successEl.style.display = 'inline';
      successEl.textContent   = 'Bill updated successfully!';
      saveBtn.textContent     = '\u2713 Updated';
      setTimeout(() => { window.location.href = `/bills/${BILL_ID}`; }, 1500);
    } else {
      savedBillId = result.id;
      const successEl         = document.getElementById('save-success');
      successEl.style.display = 'inline';
      successEl.textContent   = `Bill ${result.bill_number} saved successfully!`;
      document.getElementById('btn-print').disabled = false;
      saveBtn.textContent = '\u2713 Saved';
      showPostSaveActions(result);
    }

  } catch (err) {
    document.getElementById('save-error').textContent = 'Network error: ' + err.message;
    saveBtn.disabled    = false;
    saveBtn.textContent = EDIT_MODE ? '\u2713 Update Bill' : '\u2713 Save Bill';
  }
}

// ----------------------------------------------------------------
// Print / PDF
// ----------------------------------------------------------------
function doPrint() {
  if (savedBillId) window.location.href = `/bills/${savedBillId}`;
}

// ----------------------------------------------------------------
// Inventory badge helpers
// ----------------------------------------------------------------
function showInventoryBadge(id, show) {
  const badge = document.getElementById(`inv-badge-${id}`);
  if (badge) badge.style.display = show ? '' : 'none';
}

function clearInventoryLink(id) {
  if (!itemDataStore[id]) return;
  itemDataStore[id].inventoryItemId = null;
  showInventoryBadge(id, false);
}

// ----------------------------------------------------------------
// QR Scanner — dual mode: USB/manual input + camera (HTTPS only)
// ----------------------------------------------------------------
function openQrScanModal() {
  qrScanLock = false;
  document.getElementById('qr-scan-error').textContent = '';
  document.getElementById('qr-manual-input').value = '';
  document.getElementById('qr-reader').style.display    = 'none';
  document.getElementById('btn-stop-camera').style.display = 'none';
  document.getElementById('btn-start-camera').style.display = '';
  document.getElementById('qr-scan-modal').classList.remove('hidden');
  document.getElementById('qr-manual-input').focus();
}

function closeQrScanModal() {
  stopCamera();
  document.getElementById('qr-scan-modal').classList.add('hidden');
}

// ---- Manual / USB scanner input ----
async function applyManualQr() {
  const raw = document.getElementById('qr-manual-input').value.trim();
  if (!raw) return;

  let text = raw;
  // If user typed just a plain number, treat it as an inventory item ID
  if (/^\d+$/.test(raw)) text = 'inv:' + raw;

  document.getElementById('qr-manual-input').value = '';
  closeQrScanModal();
  await processQrText(text);
}

// ---- Camera (only works on HTTPS / localhost) ----
function startCamera() {
  document.getElementById('qr-scan-error').textContent = '';

  if (typeof Html5Qrcode === 'undefined') {
    document.getElementById('qr-scan-error').textContent =
      'QR library not loaded — check internet connection.';
    return;
  }
  if (!window.isSecureContext) {
    document.getElementById('qr-scan-error').textContent =
      'Camera requires HTTPS. Use a USB scanner or type the item ID instead.';
    return;
  }

  document.getElementById('btn-start-camera').style.display = 'none';
  document.getElementById('qr-reader').style.display = '';
  document.getElementById('btn-stop-camera').style.display = '';

  html5QrScanner = new Html5Qrcode('qr-reader');
  Html5Qrcode.getCameras().then(cameras => {
    if (!cameras || !cameras.length) {
      document.getElementById('qr-scan-error').textContent = 'No camera found on this device.';
      stopCamera();
      return;
    }
    const cameraId = cameras[cameras.length - 1].id;
    html5QrScanner.start(
      cameraId,
      { fps: 10, qrbox: { width: 220, height: 220 } },
      onQrScanned,
      () => {}
    ).catch(err => {
      document.getElementById('qr-scan-error').textContent = 'Camera error: ' + err;
      stopCamera();
    });
  }).catch(err => {
    document.getElementById('qr-scan-error').textContent =
      'Camera access denied. Use USB scanner or type the item ID.';
    stopCamera();
  });
}

function stopCamera() {
  if (html5QrScanner) {
    html5QrScanner.stop().catch(() => {}).finally(() => {
      html5QrScanner.clear();
      html5QrScanner = null;
    });
  }
  const readerEl  = document.getElementById('qr-reader');
  const startBtn  = document.getElementById('btn-start-camera');
  const stopBtn   = document.getElementById('btn-stop-camera');
  if (readerEl) readerEl.style.display = 'none';
  if (startBtn) startBtn.style.display = '';
  if (stopBtn)  stopBtn.style.display  = 'none';
}

async function onQrScanned(text) {
  if (qrScanLock) return;   // ignore duplicate fires from the same QR code
  qrScanLock = true;

  if (html5QrScanner) {
    await html5QrScanner.stop().catch(() => {});
    html5QrScanner = null;
  }
  closeQrScanModal();
  await processQrText(text);
}

// ---- Shared QR processing (used by both modes) ----
async function processQrText(text) {
  if (text.startsWith('inv:')) {
    const itemId = parseInt(text.slice(4), 10);
    if (isNaN(itemId)) { alert('Invalid inventory QR code.'); return; }
    try {
      const res = await fetch(`/api/inventory/${itemId}`);
      if (!res.ok) { alert('Inventory item not found (ID ' + itemId + ').'); return; }
      const item = await res.json();
      await fillRowFromInventoryItem(item);
    } catch (e) {
      alert('Failed to fetch inventory item: ' + e.message);
    }
  } else if (text.startsWith('cs:')) {
    try {
      const data = JSON.parse(text.slice(3));
      await fillRowFromCurrentStock(data);
    } catch (e) {
      alert('Invalid current stock QR code.');
    }
  } else {
    alert('Unrecognised QR. Expected an Inventory or Current Stock QR from this system.');
  }
}

function findOrAddRow() {
  // Reuse the first row that has no qty AND no mrp entered, else add a new one
  for (const id of activeItemIds) {
    const qty = parseFloat(document.getElementById(`qty-${id}`)?.value) || 0;
    const mrp = parseFloat(document.getElementById(`mrp-${id}`)?.value) || 0;
    if (qty === 0 && mrp === 0) return id;
  }
  addItemRow();
  return activeItemIds[activeItemIds.length - 1];
}

async function fillRowFromInventoryItem(item) {
  const id = findOrAddRow();

  itemDataStore[id].inventoryItemId = item.id;

  const mrpEl  = document.getElementById(`mrp-${id}`);
  const qualEl = document.getElementById(`quality-${id}`);
  if (mrpEl)  mrpEl.value  = item.mrp;
  if (qualEl) qualEl.value = item.quality_number || '';

  await onClothChangeRestoring(id, item.cloth_type, item.company_name || '');
  showInventoryBadge(id, true);
  recalcRow(id);

  const qtyEl = document.getElementById(`qty-${id}`);
  if (qtyEl) { qtyEl.value = ''; qtyEl.focus(); }
}

async function fillRowFromCurrentStock(data) {
  const id = findOrAddRow();

  // inventoryItemId stays null — no deduction
  const mrpEl  = document.getElementById(`mrp-${id}`);
  const qualEl = document.getElementById(`quality-${id}`);
  if (mrpEl)  mrpEl.value  = data.mrp || '';
  if (qualEl) qualEl.value = data.quality_number || '';

  await onClothChangeRestoring(id, data.cloth_type || 'Shirting', data.company_name || '');
  recalcRow(id);

  const qtyEl = document.getElementById(`qty-${id}`);
  if (qtyEl) { qtyEl.value = ''; qtyEl.focus(); }
}

document.getElementById('qr-scan-modal').addEventListener('click', function(e) {
  if (e.target === this) closeQrScanModal();
});
