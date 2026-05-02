/* ============================================================
   bill-payments.js — Payment tabs, combination payment, summary
   Depends on: bill-state.js
   ============================================================ */

// ---- Summary totals — reads from itemDataStore (layout-agnostic) ----
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

// ---- Payment tabs ----
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

// ---- Combination payment ----
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
