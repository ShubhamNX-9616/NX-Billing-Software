/* history.js — Bill History page logic */

// ---- Delete state ----
let pendingDeleteId     = null;
let pendingDeleteNumber = null;

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
    const itemCount = b.item_count !== undefined ? b.item_count : '—';
    const remaining = b.remaining || 0;
    const statusBadge = remaining > 0
      ? `<span class="badge" style="background:#fee2e2;color:#b91c1c;font-size:10px;">Due: ${fmt(remaining)}</span>`
      : `<span class="badge badge-success" style="font-size:10px;">Paid</span>`;
    return `
      <tr onclick="location.href='/bills/${b.id}'" style="cursor:pointer;">
        <td><span class="fw-600" style="color:var(--primary);">${b.bill_number}</span></td>
        <td>${b.customer_name_snapshot || '—'}</td>
        <td class="col-mobile" style="color:var(--text-muted);">${b.customer_mobile_snapshot || '—'}</td>
        <td class="col-date">${b.bill_date || '—'}</td>
        <td class="col-items text-right">${itemCount}</td>
        <td class="text-right">
          <span class="fw-600">${fmt(b.final_total)}</span>
          <span style="display:block;margin-top:2px;">${statusBadge}</span>
        </td>
        <td class="col-payment">${paymentBadge(b.payment_mode_type)}</td>
        <td style="text-align:center;">
          <div style="display:flex;gap:6px;justify-content:center;flex-wrap:wrap;" onclick="event.stopPropagation()">
            <a href="/bills/${b.id}" class="btn btn-secondary btn-sm">View</a>
            <a href="/edit-bill/${b.id}" class="btn btn-secondary btn-sm"
               onclick="event.stopPropagation()">Edit</a>
            <a href="/bills/${b.id}?print=1" class="btn btn-secondary btn-sm"
               target="_blank" onclick="event.stopPropagation()">&#128438; Print</a>
            <button class="btn-share-icon"
                    onclick="copyBillShareLink('${b.bill_number}'); event.stopPropagation();"
                    title="Copy share link">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" stroke-width="2">
                <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/>
                <circle cx="18" cy="19" r="3"/>
                <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
                <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
              </svg>
            </button>
            <button class="btn btn-danger btn-sm"
                    onclick="deleteBill(${b.id}, '${b.bill_number}'); event.stopPropagation();">
              &#128465; Delete
            </button>
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

  // If all empty, reload all
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

// ---- Allow pressing Enter in any search field to trigger search
['search-bill-number', 'search-name', 'search-mobile'].forEach(id => {
  document.getElementById(id).addEventListener('keydown', e => {
    if (e.key === 'Enter') doSearch();
  });
});

// ---- Init
document.addEventListener('DOMContentLoaded', loadAllBills);

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
  btn.textContent = 'Deleting\u2026';
  document.getElementById('delete-modal-error').textContent = '';

  try {
    const res  = await fetch(`/api/bills/${pendingDeleteId}`, { method: 'DELETE' });
    const data = await res.json();

    if (!res.ok) throw new Error(data.error || 'Delete failed.');

    closeDeleteModal();
    showDeleteToast('Bill deleted. Remaining bills have been renumbered.');
    setTimeout(() => { showLoading(); loadAllBills(); }, 1000);

  } catch (err) {
    document.getElementById('delete-modal-error').textContent = err.message;
    btn.disabled    = false;
    btn.textContent = 'Yes, Delete and Renumber';
  }
}

function showDeleteToast(msg) {
  let el = document.getElementById('__delete-toast__');
  if (!el) {
    el = document.createElement('div');
    el.id = '__delete-toast__';
    el.className = 'alert alert-success';
    el.style.cssText = 'position:fixed;top:16px;right:16px;z-index:9999;min-width:300px;' +
                       'max-width:420px;box-shadow:0 4px 16px rgba(0,0,0,.15);';
    document.body.appendChild(el);
  }
  el.textContent    = msg;
  el.style.display  = 'flex';
  el.style.opacity  = '1';
  clearTimeout(el._timer);
  el._timer = setTimeout(() => {
    el.style.transition = 'opacity .4s';
    el.style.opacity    = '0';
    setTimeout(() => { el.style.display = 'none'; el.style.transition = ''; }, 400);
  }, 2800);
}

// Close delete modal on overlay click
document.getElementById('delete-modal').addEventListener('click', function (e) {
  if (e.target === this) closeDeleteModal();
});

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
  showAlert('Share link copied for ' + billNumber, 'success');
}

function showAlert(msg, type) {
  showDeleteToast(msg);
}
