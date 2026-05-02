/* ============================================================
   bill-form.js — Form init, validation, save, and mobile search
   Depends on: all other bill-*.js modules
   ============================================================ */

// ---- Validation helpers ----
function setError(elId, msg) {
  const el = document.getElementById(elId);
  if (el) el.textContent = msg;
}

function clearErrors() {
  ['mobile-error','name-error','salesperson-error','items-error','payment-error','save-error','advance-error','roundoff-error'].forEach(id => setError(id, ''));
}

// ---- Load next bill number ----
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

// ---- Mobile search ----
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

// ---- Collect bill data ----
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

// ---- Client-side validation ----
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

// ---- Edit mode: pre-fill all fields from existing bill ----
async function prefillEditForm() {
  try {
    const res = await fetch(`/api/bills/${BILL_ID}`);
    if (!res.ok) throw new Error('Failed to load bill for editing.');
    const bill = await res.json();

    document.getElementById('bill-number').value = bill.bill_number;
    document.getElementById('bill-date').value   = bill.bill_date;
    renderSalespersonOptions(bill.salesperson_name || 'Self');

    const bnEl = document.getElementById('edit-warning-bill-num');
    if (bnEl) bnEl.textContent = bill.bill_number;

    document.getElementById('customer-mobile').value = bill.customer_mobile_snapshot;
    document.getElementById('customer-name').value   = bill.customer_name_snapshot;
    const statusEl = document.getElementById('customer-status');
    if (statusEl) statusEl.innerHTML = '<span class="badge badge-success">Existing Customer</span>';

    for (const item of bill.items) {
      addItemRow();
      const id = activeItemIds[activeItemIds.length - 1];
      await setItemRowValues(id, item);
    }

    setPaymentMode(bill.payment_mode_type, bill.payments || []);

    const roEl = document.getElementById('sum-roundoff');
    if (roEl) roEl.value = (bill.round_off || 0) > 0 ? Number(bill.round_off).toFixed(2) : '';

    const advEl = document.getElementById('advance-paid');
    if (advEl) advEl.value = (bill.advance_paid || 0).toFixed(2);
    advancePaidUserModified = true;

    const saveBtn = document.getElementById('btn-save');
    if (saveBtn) saveBtn.textContent = '✓ Update Bill';

    updateSummary();
  } catch (err) {
    document.getElementById('save-error').textContent = 'Failed to load bill data: ' + err.message;
  }
}

async function setItemRowValues(id, item) {
  const qtyEl     = document.getElementById(`qty-${id}`);
  const mrpEl     = document.getElementById(`mrp-${id}`);
  const discEl    = document.getElementById(`disc-${id}`);
  const discAmtEl = document.getElementById(`discamt-${id}`);
  const qualEl    = document.getElementById(`quality-${id}`);
  if (qtyEl)  qtyEl.value  = item.quantity;
  if (mrpEl)  mrpEl.value  = item.mrp;
  // Restore discount as flat ₹ to avoid lossy percentage round-trip
  const discPerUnit = round2((item.mrp || 0) - (item.rate_after_disc || 0));
  if (discEl)    discEl.value    = '';
  if (discAmtEl) discAmtEl.value = discPerUnit > 0 ? discPerUnit : '';
  if (qualEl)    qualEl.value    = item.quality_number || '';
  if (item.inventory_item_id) {
    itemDataStore[id].inventoryItemId = item.inventory_item_id;
    showInventoryBadge(id, true);
  }
  await onClothChangeRestoring(id, item.cloth_type, item.company_name || '');
}

function setPaymentMode(mode, payments) {
  currentMode = mode;
  document.querySelectorAll('.payment-mode-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
  onPaymentModeChange(mode);

  if (mode === 'Combination') {
    ['Cash', 'Card', 'UPI'].forEach(m => {
      const chk = document.getElementById(`combo-chk-${m}`);
      const amt = document.getElementById(`combo-amt-${m}`);
      if (chk) chk.checked = false;
      if (amt) { amt.disabled = true; amt.value = ''; }
    });
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

// ---- Save bill ----
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
      saveBtn.textContent = EDIT_MODE ? '✓ Update Bill' : '✓ Save Bill';
      return;
    }

    billSaved = true;  // disable beforeunload guard

    if (EDIT_MODE) {
      const successEl         = document.getElementById('save-success');
      successEl.style.display = 'inline';
      successEl.textContent   = 'Bill updated successfully!';
      saveBtn.textContent     = '✓ Updated';
      setTimeout(() => { window.location.href = `/bills/${BILL_ID}`; }, 1500);
    } else {
      savedBillId = result.id;
      const successEl         = document.getElementById('save-success');
      successEl.style.display = 'inline';
      successEl.textContent   = `Bill ${result.bill_number} saved successfully!`;
      document.getElementById('btn-print').disabled = false;
      saveBtn.textContent = '✓ Saved';
      showPostSaveActions(result);
    }

  } catch (err) {
    document.getElementById('save-error').textContent = 'Network error: ' + err.message;
    saveBtn.disabled    = false;
    saveBtn.textContent = EDIT_MODE ? '✓ Update Bill' : '✓ Save Bill';
  }
}

// ---- Print / PDF ----
function doPrint() {
  if (savedBillId) window.location.href = `/bills/${savedBillId}`;
}

// ---- Page init ----
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
