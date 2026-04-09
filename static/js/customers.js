/* customers.js — Customers list + Customer detail pages */

// ----------------------------------------------------------------
// Shared utilities
// ----------------------------------------------------------------
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
// Detect which page we're on
// ----------------------------------------------------------------
const isDetailPage = typeof CUSTOMER_ID !== 'undefined';

document.addEventListener('DOMContentLoaded', () => {
  if (isDetailPage) {
    loadCustomerDetail();
  } else {
    loadCustomerList();
  }
});

// ================================================================
// CUSTOMERS LIST PAGE
// ================================================================
let allCustomers     = [];  // full list from API
let customerBillMap  = {};  // { customerId: [bills] } — loaded from /api/bills

async function loadCustomerList() {
  try {
    // Fetch customers and all bills in parallel for bill counts
    const [custRes, billsRes] = await Promise.all([
      fetch('/api/customers'),
      fetch('/api/bills'),
    ]);

    if (!custRes.ok)  throw new Error('Failed to load customers.');
    if (!billsRes.ok) throw new Error('Failed to load bills.');

    allCustomers = await custRes.json();
    const bills  = await billsRes.json();

    // Build bill map: customerId → sorted bills (newest first)
    customerBillMap = {};
    bills.forEach(b => {
      const cid = b.customer_id;
      if (!customerBillMap[cid]) customerBillMap[cid] = [];
      customerBillMap[cid].push(b);
    });

    document.getElementById('cust-loading').style.display = 'none';
    renderCustomerList(allCustomers);
  } catch (err) {
    document.getElementById('cust-loading').innerHTML =
      `<span class="text-danger">Error: ${err.message}</span>`;
  }
}

function renderCustomerList(customers) {
  const empty   = document.getElementById('cust-empty');
  const wrap    = document.getElementById('cust-table-wrap');
  const tbody   = document.getElementById('cust-body');
  const countEl = document.getElementById('customer-count');

  countEl.textContent = customers.length
    ? `${customers.length} customer${customers.length !== 1 ? 's' : ''}`
    : '';

  if (!customers.length) {
    empty.style.display = 'block';
    wrap.style.display  = 'none';
    return;
  }

  empty.style.display = 'none';
  wrap.style.display  = 'block';

  tbody.innerHTML = customers.map(c => {
    const bills       = customerBillMap[c.id] || [];
    const billCount   = bills.length;
    const lastBill    = bills.sort((a, b) => b.bill_date.localeCompare(a.bill_date))[0];
    const lastDate    = lastBill ? lastBill.bill_date : '—';

    return `
      <tr onclick="location.href='/customers/${c.id}'" style="cursor:pointer;">
        <td><span class="fw-600">${c.name}</span></td>
        <td style="color:var(--text-muted);">${c.mobile}</td>
        <td class="text-right col-bills">
          <span class="badge badge-info">${billCount}</span>
        </td>
        <td class="col-lastdate" style="color:var(--text-muted);">${lastDate !== '—' ? lastDate : '—'}</td>
        <td style="text-align:center;">
          <a href="/customers/${c.id}" class="btn btn-secondary btn-sm"
             onclick="event.stopPropagation()">View</a>
        </td>
      </tr>
    `;
  }).join('');
}

function filterCustomers() {
  const q = (document.getElementById('customer-search').value || '').toLowerCase().trim();
  if (!q) {
    renderCustomerList(allCustomers);
    return;
  }
  const filtered = allCustomers.filter(c =>
    c.name.toLowerCase().includes(q) ||
    (c.mobile || '').includes(q)
  );
  const emptyMsg = document.getElementById('cust-empty-msg');
  emptyMsg.textContent = filtered.length === 0
    ? `No customers match "${document.getElementById('customer-search').value}".`
    : '';
  renderCustomerList(filtered);
}

// ================================================================
// CUSTOMER DETAIL PAGE
// ================================================================
async function loadCustomerDetail() {
  try {
    const [custRes, billsRes] = await Promise.all([
      fetch(`/api/customers/${CUSTOMER_ID}`),
      fetch(`/api/customers/${CUSTOMER_ID}/bills`),
    ]);

    if (custRes.status === 404) throw new Error('Customer not found.');
    if (!custRes.ok)             throw new Error('Failed to load customer.');

    const customer = await custRes.json();
    const bills    = billsRes.ok ? await billsRes.json() : [];

    renderCustomerDetail(customer, bills);
  } catch (err) {
    document.getElementById('cd-loading').style.display = 'none';
    const errEl = document.getElementById('cd-error');
    errEl.textContent   = err.message;
    errEl.style.display = 'block';
  }
}

function renderCustomerDetail(customer, bills) {
  // Info card
  document.getElementById('cd-name').textContent   = customer.name;
  document.getElementById('cd-mobile').textContent = customer.mobile;
  document.getElementById('cd-bill-count').textContent = bills.length;

  const totalSpent = bills.reduce((s, b) => s + (b.final_total || 0), 0);
  document.getElementById('cd-total-spent').textContent = fmt(totalSpent);

  // Bills table
  const emptyEl = document.getElementById('cd-bills-empty');
  const wrapEl  = document.getElementById('cd-bills-wrap');
  const tbody   = document.getElementById('cd-bills-body');

  if (!bills.length) {
    emptyEl.style.display = 'block';
    wrapEl.style.display  = 'none';
  } else {
    emptyEl.style.display = 'none';
    wrapEl.style.display  = 'block';

    tbody.innerHTML = bills.map(b => {
      return `
        <tr onclick="location.href='/bills/${b.id}'" style="cursor:pointer;">
          <td><span class="fw-600" style="color:var(--primary);">${b.bill_number}</span></td>
          <td class="col-date">${b.bill_date || '—'}</td>
          <td class="text-right col-items">—</td>
          <td class="text-right fw-600">${fmt(b.final_total)}</td>
          <td class="col-payment">${paymentBadge(b.payment_mode_type)}</td>
          <td style="text-align:center;">
            <div style="display:flex;gap:6px;justify-content:center;" onclick="event.stopPropagation()">
              <a href="/bills/${b.id}" class="btn btn-secondary btn-sm">View</a>
              <a href="/edit-bill/${b.id}" class="btn btn-secondary btn-sm">Edit</a>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  // Show content
  document.getElementById('cd-loading').style.display = 'none';
  document.getElementById('cd-content').style.display = 'block';
}
