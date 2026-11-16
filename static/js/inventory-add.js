/* ============================================================
   inventory-add.js — Inventory page - adding and editing stock: Add Item, Edit Item, Batch Add and New Invoice modals.
   Part of the Inventory page; shares globals with inventory.js (load order matters:
   see inventory.html). Code moved here unchanged from the old single inventory.js.
   ============================================================ */

// ----------------------------------------------------------------
// Batch Add Modal
// ----------------------------------------------------------------
function openBatchModal(preselectedInvoiceId) {
  baGroupCounter = 0;
  baRowCounters  = {};
  document.getElementById('ba-groups').innerHTML = '';
  document.getElementById('ba-error').textContent = '';
  document.getElementById('ba-save-count').textContent = '';
  loadInvoicesForBatchSelect(preselectedInvoiceId);
  document.getElementById('batch-add-modal').classList.remove('hidden');
  addBaGroup();
}

function closeBatchModal() {
  document.getElementById('batch-add-modal').classList.add('hidden');
}

function openNewInvoiceFromBatch() {
  document.getElementById('batch-add-modal').classList.add('hidden');
  openNewInvoiceModal(function(inv) {
    loadInvoicesForSelect(inv.id);
    loadInvoicesForBatchSelect(inv.id);
    document.getElementById('ba-invoice').value = inv.id;
    onBaInvoiceChange();
    document.getElementById('batch-add-modal').classList.remove('hidden');
  });
}

function addBaGroup(preCloth, preCompany) {
  const gid = ++baGroupCounter;
  baRowCounters[gid] = 0;

  const container = document.getElementById('ba-groups');
  const div = document.createElement('div');
  div.id = `ba-group-${gid}`;
  div.className = 'ba-group';
  div.style.cssText = 'border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:14px;';

  const removeBtn = gid > 1
    ? `<button type="button" class="btn btn-sm" style="color:var(--danger);margin-left:auto;" onclick="removeBaGroup(${gid})">Remove Group</button>`
    : '';

  div.innerHTML = `
    <div style="display:flex;gap:10px;align-items:flex-end;margin-bottom:12px;flex-wrap:wrap;">
      <div style="flex:1;min-width:140px;">
        <label style="font-size:12px;font-weight:600;">Cloth Type <span class="text-danger">*</span></label>
        <select id="ba-cloth-${gid}" class="input select" style="margin-top:4px;" onchange="onBaClothChange(${gid})">
          <option value="">— Select —</option>
        </select>
      </div>
      <div style="flex:1;min-width:140px;">
        <label style="font-size:12px;font-weight:600;">Company <span class="text-danger">*</span></label>
        <select id="ba-company-${gid}" class="input select" style="margin-top:4px;" onchange="onBaCompanyChange(${gid})">
          <option value="">— Select cloth type first —</option>
        </select>
        <div id="ba-company-add-row-${gid}" style="display:none;margin-top:6px;">
          <div style="display:flex;gap:6px;align-items:center;">
            <input type="text" id="ba-company-new-${gid}" class="input" placeholder="New company name" style="flex:1;" />
            <button type="button" class="btn btn-sm btn-primary" onclick="saveBaNewCompany(${gid})">Add</button>
            <button type="button" class="btn btn-sm btn-secondary" onclick="cancelBaCompanyAdd(${gid})" title="Cancel" aria-label="Cancel"><svg class="ico" aria-hidden="true"><use href="#i-x"/></svg></button>
          </div>
        </div>
      </div>
      <div style="min-width:70px;">
        <label style="font-size:12px;font-weight:600;">Unit</label>
        <select id="ba-unit-${gid}" class="input select" style="margin-top:4px;width:75px;">
          <option value="m">m</option>
          <option value="pcs">pcs</option>
        </select>
      </div>
      ${removeBtn}
    </div>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;min-width:720px;">
        <thead>
          <tr style="border-bottom:2px solid var(--border);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.4px;">
            <th style="padding:4px 6px;text-align:left;min-width:110px;">Item Name</th>
            <th style="padding:4px 6px;text-align:left;min-width:80px;">Shade No.</th>
            <th style="padding:4px 6px;text-align:left;min-width:80px;">Quality No.</th>
            <th style="padding:4px 6px;text-align:right;min-width:75px;">CP (&#8377;)</th>
            <th style="padding:4px 6px;text-align:right;min-width:75px;">MRP (&#8377;)</th>
            <th style="padding:4px 6px;text-align:right;min-width:65px;">Stock</th>
            <th style="padding:4px 6px;text-align:right;min-width:60px;">Alert</th>
            <th style="padding:4px 6px;text-align:left;min-width:90px;">Notes</th>
            <th style="width:28px;"></th>
          </tr>
        </thead>
        <tbody id="ba-tbody-${gid}"></tbody>
      </table>
    </div>
    <button type="button" class="btn btn-secondary btn-sm" onclick="addBaRow(${gid})" style="margin-top:8px;">&#43; Add Row</button>
  `;

  container.appendChild(div);
  populateClothTypeSelect(`ba-cloth-${gid}`, preCloth || '');
  if (preCompany) populateCompanySelect(`ba-company-${gid}`, preCloth, preCompany);
  addBaRow(gid);
}

function removeBaGroup(gid) {
  const el = document.getElementById(`ba-group-${gid}`);
  if (el) el.remove();
}

function addBaRow(gid) {
  const rowId = ++baRowCounters[gid];
  const tbody = document.getElementById(`ba-tbody-${gid}`);
  if (!tbody) return;

  const s = 'width:100%;padding:4px 6px;border:1px solid var(--border);border-radius:4px;background:var(--surface);color:var(--text);font-size:13px;box-sizing:border-box;';
  const sr = s + 'text-align:right;';

  const tr = document.createElement('tr');
  tr.id = `ba-row-${gid}-${rowId}`;
  tr.style.borderBottom = '1px solid var(--border)';
  tr.innerHTML = `
    <td style="padding:3px 4px;"><input type="text"   style="${s}"  placeholder="Item name" /></td>
    <td style="padding:3px 4px;"><input type="text"   style="${s}"  placeholder="Shade no." /></td>
    <td style="padding:3px 4px;"><input type="text"   style="${s}"  placeholder="Quality no." /></td>
    <td style="padding:3px 4px;"><input type="number" style="${sr}" placeholder="0.00" min="0" step="0.01" /></td>
    <td style="padding:3px 4px;"><input type="number" style="${sr}" placeholder="0.00" min="0" step="0.01" /></td>
    <td style="padding:3px 4px;"><input type="number" style="${sr}" placeholder="0"    min="0" step="0.01" /></td>
    <td style="padding:3px 4px;"><input type="number" style="${sr}" value="2"           min="0" step="0.01" /></td>
    <td style="padding:3px 4px;"><input type="text"   style="${s}"  placeholder="Optional" /></td>
    <td style="padding:3px 4px;text-align:center;">
      <button type="button" style="background:none;border:none;cursor:pointer;color:var(--danger);display:inline-flex;align-items:center;" onclick="removeBaRow(${gid},${rowId})" aria-label="Remove row"><svg class="ico" aria-hidden="true"><use href="#i-x"/></svg></button>
    </td>
  `;
  tbody.appendChild(tr);
  tr.querySelector('input').focus();
}

function removeBaRow(gid, rowId) {
  const el = document.getElementById(`ba-row-${gid}-${rowId}`);
  if (el) el.remove();
}

async function onBaClothChange(gid) {
  const clothType = document.getElementById(`ba-cloth-${gid}`).value;
  const unitSel   = document.getElementById(`ba-unit-${gid}`);
  if (clothType === 'Shirting' || clothType === 'Suiting') {
    unitSel.value = 'm';
  } else if (clothType) {
    unitSel.value = 'pcs';
  }
  cancelBaCompanyAdd(gid);
  await populateCompanySelect(`ba-company-${gid}`, clothType, '');
}

function onBaCompanyChange(gid) {
  const sel    = document.getElementById(`ba-company-${gid}`);
  const addRow = document.getElementById(`ba-company-add-row-${gid}`);
  if (sel.value === '__add__') {
    addRow.style.display = '';
    document.getElementById(`ba-company-new-${gid}`).focus();
  } else {
    addRow.style.display = 'none';
  }
}

async function saveBaNewCompany(gid) {
  const cloth = document.getElementById(`ba-cloth-${gid}`).value;
  const input = document.getElementById(`ba-company-new-${gid}`);
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
    document.getElementById(`ba-company-add-row-${gid}`).style.display = 'none';
    await populateCompanySelect(`ba-company-${gid}`, cloth, data.company_name);
  } catch (e) { alert('Network error: ' + e.message); }
}

function cancelBaCompanyAdd(gid) {
  const input  = document.getElementById(`ba-company-new-${gid}`);
  const addRow = document.getElementById(`ba-company-add-row-${gid}`);
  if (input)  input.value = '';
  if (addRow) addRow.style.display = 'none';
  const sel = document.getElementById(`ba-company-${gid}`);
  if (sel && sel.value === '__add__') sel.value = '';
}

async function saveBatch() {
  const errEl   = document.getElementById('ba-error');
  const btn     = document.getElementById('btn-ba-save');
  const cntEl   = document.getElementById('ba-save-count');
  errEl.textContent = '';
  cntEl.textContent = '';

  const invoiceRaw = document.getElementById('ba-invoice').value;
  const invoiceId  = invoiceRaw ? parseInt(invoiceRaw) : null;

  const groups = [];
  for (const groupEl of document.querySelectorAll('.ba-group')) {
    const gid        = groupEl.id.replace('ba-group-', '');
    const clothType  = document.getElementById(`ba-cloth-${gid}`).value;
    const company    = document.getElementById(`ba-company-${gid}`).value;
    const unit       = document.getElementById(`ba-unit-${gid}`).value;

    if (!clothType || clothType === '__add__') { errEl.textContent = 'Select a cloth type for every group.'; return; }
    if (!company   || company   === '__add__') { errEl.textContent = 'Select a company for every group.'; return; }

    const items = [];
    for (const tr of document.querySelectorAll(`#ba-tbody-${gid} tr`)) {
      const inp = tr.querySelectorAll('input');
      const item_name      = inp[0].value.trim();
      const shade_number   = inp[1].value.trim();
      const quality_number = inp[2].value.trim();
      const cost_price     = parseFloat(inp[3].value) || 0;
      const mrp            = parseFloat(inp[4].value) || 0;
      const opening_stock  = parseFloat(inp[5].value) || 0;
      const min_stock_alert = parseFloat(inp[6].value) || 2;
      const notes          = inp[7].value.trim();
      if (!item_name && !shade_number && !quality_number && !cost_price && !mrp) continue;
      items.push({ item_name, shade_number, quality_number, cost_price, mrp,
                   opening_stock, min_stock_alert, notes, unit_label: unit });
    }
    if (items.length) groups.push({ cloth_type: clothType, company_name: company, items });
  }

  const totalItems = groups.reduce((s, g) => s + g.items.length, 0);
  if (!totalItems) { errEl.textContent = 'Add at least one item row with some data.'; return; }

  btn.disabled = true;
  try {
    const res  = await fetch('/api/inventory/batch', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ invoice_id: invoiceId, groups }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error || 'Save failed.'; return; }
    closeBatchModal();
    await loadInventory();
  } catch (e) {
    errEl.textContent = 'Network error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('batch-add-modal').addEventListener('click', function(e) {
  if (e.target === this) closeBatchModal();
});

// ----------------------------------------------------------------
// New Invoice Modal
// ----------------------------------------------------------------
async function loadNiSuppliersForSelect(restoreId) {
  try {
    const res  = await fetch('/api/suppliers');
    const list = await res.json();
    const sel  = document.getElementById('ni-supplier');
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

function onNiSupplierChange() {
  const sel    = document.getElementById('ni-supplier');
  const addRow = document.getElementById('ni-supplier-add-row');
  if (sel.value === '__add__') {
    addRow.style.display = '';
    document.getElementById('ni-supplier-new').focus();
  } else {
    addRow.style.display = 'none';
  }
}

async function saveNiNewSupplier() {
  const input = document.getElementById('ni-supplier-new');
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
    document.getElementById('ni-supplier-add-row').style.display = 'none';
    await loadNiSuppliersForSelect(data.id);
    await loadSuppliersForSelect(data.id);
  } catch (e) { alert('Network error: ' + e.message); }
}

function cancelNiSupplierAdd() {
  document.getElementById('ni-supplier-new').value = '';
  document.getElementById('ni-supplier-add-row').style.display = 'none';
  document.getElementById('ni-supplier').value = '';
}

function openNewInvoiceModal(afterSaveCallback) {
  document.getElementById('ni-number').value = '';
  document.getElementById('ni-date').value   = new Date().toISOString().slice(0, 10);
  document.getElementById('ni-notes').value  = '';
  document.getElementById('ni-error').textContent = '';
  document.getElementById('ni-supplier-new').value = '';
  document.getElementById('ni-supplier-add-row').style.display = 'none';
  loadNiSuppliersForSelect();
  document.getElementById('new-invoice-modal')._afterSave = afterSaveCallback || null;
  document.getElementById('new-invoice-modal').classList.remove('hidden');
  document.getElementById('ni-number').focus();
}

function closeNewInvoiceModal() {
  document.getElementById('new-invoice-modal').classList.add('hidden');
}

function openNewInvoiceFromAddItem() {
  closeAddItemModal();
  openNewInvoiceModal((inv) => {
    loadInvoicesForSelect(inv.id);
    openAddItemModal(inv.id);
  });
}

async function saveNewInvoice() {
  const errEl = document.getElementById('ni-error');
  const btn   = document.getElementById('btn-ni-save');
  const num   = document.getElementById('ni-number').value.trim();
  const date  = document.getElementById('ni-date').value.trim();
  const suppRaw = document.getElementById('ni-supplier').value;

  errEl.textContent = '';
  if (!num)  { errEl.textContent = 'Invoice number is required.'; return; }
  if (!date) { errEl.textContent = 'Invoice date is required.'; return; }

  btn.disabled = true;
  try {
    const res = await fetch('/api/invoices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        invoice_number: num,
        invoice_date:   date,
        supplier_id:    suppRaw ? parseInt(suppRaw) : null,
        notes:          document.getElementById('ni-notes').value.trim(),
      }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error || 'Save failed.'; return; }
    closeNewInvoiceModal();
    const cb = document.getElementById('new-invoice-modal')._afterSave;
    if (cb) cb(data);
    else await loadInvoicesForSelect(data.id);
  } catch (e) {
    errEl.textContent = 'Network error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('new-invoice-modal').addEventListener('click', function(e) {
  if (e.target === this) closeNewInvoiceModal();
});

// ----------------------------------------------------------------
// Add Item Modal
// ----------------------------------------------------------------
function openAddItemModal(preselectedInvoiceId) {
  document.getElementById('ai-invoice').value  = preselectedInvoiceId || '';
  onAiInvoiceChange();
  document.getElementById('ai-cloth').value   = '';
  document.getElementById('ai-company').innerHTML = '<option value="">— Select cloth type first —</option>';
  document.getElementById('ai-supplier').value = '';
  ['ai-quality','ai-mrp','ai-cp','ai-opening','ai-notes','ai-item-name','ai-shade',
   'ai-cloth-new','ai-company-new','ai-supplier-new','ai-special-code'].forEach(id => {
    document.getElementById(id).value = '';
  });
  ['ai-cloth-add-row','ai-company-add-row','ai-supplier-add-row'].forEach(id => {
    document.getElementById(id).style.display = 'none';
  });
  document.getElementById('ai-alert').value = '2';
  document.getElementById('ai-unit').value  = 'm';
  document.getElementById('ai-error').textContent = '';
  document.getElementById('add-item-modal').classList.remove('hidden');
  document.getElementById('ai-cloth').focus();
}

function closeAddItemModal() {
  document.getElementById('add-item-modal').classList.add('hidden');
  resetScanState();
}

async function saveNewItem() {
  updateAiSpecialCode();
  const cloth      = document.getElementById('ai-cloth').value;
  const company    = document.getElementById('ai-company').value;
  const suppRaw    = document.getElementById('ai-supplier').value;
  const errEl      = document.getElementById('ai-error');
  const saveBtn    = document.getElementById('btn-ai-save');

  errEl.textContent = '';
  if (!cloth   || cloth   === '__add__') { errEl.textContent = 'Select a cloth type.'; return; }
  if (!company || company === '__add__') { errEl.textContent = 'Select a company.'; return; }

  const qualityVal  = document.getElementById('ai-quality').value.trim();
  const shadeVal    = document.getElementById('ai-shade').value.trim();
  const itemNameVal = document.getElementById('ai-item-name').value.trim();
  if (!qualityVal && !shadeVal && !itemNameVal) {
    errEl.textContent = 'Fill at least one of: Item Name, Quality No., or Shade No.'; return;
  }

  const openingVal = document.getElementById('ai-opening').value;
  if (openingVal === '' || isNaN(parseFloat(openingVal))) {
    errEl.textContent = 'Enter the opening stock quantity.'; return;
  }

  const mrp = parseFloat(document.getElementById('ai-mrp').value);
  if (isNaN(mrp) || mrp < 0) { errEl.textContent = 'Enter a valid MRP.'; return; }

  saveBtn._scanWarned = false;

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
        cost_price:      parseFloat(document.getElementById('ai-cp').value) || 0,
        opening_stock:   parseFloat(document.getElementById('ai-opening').value) || 0,
        min_stock_alert: parseFloat(document.getElementById('ai-alert').value) || 2,
        notes:           document.getElementById('ai-notes').value.trim(),
        supplier_id:     supplierId,
        item_name:       document.getElementById('ai-item-name').value.trim(),
        shade_number:    document.getElementById('ai-shade').value.trim(),
        invoice_id:      document.getElementById('ai-invoice').value ? parseInt(document.getElementById('ai-invoice').value) : null,
        special_code:    document.getElementById('ai-special-code').value.trim(),
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

async function saveAllScanItems() {
  _saveCurrentItemEdits();  // capture last item's edits

  const cloth   = document.getElementById('ai-cloth').value;
  const company = document.getElementById('ai-company').value;
  const errEl   = document.getElementById('ai-error');
  const btn     = document.getElementById('btn-ai-save-all');

  errEl.textContent = '';
  if (!cloth   || cloth   === '__add__') { errEl.textContent = 'Select a cloth type first.'; return; }
  if (!company || company === '__add__') { errEl.textContent = 'Select a company first.'; return; }

  const invoiceId  = document.getElementById('ai-invoice').value;
  const suppRaw    = document.getElementById('ai-supplier').value;
  const supplierId = (suppRaw && suppRaw !== '__add__') ? parseInt(suppRaw) : null;

  const group = {
    cloth_type:   cloth,
    company_name: company,
    supplier_id:  supplierId,
    items: _scanItems.map(item => ({
      item_name:       item.item_name      || '',
      quality_number:  item.quality_number || '',
      shade_number:    item.shade_number   || '',
      opening_stock:   item.opening_stock  || 0,
      unit_label:      item.unit_label     || 'm',
      notes:           item.notes          || '',
      mrp:             item.mrp            || 0,
      cost_price:      item.cost_price     || 0,
      min_stock_alert: item.min_stock_alert || 2,
    })),
  };

  btn.disabled = true;
  try {
    const res  = await fetch('/api/inventory/batch', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        invoice_id: invoiceId ? parseInt(invoiceId) : null,
        groups:     [group],
      }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error || 'Save failed.'; return; }
    closeAddItemModal();
    await loadInventory();
  } catch (e) {
    errEl.textContent = 'Network error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

// ----------------------------------------------------------------
// Edit Item Modal
// ----------------------------------------------------------------
function updateEiSpecialCode() {
  const cp     = document.getElementById('ei-cp').value;
  const supSel = document.getElementById('ei-supplier');
  const supOpt = supSel.options[supSel.selectedIndex];
  const supName = supSel.value ? (supOpt ? supOpt.textContent : '') : '';
  document.getElementById('ei-special-code').value = computeSpecialCode(cp, supName);
}

function openEditItemModal(id) {
  const item = allItems.find(i => i.id === id);
  if (!item) return;
  document.getElementById('ei-id').value        = item.id;
  document.getElementById('ei-invoice-id').value = item.invoice_id || '';
  const invFieldsEl = document.getElementById('ei-invoice-fields');
  if (item.invoice_id) {
    invFieldsEl.style.display = 'grid';
    document.getElementById('ei-invoice-number').value = item.invoice_number || '';
    document.getElementById('ei-invoice-date').value   = item.invoice_date || '';
  } else {
    invFieldsEl.style.display = 'none';
  }
  document.getElementById('ei-mrp').value       = item.mrp;
  document.getElementById('ei-cp').value        = item.cost_price || 0;
  document.getElementById('ei-quality').value   = item.quality_number || '';
  document.getElementById('ei-alert').value     = item.min_stock_alert;
  document.getElementById('ei-notes').value     = item.notes || '';
  document.getElementById('ei-item-name').value = item.item_name || '';
  document.getElementById('ei-shade').value     = item.shade_number || '';
  document.getElementById('ei-supplier').value  = item.effective_supplier_id != null ? String(item.effective_supplier_id) : '';
  document.getElementById('ei-error').textContent = '';
  document.getElementById('edit-item-title').textContent =
    `Edit — ${item.cloth_type} / ${item.company_name}${item.item_name ? ' / ' + item.item_name : ''}${item.quality_number ? ' / ' + item.quality_number : ''}`;
  updateEiSpecialCode();
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

  const invoiceId = document.getElementById('ei-invoice-id').value;
  if (invoiceId) {
    const invNum  = document.getElementById('ei-invoice-number').value.trim();
    const invDate = document.getElementById('ei-invoice-date').value.trim();
    if (!invNum)  { errEl.textContent = 'Invoice number is required.'; return; }
    if (!invDate) { errEl.textContent = 'Invoice date is required.'; return; }
  }

  btn.disabled = true;
  try {
    if (invoiceId) {
      const invRes = await fetch(`/api/invoices/${invoiceId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          invoice_number: document.getElementById('ei-invoice-number').value.trim(),
          invoice_date:   document.getElementById('ei-invoice-date').value.trim(),
        }),
      });
      const invData = await invRes.json();
      if (!invRes.ok) { errEl.textContent = invData.error || 'Invoice save failed.'; return; }
    }

    const res = await fetch(`/api/inventory/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mrp:             parseFloat(document.getElementById('ei-mrp').value) || 0,
        cost_price:      parseFloat(document.getElementById('ei-cp').value) || 0,
        quality_number:  document.getElementById('ei-quality').value.trim(),
        supplier_id:     document.getElementById('ei-supplier').value || null,
        min_stock_alert: parseFloat(document.getElementById('ei-alert').value) || 2,
        notes:           document.getElementById('ei-notes').value.trim(),
        item_name:       document.getElementById('ei-item-name').value.trim(),
        shade_number:    document.getElementById('ei-shade').value.trim(),
        special_code:    document.getElementById('ei-special-code').value.trim(),
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

