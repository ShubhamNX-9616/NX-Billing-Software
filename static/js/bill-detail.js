/* ============================================================
   bill-detail.js — Bill Detail page logic
   Moved out of bill_detail.html so it is a cacheable static file (and so the pages can
   adopt a strict Content-Security-Policy later). The bill id comes from the page:
   <div id="bill-detail-root" data-bill-id="...">.
   ============================================================ */

const BILL_ID = parseInt(document.getElementById('bill-detail-root').dataset.billId, 10);
  let CURRENT_BILL = null;
  let DETAIL_PAYMENT_MODE = '';

  /* ---- Formatters ---- */
  function fmt(amount) {
    return Number(amount || 0).toLocaleString('en-IN', {
      style: 'currency', currency: 'INR',
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    });
  }

  function fmtDate(iso) {
    if (!iso) return '—';
    const [y, m, d] = iso.split('-');
    return `${d}/${m}/${y}`;
  }

  function fmtTime(createdAt) {
    if (!createdAt) return '';
    const parts = createdAt.split(' ');
    if (parts.length < 2) return '';
    const [h, min] = parts[1].split(':');
    const hour = parseInt(h, 10);
    const ampm = hour >= 12 ? 'PM' : 'AM';
    const h12 = hour % 12 || 12;
    return `${h12}:${min} ${ampm}`;
  }

  function paymentBadgeHTML(mode) {
      const map = { Cash:'badge-success', Card:'badge-info', UPI:'badge-warning', Combination:'badge-neutral', Pending:'badge-secondary' };
      return `<span class="badge ${map[mode] || 'badge-neutral'}">${mode}</span>`;
    }

  /* ---- WhatsApp / share helpers ---- */
  function formatDateLong(isoStr) {
    if (!isoStr) return '';
    const [y, m, d] = isoStr.split('-');
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return `${parseInt(d, 10)} ${months[parseInt(m, 10) - 1]} ${y}`;
  }

  function buildWhatsAppMessageFromBill(bill) {
    const shopName    = 'SHUBHAM NX';
    const shopAddress = 'Krishna Chowk, New Sangvi, Pune - 411061';
    const shopPhone   = '+91 9284630254';

    const dateStr   = formatDateLong(bill.bill_date);
    const total     = fmt(bill.final_total);
    const advance   = bill.advance_paid > 0 && Math.abs(bill.advance_paid - bill.final_total) >= 0.005 ? fmt(bill.advance_paid) : null;
    const remaining = bill.remaining     > 0 ? fmt(bill.remaining)   : null;
    const shareLink = (window.SHARE_BASE_URL || window.location.origin) + '/bill/share/' + bill.bill_number;

    let amountLine = 'Amount: ' + total;
    if (advance)   amountLine += '  |  Advance: ' + advance;
    if (remaining) amountLine += '  |  Balance: ' + remaining + ' (pending)';

    const lines = [];
    lines.push('Dear ' + (bill.customer_name_snapshot || 'Customer') + ',');
    lines.push('');
    lines.push('Thank you for shopping at *' + shopName + '*! 🙏');
    lines.push('');
    lines.push('Bill No: ' + bill.bill_number + '  |  ' + dateStr);
    lines.push(amountLine);
    lines.push('');
    lines.push('📄 Bill: ' + shareLink);
    lines.push('⭐ Review: https://maps.app.goo.gl/YjTCZZNLWwbjWZDH8');
    lines.push('📸 Follow: https://www.instagram.com/shubham_nx_2016/');
    lines.push('');
    lines.push('📍 ' + shopAddress + '  |  📞 ' + shopPhone);
    lines.push('');
    lines.push('See you again soon!');
    return lines.join('\n');
  }

  function buildWhatsAppURL(mobile, message) {
    let m = String(mobile || '').replace(/\D/g, '');
    if (m.length === 10)                           m = '91' + m;
    else if (m.length === 11 && m.startsWith('0')) m = '91' + m.slice(1);
    return 'https://wa.me/' + m + '?text=' + encodeURIComponent(message);
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

  function normalizeWhatsAppNumber(raw) {
    let digits = String(raw || '').replace(/\D/g, '');
    if (!digits) return '';
    if (digits.length === 10) return `91${digits}`;
    if (digits.startsWith('91') && digits.length === 12) return digits;
    return digits;
  }

  function openWhatsAppForBill() {
    if (!CURRENT_BILL) return;
    const mobile = normalizeWhatsAppNumber(CURRENT_BILL.customer_mobile_snapshot);
    if (!mobile) {
      alert('Customer mobile number is not available for WhatsApp.');
      return;
    }
    const text = buildWhatsAppMessageFromBill(CURRENT_BILL);
    window.open('https://wa.me/' + mobile + '?text=' + encodeURIComponent(text), '_blank');
  }

  /* ---- Render ---- */
  function renderBill(bill) {
    CURRENT_BILL = bill;
    const grossFinalTotal = Number(
      bill.gross_final_total
      || bill.items.reduce((sum, item) => sum + Number(item.final_amount || 0), 0)
    );
    const roundOff = bill.round_off != null && bill.round_off !== 0
      ? Number(bill.round_off)
      : (grossFinalTotal - Number(bill.final_total || 0));

    // Show/hide cancelled banner + swap Cancel/Restore buttons
    const cancelled = bill.status === 'cancelled';
    document.getElementById('cancelled-banner').style.display = cancelled ? 'block' : 'none';
    document.getElementById('action-cancel-btn').style.display  = cancelled ? 'none' : '';
    document.getElementById('action-restore-btn').style.display = cancelled ? '' : 'none';

    // Screen bar
    document.getElementById('screen-bill-number').textContent = bill.bill_number;
    document.getElementById('screen-payment-badge').innerHTML = paymentBadgeHTML(bill.payment_mode_type);
    // Header fields
    document.getElementById('inv-bill-number').textContent    = bill.bill_number;
    const timeStr = fmtTime(bill.created_at);
    document.getElementById('inv-bill-date').textContent = fmtDate(bill.bill_date) + (timeStr ? ', ' + timeStr : '');
    document.getElementById('inv-customer-name').textContent  = bill.customer_name_snapshot;
    document.getElementById('inv-customer-mobile').textContent = bill.customer_mobile_snapshot;

    // Items table
    const tbody = document.getElementById('inv-items-body');
    tbody.innerHTML = bill.items.map((item, i) => {
      const desc = `${item.cloth_type} &mdash; ${item.company_name}`;
      const qualityParts = [];
      if (item.quality_number) qualityParts.push(`Quality: ${item.quality_number}`);
      if (item.item_code) qualityParts.push(item.item_code);
      const quality = qualityParts.length
        ? `<br><span class="text-muted" style="font-size:11px;">${qualityParts.join(' &nbsp;|&nbsp; ')}</span>`
        : '';
      const discDisplay = item.discount_percent > 0
        ? `${Number(item.discount_percent).toFixed(1)}%`
        : '—';
      const rowClass = i % 2 === 1 ? 'inv-row-alt' : '';
      return `
        <tr class="${rowClass}">
          <td class="inv-td inv-td-num">${i + 1}</td>
          <td class="inv-td">${desc}${quality}</td>
          <td class="inv-td inv-td-right">${Number(item.quantity).toLocaleString('en-IN')}</td>
          <td class="inv-td inv-td-right">${fmt(item.mrp)}</td>
          <td class="inv-td inv-td-center-muted">${discDisplay}</td>
          <td class="inv-td inv-td-right-muted">${item.rate_after_disc > 0 ? fmt(item.rate_after_disc) : '—'}</td>
          <td class="inv-td inv-td-amount">${fmt(item.final_amount)}</td>
        </tr>
      `;
    }).join('');

    // Piece counts: a Shirting / Suiting line is one shirt / pant whatever its
    // metres; every other type counts by quantity.
    let shirts = 0, pants = 0, others = 0;
    bill.items.forEach(item => {
      if (item.cloth_type === 'Shirting') shirts += 1;
      else if (item.cloth_type === 'Suiting') pants += 1;
      else others += Number(item.quantity) || 0;
    });
    document.getElementById('inv-count-shirts').textContent = shirts;
    document.getElementById('inv-count-pants').textContent  = pants;
    document.getElementById('inv-count-others').textContent = others.toLocaleString('en-IN');

    // Totals
    const subtotal = Number(bill.subtotal || 0);
    const subtotalRow = document.getElementById('inv-subtotal-row');
    if (subtotal > grossFinalTotal) {
      document.getElementById('inv-subtotal').textContent = fmt(subtotal);
      subtotalRow.style.display = 'flex';
    } else {
      subtotalRow.style.display = 'none';
    }
    document.getElementById('inv-final').textContent        = fmt(grossFinalTotal);
    document.getElementById('inv-roundoff').textContent     =
      roundOff > 0 ? `−${fmt(roundOff)}` : roundOff < 0 ? `+${fmt(-roundOff)}` : '—';
    document.getElementById('inv-finalpayable').textContent = fmt(Number(bill.final_total || 0));
    document.getElementById('inv-savings').textContent      = fmt(bill.total_savings);

    const advancePaid = bill.advance_paid || 0;
    const remaining   = bill.remaining   || 0;
    const advRow = document.getElementById('inv-advance-row');
    document.getElementById('inv-advance').textContent = fmt(advancePaid);
    advRow.style.display = 'flex';

    const remRow = document.getElementById('inv-remaining-row');
    const recBtn = document.getElementById('record-payment-btn');
    if (remaining > 0.005 && bill.status !== 'cancelled') {
      document.getElementById('inv-remaining').textContent = fmt(remaining);
      remRow.style.display = 'flex';
      if (recBtn) recBtn.style.display = '';
    } else {
      remRow.style.display = 'none';
      if (recBtn) recBtn.style.display = 'none';
    }

    // Payments
    const paymentsEl = document.getElementById('inv-payments');
    if (bill.payments && bill.payments.length) {
      paymentsEl.innerHTML = bill.payments.map(p =>
        `<div class="inv-payment-pill"><strong>${p.payment_method}</strong>: ${fmt(p.amount)}${p.paid_at ? `<span style="font-size:11px;color:var(--text-muted);margin-left:5px;">(${p.paid_at})</span>` : ''}</div>`
      ).join('');
    } else {
      paymentsEl.innerHTML = `<span class="text-muted">Payment pending</span>`;
    }

    // Show invoice
    document.getElementById('detail-loading').style.display     = 'none';
    document.getElementById('invoice-print-area').style.display = 'block';

    // Wire up WhatsApp and share buttons (both topbar + action bar pairs)
    const waMsg  = buildWhatsAppMessageFromBill(bill);
    const waURL  = buildWhatsAppURL(bill.customer_mobile_snapshot, waMsg);
    const shareLink = (window.SHARE_BASE_URL || window.location.origin) + '/bill/share/' + bill.bill_number;

    const waEl = document.getElementById('detail-whatsapp-btn');
    if (waEl) waEl.href = waURL;

    function wireShareBtn(btnId, msgId) {
      const btn = document.getElementById(btnId);
      if (!btn) return;
      btn.onclick = function () {
        copyToClipboard(shareLink);
        const msg = document.getElementById(msgId);
        if (msg) {
          msg.style.display = 'inline';
          setTimeout(() => { msg.style.display = 'none'; }, 3000);
        }
      };
    }
    wireShareBtn('detail-share-btn', 'detail-link-copied');

    // Auto-print if ?print=1
    if (new URLSearchParams(window.location.search).get('print') === '1') {
      setTimeout(() => window.print(), 800);
    }
  }

  /* ---- Fetch ---- */
  async function loadBill() {
    try {
      const res = await fetch(`/api/bills/${BILL_ID}`);
      if (res.status === 404) throw new Error('Bill not found.');
      if (!res.ok)            throw new Error('Failed to load bill.');
      const bill = await res.json();
      renderBill(bill);
    } catch (err) {
      document.getElementById('detail-loading').style.display = 'none';
      const errEl = document.getElementById('detail-error');
      errEl.textContent  = err.message;
      errEl.style.display = 'block';
    }
  }

  /* ---- Delete ---- */
  function openDetailDeleteModal() {
    const billNumEl = document.getElementById('screen-bill-number');
    const label     = billNumEl ? billNumEl.textContent : 'this bill';
    document.getElementById('detail-delete-bill-num').textContent = label;
    document.getElementById('detail-delete-error').textContent    = '';
    document.getElementById('btn-detail-confirm-delete').disabled    = false;
    document.getElementById('btn-detail-confirm-delete').textContent = 'Yes, Delete and Renumber';
    document.getElementById('detail-delete-modal').classList.remove('hidden');
  }

  function closeDetailDeleteModal() {
    document.getElementById('detail-delete-modal').classList.add('hidden');
  }

  async function confirmDetailDelete() {
    const btn = document.getElementById('btn-detail-confirm-delete');
    btn.disabled    = true;
    btn.textContent = 'Deleting\u2026';
    document.getElementById('detail-delete-error').textContent = '';

    try {
      const res  = await fetch(`/api/bills/${BILL_ID}`, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Delete failed.');
      // Redirect to history after brief success moment
      window.location.href = '/bill-history';
    } catch (err) {
      document.getElementById('detail-delete-error').textContent = err.message;
      btn.disabled    = false;
      btn.textContent = 'Yes, Delete and Renumber';
    }
  }

  document.getElementById('detail-delete-modal').addEventListener('click', function (e) {
    if (e.target === this) closeDetailDeleteModal();
  });

  /* ---- Cancel ---- */
  function openDetailCancelModal() {
    const label = document.getElementById('screen-bill-number').textContent || 'this bill';
    document.getElementById('detail-cancel-bill-num').textContent = label;
    document.getElementById('detail-cancel-error').textContent    = '';
    document.getElementById('btn-detail-confirm-cancel').disabled    = false;
    document.getElementById('btn-detail-confirm-cancel').textContent = 'Yes, Cancel Bill';
    document.getElementById('detail-cancel-modal').classList.remove('hidden');
  }

  function closeDetailCancelModal() {
    document.getElementById('detail-cancel-modal').classList.add('hidden');
  }

  async function confirmDetailCancel() {
    const btn = document.getElementById('btn-detail-confirm-cancel');
    btn.disabled    = true;
    btn.textContent = 'Cancelling…';
    document.getElementById('detail-cancel-error').textContent = '';
    try {
      const res  = await fetch(`/api/bills/${BILL_ID}/cancel`, { method: 'PUT' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Cancel failed.');
      closeDetailCancelModal();
      await loadBill();
    } catch (err) {
      document.getElementById('detail-cancel-error').textContent = err.message;
      btn.disabled    = false;
      btn.textContent = 'Yes, Cancel Bill';
    }
  }

  document.getElementById('detail-cancel-modal').addEventListener('click', function (e) {
    if (e.target === this) closeDetailCancelModal();
  });

  /* ---- Restore ---- */
  async function confirmDetailRestore() {
    if (!confirm('Restore this bill? It will become active again.')) return;
    try {
      const res  = await fetch(`/api/bills/${BILL_ID}/restore`, { method: 'PUT' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Restore failed.');
      await loadBill();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  }

  document.addEventListener('DOMContentLoaded', loadBill);

  /* ---- Record Payment ---- */
  function openRecordPaymentModal() {
    const remaining = CURRENT_BILL && CURRENT_BILL.remaining ? Number(CURRENT_BILL.remaining) : 0;
    document.getElementById('rp-balance-due').textContent = fmt(remaining);
    document.getElementById('rp-amount').value            = remaining.toFixed(2);
    document.getElementById('rp-error').textContent       = '';
    document.getElementById('rp-confirm-btn').disabled    = false;
    document.getElementById('rp-confirm-btn').textContent = 'Record Payment';
    document.getElementById('rp-date').value = new Date().toLocaleDateString('en-CA');
    document.querySelectorAll('.rp-method-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.rp-method-btn[data-method="Cash"]').classList.add('active');
    document.getElementById('record-payment-modal').classList.remove('hidden');
  }

  function closeRecordPaymentModal() {
    document.getElementById('record-payment-modal').classList.add('hidden');
  }

  function selectRpMethod(btn) {
    document.querySelectorAll('.rp-method-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  }

  async function confirmRecordPayment() {
    const btn    = document.getElementById('rp-confirm-btn');
    const errEl  = document.getElementById('rp-error');
    const amount = parseFloat(document.getElementById('rp-amount').value) || 0;
    const method = (document.querySelector('.rp-method-btn.active') || {}).dataset?.method;

    errEl.textContent = '';
    if (amount <= 0) { errEl.textContent = 'Enter a valid amount.'; return; }

    const paid_date = document.getElementById('rp-date').value;
    btn.disabled    = true;
    btn.textContent = 'Saving…';
    try {
      const res  = await fetch(`/api/bills/${BILL_ID}/record-payment`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ amount, payment_method: method, paid_date }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to record payment.');
      closeRecordPaymentModal();
      await loadBill();
    } catch (err) {
      errEl.textContent   = err.message;
      btn.disabled        = false;
      btn.textContent     = 'Record Payment';
    }
  }

  document.getElementById('record-payment-modal').addEventListener('click', function (e) {
    if (e.target === this) closeRecordPaymentModal();
  });
