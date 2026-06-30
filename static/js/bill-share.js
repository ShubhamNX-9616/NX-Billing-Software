/* ============================================================
   bill-share.js — WhatsApp message and share-link helpers
   Depends on: bill-state.js (fmt)
   ============================================================ */

function formatDate(isoStr) {
  if (!isoStr) return '';
  const [y, m, d] = isoStr.split('-');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${parseInt(d, 10)} ${months[parseInt(m, 10) - 1]} ${y}`;
}

function buildWhatsAppMessage(bill) {
  const shopName    = 'SHUBHAM NX';
  const shopAddress = 'Krishna Chowk, New Sangvi, Pune - 411061';
  const shopPhone   = '+91 9284630254';

  const dateStr = bill.bill_date
    ? formatDate(bill.bill_date)
    : new Date().toLocaleDateString('en-IN');

  const total     = fmt(bill.final_total);
  const advance   = bill.advance_paid > 0 ? fmt(bill.advance_paid) : null;
  const remaining = bill.remaining > 0    ? fmt(bill.remaining)    : null;
  const shareLink = buildShareLink(bill.bill_number);

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

  const paymentBtn = document.getElementById('update-payment-btn');
  if (paymentBtn) {
    paymentBtn.style.display = '';
    paymentBtn.dataset.billId     = bill.id;
    paymentBtn.dataset.billNumber = bill.bill_number;
    paymentBtn.dataset.finalTotal = bill.final_total;
    paymentBtn.dataset.advancePaid = bill.advance_paid || 0;
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

function openInlinePaymentUpdateModal() {
  const btn = document.getElementById('update-payment-btn');
  if (!btn) return;
  const billNum = btn.dataset.billNumber || '';
  document.getElementById('inline-payment-bill-num').textContent = billNum;
  document.getElementById('inline-payment-error').textContent = '';
  document.getElementById('inline-payment-mode').value = '';
  document.getElementById('inline-payment-single-wrap').style.display = 'none';
  document.getElementById('inline-payment-combo-wrap').style.display = 'none';
  ['cash', 'card', 'upi'].forEach(m => {
    const chk = document.getElementById(`inline-combo-${m}`);
    const amt = document.getElementById(`inline-combo-amt-${m}`);
    if (chk) chk.checked = false;
    if (amt) { amt.disabled = true; amt.value = ''; }
  });
  document.getElementById('inline-payment-modal').classList.remove('hidden');
}

function closeInlinePaymentUpdateModal() {
  document.getElementById('inline-payment-modal').classList.add('hidden');
}

function _inlinePaymentTotal() {
  const btn = document.getElementById('update-payment-btn');
  const advance = Number(btn?.dataset.advancePaid || 0);
  const final   = Number(btn?.dataset.finalTotal  || 0);
  return advance > 0 ? advance : final;
}

function syncInlinePaymentMode() {
  const total = _inlinePaymentTotal();
  const mode = document.getElementById('inline-payment-mode').value;
  const singleWrap = document.getElementById('inline-payment-single-wrap');
  const comboWrap = document.getElementById('inline-payment-combo-wrap');
  document.getElementById('inline-payment-error').textContent = '';
  singleWrap.style.display = 'none';
  comboWrap.style.display = 'none';
  if (!mode) return;
  if (mode === 'Combination') {
    comboWrap.style.display = 'grid';
    syncInlineCombo();
  } else {
    singleWrap.style.display = 'block';
    document.getElementById('inline-payment-single-amount').value = total.toFixed(2);
  }
}

function syncInlineCombo() {
  const total = _inlinePaymentTotal();
  const methods = ['Cash', 'Card', 'UPI'];
  const checked = methods.filter(m => document.getElementById(`inline-combo-${m.toLowerCase()}`).checked);
  methods.forEach(m => {
    const chk = document.getElementById(`inline-combo-${m.toLowerCase()}`);
    const amt = document.getElementById(`inline-combo-amt-${m.toLowerCase()}`);
    if (amt) {
      amt.disabled = !chk.checked;
      if (!chk.checked) amt.value = '';
    }
  });
  const status = document.getElementById('inline-combo-status');
  if (!status) return;
  if (checked.length < 2) {
    status.textContent = 'Select at least 2 methods.';
    return;
  }
  const sum = checked.reduce((acc, m) => acc + (parseFloat(document.getElementById(`inline-combo-amt-${m.toLowerCase()}`).value) || 0), 0);
  status.textContent = Math.abs(sum - total) <= 0.01 ? 'Payment balanced ✓' : `Remaining: ${fmt(total - sum)}`;
}

async function saveInlinePayment() {
  const btn = document.getElementById('btn-inline-payment-save');
  const err = document.getElementById('inline-payment-error');
  const billBtn = document.getElementById('update-payment-btn');
  const billId = billBtn?.dataset.billId;
  const total  = _inlinePaymentTotal();
  const mode = document.getElementById('inline-payment-mode').value;
  err.textContent = '';

  if (!billId) {
    err.textContent = 'Missing bill id.';
    return;
  }
  if (!mode) {
    err.textContent = 'Select a payment mode.';
    return;
  }

  let payments = [];
  if (mode === 'Combination') {
    ['Cash', 'Card', 'UPI'].forEach(m => {
      const chk = document.getElementById(`inline-combo-${m.toLowerCase()}`);
      if (chk && chk.checked) {
        payments.push({
          payment_method: m,
          amount: parseFloat(document.getElementById(`inline-combo-amt-${m.toLowerCase()}`).value) || 0,
        });
      }
    });
  } else {
    payments = [{ payment_method: mode, amount: parseFloat(document.getElementById('inline-payment-single-amount').value) || 0 }];
  }

  if (!payments.length) {
    err.textContent = 'Enter at least one payment amount.';
    return;
  }

  const sum = payments.reduce((acc, p) => acc + Number(p.amount || 0), 0);
  if (Math.abs(sum - total) > 0.01) {
    err.textContent = `Payment sum (${fmt(sum)}) must equal final total (${fmt(total)}).`;
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Saving...';
  try {
    const res = await fetch(`/api/bills/${billId}/payment`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payment_mode_type: mode, payments }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to update payment.');
    closeInlinePaymentUpdateModal();
    window.location.href = `/bills/${billId}`;
  } catch (e) {
    err.textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save Payment';
  }
}
