/* ============================================================
   bill-items.js — Item rows/cards, cloth types, inventory links
   Depends on: bill-state.js, bill-payments.js (updateSummary)
   ============================================================ */

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

// ---- Company fetching (with cache) ----
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

// ---- Cloth type change → reload company dropdown + update unit ----
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

// ---- Keyboard nav: Enter moves qty→mrp→disc→next row ----
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

// ---- addItemRow — entry point, branches on layout ----
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

// ---- Desktop: append a table row for item `id` ----
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

// ---- Mobile: append a card for item `id` ----
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

// ---- Remove item — works for both table rows and cards ----
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

// ---- Row / card calculations ----
function recalcRow(id) {
  const mrp        = parseFloat(document.getElementById(`mrp-${id}`)?.value)     || 0;
  const discPct    = parseFloat(document.getElementById(`disc-${id}`)?.value)    || 0;
  const discAmtRaw = parseFloat(document.getElementById(`discamt-${id}`)?.value);
  const qty        = parseFloat(document.getElementById(`qty-${id}`)?.value)     || 0;

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
  const rateEl  = document.getElementById(`rateafterdisc-${id}`);
  const finalEl = document.getElementById(`finalamt-${id}`);
  if (rateEl)  rateEl.textContent  = fmt(rateAfterDisc);
  if (finalEl) finalEl.textContent = fmt(finalAmt);

  const cardMrpEl   = document.getElementById(`card-mrp-${id}`);
  const cardDiscEl  = document.getElementById(`card-disc-${id}`);
  const cardRateEl  = document.getElementById(`card-rate-${id}`);
  const cardFinalEl = document.getElementById(`card-finalamt-${id}`);
  if (cardMrpEl)   cardMrpEl.textContent   = fmt(mrp);
  if (cardDiscEl)  cardDiscEl.textContent  = discPerUnit > 0 ? `−${fmt(discPerUnit)}` : '—';
  if (cardRateEl)  cardRateEl.textContent  = fmt(rateAfterDisc);
  if (cardFinalEl) cardFinalEl.textContent = fmt(finalAmt);

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

// ---- Responsive: re-render items when crossing the 768px boundary ----
function handleResponsiveItemsLayout() {
  const mobile = isMobile();
  if (mobile === lastIsMobile) return;
  lastIsMobile = mobile;

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

  document.getElementById('items-body').innerHTML        = '';
  document.getElementById('items-cards-wrapper').innerHTML = '';

  snapshots.forEach(snap => {
    if (mobile) {
      appendCard(snap.id, snap);
    } else {
      appendTableRow(snap.id, snap);
    }
    recalcRow(snap.id);
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

// ---- Inventory badge helpers ----
function showInventoryBadge(id, show) {
  const badge = document.getElementById(`inv-badge-${id}`);
  if (badge) badge.style.display = show ? '' : 'none';
}

function clearInventoryLink(id) {
  if (!itemDataStore[id]) return;
  itemDataStore[id].inventoryItemId = null;
  showInventoryBadge(id, false);
}

// ---- QR fill helpers ----
function findOrAddRow() {
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

  const mrpEl  = document.getElementById(`mrp-${id}`);
  const qualEl = document.getElementById(`quality-${id}`);
  if (mrpEl)  mrpEl.value  = data.mrp || '';
  if (qualEl) qualEl.value = data.quality_number || '';

  await onClothChangeRestoring(id, data.cloth_type || 'Shirting', data.company_name || '');
  recalcRow(id);

  const qtyEl = document.getElementById(`qty-${id}`);
  if (qtyEl) { qtyEl.value = ''; qtyEl.focus(); }
}

// ---- Add item button ----
document.getElementById('btn-add-item').addEventListener('click', () => {
  addItemRow();
  requestAnimationFrame(() => {
    const clothSel = document.getElementById(`cloth-${rowCounter}`);
    if (clothSel) clothSel.focus();
  });
});
