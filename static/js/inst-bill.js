/* ============================================================
   inst-bill.js — Institution Bill form logic
   ============================================================ */

const INST_COMBO_METHODS = ['Cash', 'Card', 'UPI', 'Cheque', 'NEFT'];

let instItemCounter = 0;
let instActiveIds   = [];
let instDataStore   = {};
let instCurrentMode = 'Cash';
let instAdvanceModified = false;
let instComboLastChanged = null;
let instClothTypes  = [];
let instSalespersons = [];

function r2(v) { return Math.round(v * 100) / 100; }
function fmt(v) { return '₹' + Number(v).toFixed(2); }

// ---- Init ----
document.addEventListener('DOMContentLoaded', async function () {
  await Promise.all([loadInstClothTypes(), loadInstSalespersons()]);
  setupInstPaymentTabs();

  if (window.INST_BILL_ID) {
    await loadInstBillForEdit(window.INST_BILL_ID);
  } else {
    document.getElementById('inst-bill-date').value = istToday();
    addInstItem();
    updateInstSummary();
  }
});

async function loadInstClothTypes() {
  try {
    const res = await fetch('/api/cloth-types');
    const data = await res.json();
    instClothTypes = data;
  } catch (e) { console.error('Failed to load cloth types', e); }
}

async function loadInstSalespersons() {
  try {
    const res = await fetch('/api/salespersons');
    const data = await res.json();
    instSalespersons = data;
    const sel = document.getElementById('inst-salesperson');
    data.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.name;
      opt.textContent = s.name;
      sel.appendChild(opt);
    });
    if (data.some(s => s.name === 'Self')) sel.value = 'Self';
  } catch (e) { console.error('Failed to load salespersons', e); }
}

// ---- Item rows ----
function addInstItem() {
  const id = ++instItemCounter;
  instActiveIds.push(id);
  instDataStore[id] = { total: 0 };

  const tbody = document.getElementById('inst-items-body');
  const tr = document.createElement('tr');
  tr.id = `inst-row-${id}`;
  tr.innerHTML = `
    <td>
      <select class="input select inst-cloth-sel" id="inst-cloth-${id}"
              onchange="onInstClothChange(${id})">
        <option value="">-- Type --</option>
        ${instClothTypes.map(t => `<option value="${t.type_name}">${t.type_name}</option>`).join('')}
      </select>
    </td>
    <td>
      <select class="input select" id="inst-company-${id}">
        <option value="">-- Company --</option>
      </select>
    </td>
    <td>
      <input class="input" id="inst-quality-${id}" placeholder="Quality No" />
    </td>
    <td>
      <input class="input" type="number" id="inst-qtypc-${id}" min="0" step="0.01"
             placeholder="0.00" oninput="calcInstRow(${id})" />
    </td>
    <td>
      <input class="input" type="number" id="inst-rate-${id}" min="0" step="0.01"
             placeholder="0.00" oninput="calcInstRow(${id})" />
    </td>
    <td>
      <input class="input" type="number" id="inst-pcs-${id}" min="0" step="1"
             placeholder="0" oninput="calcInstRow(${id})" />
    </td>
    <td>
      <input class="input" type="number" id="inst-stitch-${id}" min="0" step="0.01"
             placeholder="—" oninput="calcInstRow(${id})" />
    </td>
    <td class="inst-total-cell" id="inst-total-${id}">₹0.00</td>
    <td>
      <button class="inst-del-btn" onclick="removeInstItem(${id})" title="Remove">✕</button>
    </td>
  `;
  tbody.appendChild(tr);
}

async function onInstClothChange(id) {
  const clothType = document.getElementById(`inst-cloth-${id}`).value;
  const compSel   = document.getElementById(`inst-company-${id}`);
  compSel.innerHTML = '<option value="">-- Company --</option>';
  if (!clothType) return;
  try {
    const res  = await fetch(`/api/companies?clothType=${encodeURIComponent(clothType)}`);
    const data = await res.json();
    data.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.company_name;
      opt.textContent = c.company_name;
      compSel.appendChild(opt);
    });
  } catch (e) { console.error('Failed to load companies', e); }
}

function calcInstRow(id) {
  const qtyPerPc  = parseFloat(document.getElementById(`inst-qtypc-${id}`)?.value)   || 0;
  const ratePerM  = parseFloat(document.getElementById(`inst-rate-${id}`)?.value)    || 0;
  const noPcs     = parseFloat(document.getElementById(`inst-pcs-${id}`)?.value)     || 0;
  const stitching = parseFloat(document.getElementById(`inst-stitch-${id}`)?.value)  || 0;
  const total     = r2((qtyPerPc * ratePerM * noPcs) + (noPcs * stitching));
  instDataStore[id] = { ...instDataStore[id], total };
  document.getElementById(`inst-total-${id}`).textContent = fmt(total);
  updateInstSummary();
}

function removeInstItem(id) {
  if (instActiveIds.length <= 1) return;
  instActiveIds = instActiveIds.filter(i => i !== id);
  delete instDataStore[id];
  document.getElementById(`inst-row-${id}`)?.remove();
  updateInstSummary();
}

// ---- Summary ----
function updateInstSummary() {
  const total = r2(instActiveIds.reduce((s, id) => s + (instDataStore[id]?.total || 0), 0));
  document.getElementById('inst-sum-total').textContent = fmt(total);

  const advEl = document.getElementById('inst-advance-paid');
  if (advEl && !instAdvanceModified) advEl.value = total.toFixed(2);

  const advance   = r2(parseFloat(document.getElementById('inst-advance-paid')?.value) || 0);
  const remaining = r2(Math.max(0, total - advance));
  document.getElementById('inst-sum-remaining').textContent = fmt(remaining);

  const errEl = document.getElementById('err-advance');
  if (errEl) {
    if (advance < 0)          errEl.textContent = 'Advance cannot be negative.';
    else if (advance > total) errEl.textContent = 'Advance cannot exceed total payable.';
    else                      errEl.textContent = '';
  }

  if (instCurrentMode !== 'Combination') {
    const amtEl = document.getElementById('inst-payment-amount');
    if (amtEl) amtEl.value = advance.toFixed(2);
  } else {
    syncInstComboAutoFill();
  }
}

function onInstAdvancePaidInput() {
  instAdvanceModified = true;
  const advance = r2(parseFloat(document.getElementById('inst-advance-paid')?.value) || 0);
  if (instCurrentMode !== 'Combination') {
    const amtEl = document.getElementById('inst-payment-amount');
    if (amtEl) amtEl.value = advance.toFixed(2);
  }
  updateInstSummary();
}

function onInstPaymentAmountInput() {
  const amt   = r2(parseFloat(document.getElementById('inst-payment-amount').value) || 0);
  const advEl = document.getElementById('inst-advance-paid');
  if (advEl) advEl.value = amt.toFixed(2);
  instAdvanceModified = true;
  updateInstSummary();
}

// ---- Payment tabs ----
function setupInstPaymentTabs() {
  document.querySelectorAll('.inst-payment-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.inst-payment-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      instCurrentMode = btn.dataset.mode;
      onInstModeChange(instCurrentMode);
    });
  });
}

function onInstModeChange(mode) {
  const singleWrap = document.getElementById('inst-single-wrap');
  const comboWrap  = document.getElementById('inst-combo-wrap');
  const labelEl    = document.getElementById('inst-single-label');
  document.getElementById('err-payment').textContent = '';

  if (mode === 'Combination') {
    singleWrap.style.display = 'none';
    comboWrap.style.display  = 'block';
    syncInstComboAutoFill();
  } else {
    singleWrap.style.display = 'block';
    comboWrap.style.display  = 'none';
    labelEl.textContent      = `${mode} Amount (₹)`;
    const advance = r2(parseFloat(document.getElementById('inst-advance-paid')?.value) || 0);
    document.getElementById('inst-payment-amount').value = advance.toFixed(2);
  }
}

// ---- Combination ----
function onInstComboChange() {
  INST_COMBO_METHODS.forEach(m => {
    const amtEl = document.getElementById(`inst-combo-amt-${m}`);
    const chkEl = document.getElementById(`inst-combo-chk-${m}`);
    amtEl.disabled = !chkEl.checked;
    if (!chkEl.checked) amtEl.value = '';
  });
  instComboLastChanged = null;
  syncInstComboAutoFill();
}

function onInstComboAmtInput(method) {
  instComboLastChanged = method;
  syncInstComboAutoFill();
}

function syncInstComboAutoFill() {
  if (instCurrentMode !== 'Combination') return;
  const checked = INST_COMBO_METHODS.filter(m => document.getElementById(`inst-combo-chk-${m}`).checked);
  const remEl   = document.getElementById('inst-combo-remaining');
  if (checked.length < 2) { remEl.textContent = ''; return; }

  const total          = r2(instActiveIds.reduce((s, id) => s + (instDataStore[id]?.total || 0), 0));
  const autoMethod     = checked[checked.length - 1];
  const manualMethods  = checked.filter(m => m !== autoMethod);
  const manualSum      = manualMethods.reduce((s, m) =>
    s + (parseFloat(document.getElementById(`inst-combo-amt-${m}`).value) || 0), 0);
  const remaining      = r2(total - manualSum);
  const autoEl         = document.getElementById(`inst-combo-amt-${autoMethod}`);
  if (!autoEl.disabled) autoEl.value = remaining >= 0 ? remaining.toFixed(2) : '';

  const allSum = r2(checked.reduce((s, m) =>
    s + (parseFloat(document.getElementById(`inst-combo-amt-${m}`).value) || 0), 0));
  const diff = r2(allSum - total);
  if (Math.abs(diff) <= 0.01) {
    remEl.textContent = 'Payment balanced ✓';
    remEl.style.color = 'green';
  } else {
    remEl.textContent = `Remaining: ${fmt(r2(total - allSum))}`;
    remEl.style.color = 'red';
  }
}

// ---- Collect & Validate ----
function collectInstData() {
  const mode = instCurrentMode;
  const payments = [];
  if (mode === 'Combination') {
    INST_COMBO_METHODS.forEach(m => {
      if (document.getElementById(`inst-combo-chk-${m}`).checked) {
        payments.push({ payment_method: m,
                        amount: parseFloat(document.getElementById(`inst-combo-amt-${m}`).value) || 0 });
      }
    });
  } else if (mode && mode !== 'Pending') {
    payments.push({ payment_method: mode,
                    amount: parseFloat(document.getElementById('inst-payment-amount').value) || 0 });
  }

  const items = instActiveIds.map(id => ({
    cloth_type:        document.getElementById(`inst-cloth-${id}`).value,
    company_name:      document.getElementById(`inst-company-${id}`).value,
    quality_number:    document.getElementById(`inst-quality-${id}`).value,
    quantity_per_pc:   parseFloat(document.getElementById(`inst-qtypc-${id}`).value)   || 0,
    rate_per_m:        parseFloat(document.getElementById(`inst-rate-${id}`).value)     || 0,
    no_of_pcs:         parseInt(document.getElementById(`inst-pcs-${id}`).value)        || 0,
    stitching_per_unit: parseFloat(document.getElementById(`inst-stitch-${id}`)?.value) || 0,
  }));

  return {
    company_name:          document.getElementById('inst-company-name').value.trim(),
    company_address:       (document.getElementById('inst-company-address')?.value || '').trim(),
    contact_person_name:   document.getElementById('inst-contact-person').value.trim(),
    contact_person_mobile: document.getElementById('inst-mobile').value.trim(),
    bill_date:             document.getElementById('inst-bill-date').value,
    salesperson_name:      document.getElementById('inst-salesperson').value,
    payment_mode_type:     mode,
    advance_paid:          r2(parseFloat(document.getElementById('inst-advance-paid')?.value) || 0),
    items,
    payments,
  };
}

function clearInstErrors() {
  ['err-company','err-contact','err-mobile','err-salesperson','err-items','err-payment','err-advance','inst-save-error']
    .forEach(id => { const el = document.getElementById(id); if (el) el.textContent = ''; });
}

function validateInstData(data) {
  clearInstErrors();
  let valid = true;

  if (!data.company_name) {
    document.getElementById('err-company').textContent = 'Company name is required.'; valid = false;
  }
  if (data.contact_person_mobile && !/^[6-9]\d{9}$/.test(data.contact_person_mobile)) {
    document.getElementById('err-mobile').textContent = 'Enter a valid 10-digit mobile number.'; valid = false;
  }
  if (!data.salesperson_name) {
    document.getElementById('err-salesperson').textContent = 'Salesperson is required.'; valid = false;
  }
  if (!data.items.length || data.items.every(i => i.no_of_pcs === 0)) {
    document.getElementById('err-items').textContent = 'Add at least one item with quantities.'; valid = false;
  }

  const total = r2(instActiveIds.reduce((s, id) => s + (instDataStore[id]?.total || 0), 0));
  if (data.advance_paid < 0) {
    document.getElementById('err-advance').textContent = 'Advance cannot be negative.'; valid = false;
  } else if (data.advance_paid > total) {
    document.getElementById('err-advance').textContent = 'Advance cannot exceed total payable.'; valid = false;
  }

  if (data.payment_mode_type === 'Combination') {
    const checked = INST_COMBO_METHODS.filter(m => document.getElementById(`inst-combo-chk-${m}`).checked);
    if (checked.length < 2) {
      document.getElementById('err-payment').textContent = 'Select at least 2 methods for Combination.'; valid = false;
    } else {
      const sum = r2(data.payments.reduce((s, p) => s + p.amount, 0));
      if (Math.abs(sum - total) > 0.01) {
        document.getElementById('err-payment').textContent =
          `Payment sum (${fmt(sum)}) must equal total (${fmt(total)}).`; valid = false;
      }
    }
  }

  return valid;
}

// ---- Edit mode: load existing bill ----
async function loadInstBillForEdit(billId) {
  try {
    const res  = await fetch(`/api/institution-bills/${billId}`);
    if (!res.ok) throw new Error('Failed to load bill');
    const data = await res.json();
    const bill     = data.bill;
    const items    = data.items;
    const payments = data.payments;

    const warnEl = document.getElementById('edit-warning-bill-num');
    if (warnEl) warnEl.textContent = bill.bill_number;

    document.getElementById('inst-company-name').value    = bill.company_name    || '';
    const addrEl = document.getElementById('inst-company-address');
    if (addrEl) addrEl.value                             = bill.company_address || '';
    document.getElementById('inst-contact-person').value  = bill.contact_person_name || '';
    document.getElementById('inst-mobile').value          = bill.contact_person_mobile || '';
    document.getElementById('inst-bill-date').value       = bill.bill_date || '';
    document.getElementById('inst-salesperson').value     = bill.salesperson_name || '';

    // Pre-fill payment mode
    const mode = bill.payment_mode_type || 'Cash';
    if (mode === 'Combination' && payments.length) {
      document.querySelectorAll('.inst-payment-tab').forEach(b => b.classList.remove('active'));
      const comboTab = document.querySelector('.inst-payment-tab[data-mode="Combination"]');
      if (comboTab) comboTab.classList.add('active');
      instCurrentMode = 'Combination';
      onInstModeChange('Combination');
      payments.forEach(p => {
        const chk = document.getElementById(`inst-combo-chk-${p.payment_method}`);
        const amt = document.getElementById(`inst-combo-amt-${p.payment_method}`);
        if (chk) { chk.checked = true; }
        if (amt) { amt.disabled = false; amt.value = Number(p.amount).toFixed(2); }
      });
    } else {
      const safeMode = ['Cash','Card','UPI','Cheque','NEFT'].includes(mode) ? mode : 'Cash';
      document.querySelectorAll('.inst-payment-tab').forEach(b => b.classList.remove('active'));
      const modeTab = document.querySelector(`.inst-payment-tab[data-mode="${safeMode}"]`);
      if (modeTab) modeTab.classList.add('active');
      instCurrentMode = safeMode;
      onInstModeChange(safeMode);
    }

    // Pre-fill advance paid
    instAdvanceModified = true;
    const advEl = document.getElementById('inst-advance-paid');
    if (advEl) advEl.value = Number(bill.advance_paid || 0).toFixed(2);

    // Pre-fill items
    for (const item of items) {
      await populateInstItemForEdit(item);
    }

    updateInstSummary();
  } catch (err) {
    const errEl = document.getElementById('inst-save-error');
    if (errEl) errEl.textContent = 'Failed to load bill: ' + err.message;
  }
}

async function populateInstItemForEdit(item) {
  const id = ++instItemCounter;
  instActiveIds.push(id);
  instDataStore[id] = { total: item.total || 0 };

  const tbody = document.getElementById('inst-items-body');
  const tr = document.createElement('tr');
  tr.id = `inst-row-${id}`;
  tr.innerHTML = `
    <td>
      <select class="input select inst-cloth-sel" id="inst-cloth-${id}" onchange="onInstClothChange(${id})">
        <option value="">-- Type --</option>
        ${instClothTypes.map(t => `<option value="${t.type_name}"${t.type_name === item.cloth_type ? ' selected' : ''}>${t.type_name}</option>`).join('')}
      </select>
    </td>
    <td><select class="input select" id="inst-company-${id}"><option value="">-- Company --</option></select></td>
    <td><input class="input" id="inst-quality-${id}" placeholder="Quality No" value="${item.quality_number || ''}" /></td>
    <td><input class="input" type="number" id="inst-qtypc-${id}" min="0" step="0.01" placeholder="0.00" value="${item.quantity_per_pc || ''}" oninput="calcInstRow(${id})" /></td>
    <td><input class="input" type="number" id="inst-rate-${id}" min="0" step="0.01" placeholder="0.00" value="${item.rate_per_m || ''}" oninput="calcInstRow(${id})" /></td>
    <td><input class="input" type="number" id="inst-pcs-${id}" min="0" step="1" placeholder="0" value="${item.no_of_pcs || ''}" oninput="calcInstRow(${id})" /></td>
    <td><input class="input" type="number" id="inst-stitch-${id}" min="0" step="0.01" placeholder="—" value="${item.stitching_per_unit || ''}" oninput="calcInstRow(${id})" /></td>
    <td class="inst-total-cell" id="inst-total-${id}">₹${Number(item.total || 0).toFixed(2)}</td>
    <td><button class="inst-del-btn" onclick="removeInstItem(${id})" title="Remove">✕</button></td>
  `;
  tbody.appendChild(tr);

  if (item.cloth_type) {
    try {
      const res  = await fetch(`/api/companies?clothType=${encodeURIComponent(item.cloth_type)}`);
      const data = await res.json();
      const compSel = document.getElementById(`inst-company-${id}`);
      data.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.company_name;
        opt.textContent = c.company_name;
        if (c.company_name === item.company_name) opt.selected = true;
        compSel.appendChild(opt);
      });
    } catch (e) { /* ignore */ }
  }
}

// ---- Save ----
async function saveInstBill() {
  const data = collectInstData();
  if (!validateInstData(data)) return;

  const btn = document.getElementById('inst-save-btn');
  btn.disabled = true;
  btn.textContent = 'Saving…';

  const isEdit  = !!window.INST_BILL_ID;
  const url     = isEdit ? `/api/institution-bills/${window.INST_BILL_ID}` : '/api/institution-bills';
  const method  = isEdit ? 'PUT' : 'POST';

  try {
    const res    = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const result = await res.json();
    if (!res.ok) {
      document.getElementById('inst-save-error').textContent = result.error || 'Failed to save.';
      btn.disabled = false; btn.textContent = isEdit ? '✓ Update Institution Bill' : '✓ Save Institution Bill';
      return;
    }
    if (isEdit) {
      window.location.href = `/institution-bills/${window.INST_BILL_ID}`;
    } else {
      onInstSaveSuccess(result);
    }
  } catch (err) {
    document.getElementById('inst-save-error').textContent = 'Network error: ' + err.message;
    btn.disabled = false; btn.textContent = isEdit ? '✓ Update Institution Bill' : '✓ Save Institution Bill';
  }
}

function onInstSaveSuccess(bill) {
  // Populate print area
  document.getElementById('pr-company').textContent     = bill.company_name;
  document.getElementById('pr-contact').textContent     = bill.contact_person_name;
  document.getElementById('pr-mobile').textContent      = bill.contact_person_mobile;
  document.getElementById('pr-bill-number').textContent = bill.bill_number;
  document.getElementById('pr-salesperson').textContent = bill.salesperson_name;
  document.getElementById('pr-date').textContent        = formatPrintDate(bill.bill_date);
  document.getElementById('pr-final-total').textContent = fmt(bill.final_total);
  document.getElementById('pr-advance-paid').textContent = fmt(bill.advance_paid);
  document.getElementById('pr-remaining').textContent   = fmt(bill.remaining);

  const tbody = document.getElementById('pr-items-body');
  tbody.innerHTML = bill.items.map((item, i) => `
    <tr>
      <td>${i + 1}</td>
      <td>${item.cloth_type}</td>
      <td>${item.company_name}</td>
      <td>${item.quality_number || '—'}</td>
      <td class="tr">${Number(item.quantity_per_pc).toFixed(2)}</td>
      <td class="tr">${fmt(item.rate_per_m)}</td>
      <td class="tr">${item.no_of_pcs}</td>
      <td class="tr">${fmt(item.total)}</td>
    </tr>
  `).join('');

  const payBody = document.getElementById('pr-payments-body');
  if (bill.payments && bill.payments.length) {
    payBody.innerHTML = bill.payments.map(p =>
      `<div class="inst-inv-pay-row"><span>${p.payment_method}:</span><strong>${fmt(p.amount)}</strong></div>`
    ).join('');
  } else {
    document.getElementById('pr-payments-wrap').style.display = 'none';
  }

  // Show success bar, hide form
  const successBar = document.getElementById('inst-success-bar');
  document.getElementById('inst-success-bill-num').textContent = bill.bill_number;
  successBar.style.display = 'block';

  const invoiceBtn  = document.getElementById('inst-invoice-btn');
  if (invoiceBtn)  invoiceBtn.onclick  = function () { buildPerformaWindow(bill, bill.items, bill.payments, 'invoice'); };

  const perfornaBtn = document.getElementById('inst-performa-btn');
  if (perfornaBtn) perfornaBtn.onclick = function () { buildPerformaWindow(bill, bill.items, bill.payments, 'proforma'); };

  document.getElementById('inst-save-btn').style.display = 'none';
  document.getElementById('inst-save-error').textContent = '';
}

function formatPrintDate(dateStr) {
  if (!dateStr) return '';
  // Parse as local midnight (append T00:00:00) so a YYYY-MM-DD bill date is not
  // pulled back a day for operators west of UTC (e.g. the USA), where a bare
  // new Date('YYYY-MM-DD') would be treated as UTC midnight.
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

function resetInstForm() {
  // Reset form fields
  ['inst-company-name','inst-company-address','inst-contact-person','inst-mobile'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  const salSel = document.getElementById('inst-salesperson');
  salSel.value = instSalespersons.some(s => s.name === 'Self') ? 'Self' : '';
  document.getElementById('inst-bill-date').value = istToday();
  document.getElementById('inst-advance-paid').value = '';
  document.getElementById('inst-payment-amount').value = '';

  // Reset items
  instActiveIds.forEach(id => document.getElementById(`inst-row-${id}`)?.remove());
  instActiveIds = [];
  instDataStore = {};
  instComboLastChanged = null;
  instAdvanceModified = false;

  // Reset combo
  INST_COMBO_METHODS.forEach(m => {
    const chk = document.getElementById(`inst-combo-chk-${m}`);
    const amt = document.getElementById(`inst-combo-amt-${m}`);
    if (chk) chk.checked = false;
    if (amt) { amt.disabled = true; amt.value = ''; }
  });

  // Reset payment mode to Cash
  instCurrentMode = 'Cash';
  document.querySelectorAll('.inst-payment-tab').forEach(b => b.classList.remove('active'));
  document.querySelector('.inst-payment-tab[data-mode="Cash"]').classList.add('active');
  onInstModeChange('Cash');

  // Reset print area
  document.getElementById('inst-print-area').style.display = 'none';
  document.getElementById('inst-success-bar').style.display = 'none';
  document.getElementById('inst-save-btn').style.display = '';
  document.getElementById('inst-save-btn').disabled = false;
  document.getElementById('inst-save-btn').textContent = '✓ Save Institution Bill';
  document.getElementById('pr-payments-wrap').style.display = '';

  clearInstErrors();
  addInstItem();
  updateInstSummary();
}
