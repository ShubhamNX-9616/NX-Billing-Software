/* history.js — Bill History page logic */

// ---- Modal state ----
let pendingDeleteId     = null;
let pendingDeleteNumber = null;
let pendingCancelId     = null;
let pendingCancelNumber = null;

function fmt(amount) {
  return Number(amount || 0).toLocaleString('en-IN', {
    style: 'currency', currency: 'INR',
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

function paymentBadge(mode) {
  const map = {
    Cash:        'badge-success',
    Card:        'badge-info',
    UPI:         'badge-warning',
    Combination: 'badge-neutral',
  };
  return `<span class="badge ${map[mode] || 'badge-neutral'}">${mode}</span>`;
}

// ----------------------------------------------------------------
// Render
// ----------------------------------------------------------------
function renderTable(bills, titleText) {
  const loading  = document.getElementById('history-loading');
  const empty    = document.getElementById('history-empty');
  const emptyMsg = document.getElementById('history-empty-msg');
  const wrap     = document.getElementById('history-table-wrap');
  const tbody    = document.getElementById('history-body');
  const title    = document.getElementById('results-title');
  const countEl  = document.getElementById('results-count');

  loading.style.display = 'none';
  title.textContent = titleText || 'All Bills';
  countEl.textContent = bills.length ? `${bills.length} bill${bills.length !== 1 ? 's' : ''}` : '';

  if (!bills.length) {
    empty.style.display = 'block';
    wrap.style.display  = 'none';
    emptyMsg.textContent = titleText === 'Search Results'
      ? 'No bills match your search.'
      : 'No bills yet. Create your first bill!';
    return;
  }

  empty.style.display = 'none';
  wrap.style.display  = 'block';

  tbody.innerHTML = bills.map(b => {
    const cancelled  = b.status === 'cancelled';
    const itemCount  = b.item_count !== undefined ? b.item_count : '—';
    const remaining  = b.remaining || 0;

    const paymentBadgeHtml = cancelled
      ? `<span class="badge" style="background:#fee2e2;color:#9b1c1c;font-size:10px;font-weight:700;letter-spacing:.4px;">CANCELLED</span>`
      : (remaining > 0
          ? `<span class="badge" style="background:#fee2e2;color:#b91c1c;font-size:10px;">Due: ${fmt(remaining)}</span>`
          : `<span class="badge badge-success" style="font-size:10px;">Paid</span>`);

    const rowStyle = cancelled
      ? 'background:#fafafa;opacity:.72;'
      : '';

    const billNumHtml = cancelled
      ? `<span class="fw-600" style="color:var(--text-muted);text-decoration:line-through;">${b.bill_number}</span>`
      : `<span class="fw-600" style="color:var(--primary);">${b.bill_number}</span>`;

    const amountHtml = cancelled
      ? `<span class="fw-600" style="color:var(--text-muted);text-decoration:line-through;">${fmt(b.final_total)}</span>`
      : `<span class="fw-600">${fmt(b.final_total)}</span>`;

    const moreItems = cancelled
      ? `
          <a href="/bills/${b.id}?print=1" class="row-menu-item" target="_blank"
             onclick="event.stopPropagation()">&#128438; Print</a>
          <button class="row-menu-item" onclick="copyBillShareLink('${b.bill_number}'); closeRowMenu('menu-${b.id}'); event.stopPropagation();">
            &#128279; Copy Link
          </button>
          <div class="row-menu-divider"></div>
          <button class="row-menu-item" onclick="restoreBill(${b.id}, '${b.bill_number}'); closeRowMenu('menu-${b.id}'); event.stopPropagation();">
            &#10227; Restore Bill
          </button>
          <button class="row-menu-item row-menu-danger" onclick="deleteBill(${b.id}, '${b.bill_number}'); closeRowMenu('menu-${b.id}'); event.stopPropagation();">
            &#128465; Delete
          </button>`
      : `
          <a href="/bills/${b.id}?print=1" class="row-menu-item" target="_blank"
             onclick="event.stopPropagation()">&#128438; Print</a>
          <button class="row-menu-item" onclick="copyBillShareLink('${b.bill_number}'); closeRowMenu('menu-${b.id}'); event.stopPropagation();">
            &#128279; Copy Link
          </button>
          <div class="row-menu-divider"></div>
          <button class="row-menu-item row-menu-warn" onclick="cancelBill(${b.id}, '${b.bill_number}'); closeRowMenu('menu-${b.id}'); event.stopPropagation();">
            &#10006; Cancel Bill
          </button>
          <button class="row-menu-item row-menu-danger" onclick="deleteBill(${b.id}, '${b.bill_number}'); closeRowMenu('menu-${b.id}'); event.stopPropagation();">
            &#128465; Delete
          </button>`;

    const primaryBtns = cancelled
      ? `<a href="/bills/${b.id}" class="btn btn-secondary btn-sm">View</a>`
      : `<a href="/bills/${b.id}" class="btn btn-secondary btn-sm">View</a>
         <a href="/edit-bill/${b.id}" class="btn btn-secondary btn-sm"
            onclick="event.stopPropagation()">Edit</a>`;

    const actionBtns = `
      ${primaryBtns}
      <div class="row-menu-wrap" onclick="event.stopPropagation()">
        <button class="btn btn-secondary btn-sm row-menu-trigger"
                onclick="toggleRowMenu('menu-${b.id}')">&#8943;</button>
        <div class="row-menu" id="menu-${b.id}">
          ${moreItems}
        </div>
      </div>`;

    return `
      <tr onclick="location.href='/bills/${b.id}'" style="cursor:pointer;${rowStyle}">
        <td>${billNumHtml}</td>
        <td style="${cancelled ? 'color:var(--text-muted);' : ''}">${b.customer_name_snapshot || '—'}</td>
        <td class="col-mobile" style="color:var(--text-muted);">${b.customer_mobile_snapshot || '—'}</td>
        <td class="col-date" style="${cancelled ? 'color:var(--text-muted);' : ''}">${b.bill_date || '—'}</td>
        <td class="col-items text-right" style="${cancelled ? 'color:var(--text-muted);' : ''}">${itemCount}</td>
        <td class="text-right">
          ${amountHtml}
          <span style="display:block;margin-top:2px;">${paymentBadgeHtml}</span>
        </td>
        <td class="col-payment">${paymentBadge(b.payment_mode_type)}</td>
        <td style="text-align:center;">
          <div style="display:flex;gap:6px;justify-content:center;flex-wrap:wrap;" onclick="event.stopPropagation()">
            ${actionBtns}
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// ----------------------------------------------------------------
// Load all bills on page load
// ----------------------------------------------------------------
async function loadAllBills() {
  try {
    const res   = await fetch('/api/bills');
    if (!res.ok) throw new Error('API error');
    const bills = await res.json();
    renderTable(bills, 'All Bills');
  } catch (err) {
    document.getElementById('history-loading').innerHTML =
      `<span class="text-danger">Failed to load bills: ${err.message}</span>`;
  }
}

// ----------------------------------------------------------------
// Search
// ----------------------------------------------------------------
async function doSearch() {
  const billNumber = document.getElementById('search-bill-number').value.trim();
  const name       = document.getElementById('search-name').value.trim();
  const mobile     = document.getElementById('search-mobile').value.trim();

  if (!billNumber && !name && !mobile) {
    showLoading();
    await loadAllBills();
    return;
  }

  showLoading();

  const params = new URLSearchParams();
  if (billNumber) params.set('billNumber', billNumber);
  if (name)       params.set('name', name);
  if (mobile)     params.set('mobile', mobile);

  try {
    const res   = await fetch(`/api/bills/search?${params.toString()}`);
    if (!res.ok) throw new Error('API error');
    const bills = await res.json();
    renderTable(bills, 'Search Results');
  } catch (err) {
    document.getElementById('history-loading').style.display = 'none';
    document.getElementById('history-empty').style.display   = 'block';
    document.getElementById('history-empty-msg').textContent =
      'Search failed: ' + err.message;
  }
}

function clearSearch() {
  document.getElementById('search-bill-number').value = '';
  document.getElementById('search-name').value        = '';
  document.getElementById('search-mobile').value      = '';
  showLoading();
  loadAllBills();
}

function showLoading() {
  document.getElementById('history-loading').style.display    = 'flex';
  document.getElementById('history-empty').style.display      = 'none';
  document.getElementById('history-table-wrap').style.display = 'none';
  document.getElementById('results-count').textContent        = '';
}

// ---- Live debounced search + Enter key on all three search fields
function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

const debouncedSearch = debounce(doSearch, 400);

['search-bill-number', 'search-name', 'search-mobile'].forEach(id => {
  const el = document.getElementById(id);
  el.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
  el.addEventListener('input', debouncedSearch);
});

// ---- Init
document.addEventListener('DOMContentLoaded', loadAllBills);

// ----------------------------------------------------------------
// Row "⋯" dropdown menu helpers
// ----------------------------------------------------------------
function toggleRowMenu(menuId) {
  const menu = document.getElementById(menuId);
  if (!menu) return;
  const isOpen = menu.classList.contains('open');
  // close all open menus first
  document.querySelectorAll('.row-menu.open').forEach(m => m.classList.remove('open'));
  if (!isOpen) menu.classList.add('open');
}

function closeRowMenu(menuId) {
  const menu = document.getElementById(menuId);
  if (menu) menu.classList.remove('open');
}

// Close any open row menu when clicking elsewhere
document.addEventListener('click', () => {
  document.querySelectorAll('.row-menu.open').forEach(m => m.classList.remove('open'));
});

// ----------------------------------------------------------------
// Cancel bill
// ----------------------------------------------------------------
function cancelBill(billId, billNumber) {
  pendingCancelId     = billId;
  pendingCancelNumber = billNumber;
  document.getElementById('cancel-modal-bill-num').textContent = billNumber;
  document.getElementById('cancel-modal-error').textContent    = '';
  document.getElementById('btn-confirm-cancel').disabled    = false;
  document.getElementById('btn-confirm-cancel').textContent = 'Yes, Cancel Bill';
  document.getElementById('cancel-modal').classList.remove('hidden');
}

function closeCancelModal() {
  document.getElementById('cancel-modal').classList.add('hidden');
  pendingCancelId     = null;
  pendingCancelNumber = null;
}

async function confirmCancel() {
  if (!pendingCancelId) return;
  const btn = document.getElementById('btn-confirm-cancel');
  btn.disabled    = true;
  btn.textContent = 'Cancelling…';
  document.getElementById('cancel-modal-error').textContent = '';
  try {
    const res  = await fetch(`/api/bills/${pendingCancelId}/cancel`, { method: 'PUT' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Cancel failed.');
    closeCancelModal();
    showToast('Bill cancelled successfully.');
    setTimeout(() => { showLoading(); loadAllBills(); }, 800);
  } catch (err) {
    document.getElementById('cancel-modal-error').textContent = err.message;
    btn.disabled    = false;
    btn.textContent = 'Yes, Cancel Bill';
  }
}

document.getElementById('cancel-modal').addEventListener('click', function (e) {
  if (e.target === this) closeCancelModal();
});

// ----------------------------------------------------------------
// Restore bill
// ----------------------------------------------------------------
async function restoreBill(billId, billNumber) {
  if (!confirm(`Restore bill ${billNumber}? It will become active again.`)) return;
  try {
    const res  = await fetch(`/api/bills/${billId}/restore`, { method: 'PUT' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Restore failed.');
    showToast('Bill restored successfully.');
    setTimeout(() => { showLoading(); loadAllBills(); }, 800);
  } catch (err) {
    showToast('Error: ' + err.message, true);
  }
}

// ----------------------------------------------------------------
// Delete bill — confirmation modal + API call
// ----------------------------------------------------------------
function deleteBill(billId, billNumber) {
  document.getElementById('delete-modal-bill-num').textContent    = billNumber;
  document.getElementById('delete-modal-warning-num').textContent = billNumber;
  document.getElementById('delete-modal-error').textContent       = '';
  document.getElementById('btn-confirm-delete').disabled    = false;
  document.getElementById('btn-confirm-delete').textContent = 'Yes, Delete and Renumber';
  pendingDeleteId     = billId;
  pendingDeleteNumber = billNumber;
  document.getElementById('delete-modal').classList.remove('hidden');
}

function closeDeleteModal() {
  document.getElementById('delete-modal').classList.add('hidden');
  pendingDeleteId     = null;
  pendingDeleteNumber = null;
}

async function confirmDelete() {
  if (!pendingDeleteId) return;

  const btn = document.getElementById('btn-confirm-delete');
  btn.disabled    = true;
  btn.textContent = 'Deleting…';
  document.getElementById('delete-modal-error').textContent = '';

  try {
    const res  = await fetch(`/api/bills/${pendingDeleteId}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Delete failed.');
    closeDeleteModal();
    showToast('Bill deleted. Remaining bills have been renumbered.');
    setTimeout(() => { showLoading(); loadAllBills(); }, 1000);
  } catch (err) {
    document.getElementById('delete-modal-error').textContent = err.message;
    btn.disabled    = false;
    btn.textContent = 'Yes, Delete and Renumber';
  }
}

document.getElementById('delete-modal').addEventListener('click', function (e) {
  if (e.target === this) closeDeleteModal();
});

// ----------------------------------------------------------------
// Toast
// ----------------------------------------------------------------
function showToast(msg, isError) {
  let el = document.getElementById('__history-toast__');
  if (!el) {
    el = document.createElement('div');
    el.id = '__history-toast__';
    el.style.cssText = 'position:fixed;top:16px;right:16px;z-index:9999;min-width:300px;' +
                       'max-width:420px;box-shadow:0 4px 16px rgba(0,0,0,.15);padding:12px 16px;' +
                       'border-radius:8px;font-size:14px;display:flex;align-items:center;';
    document.body.appendChild(el);
  }
  el.style.background = isError ? '#fee2e2' : '#d1fae5';
  el.style.color      = isError ? '#9b1c1c' : '#065f46';
  el.textContent      = msg;
  el.style.display    = 'flex';
  el.style.opacity    = '1';
  clearTimeout(el._timer);
  el._timer = setTimeout(() => {
    el.style.transition = 'opacity .4s';
    el.style.opacity    = '0';
    setTimeout(() => { el.style.display = 'none'; el.style.transition = ''; }, 400);
  }, 2800);
}

// legacy alias used by share helpers
function showDeleteToast(msg) { showToast(msg); }

// ----------------------------------------------------------------
// Share link helpers
// ----------------------------------------------------------------
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

function copyBillShareLink(billNumber) {
  const link = window.location.origin + '/bill/share/' + billNumber;
  copyToClipboard(link);
  showToast('Share link copied for ' + billNumber);
}
