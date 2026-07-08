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
    Pending:     'badge-secondary',
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
        <td><span class="fw-600">${escapeHtml(c.name)}</span></td>
        <td style="color:var(--text-muted);">${escapeHtml(c.mobile)}</td>
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
  // Loyalty is optional — fetched separately so a failure there can never
  // block the customer page itself.
  fetch(`/api/loyalty/customer/${CUSTOMER_ID}`)
    .then(res => (res.ok ? res.json() : null))
    .then(loyalty => { if (loyalty) renderLoyaltySection(loyalty); })
    .catch(() => {});

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

function renderLoyaltySection(loyalty) {
  const card = document.getElementById('cd-loyalty-card');
  const body = document.getElementById('cd-loyalty-body');
  const fyEl = document.getElementById('cd-loyalty-fy');
  if (!card || !body) return;

  if (!loyalty.started) {
    fyEl.textContent = '';
    body.innerHTML = `<div style="color:var(--text-muted);font-size:13px;">
      The loyalty program hasn't started yet.
    </div>`;
    card.style.display = '';
    return;
  }

  const cycle = loyalty.current_cycle;
  fyEl.textContent = cycle ? `Cycle ${cycle.start_date} – ${cycle.end_date}` : '';

  const tierBadge = loyalty.current_tier
    ? `<span class="badge ${TIER_CSS[loyalty.current_tier]}">${TIER_LABEL[loyalty.current_tier]}</span>`
    : `<span class="badge badge-neutral">No tier yet</span>`;

  const nextThreshold = loyalty.next_threshold;
  const progressPct = nextThreshold
    ? Math.max(0, Math.min(100, (loyalty.cycle_spent / nextThreshold) * 100))
    : 100;

  const progressLine = nextThreshold
    ? `<div style="margin-top:6px;height:8px;border-radius:4px;background:var(--bg);overflow:hidden;width:220px;">
         <div style="height:100%;width:${progressPct}%;background:var(--primary);"></div>
       </div>
       <div style="margin-top:4px;font-size:12px;color:var(--text-muted);">
         ${fmt(loyalty.amount_to_next)} more to ${TIER_LABEL[loyalty.next_tier]}
       </div>`
    : `<div style="margin-top:6px;font-size:12px;color:var(--success);font-weight:600;">Highest tier reached!</div>`;

  const giftsHtml = loyalty.gifts && loyalty.gifts.length
    ? loyalty.gifts.map(g => `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
          <span class="badge ${TIER_CSS[g.tier]}">${TIER_LABEL[g.tier]}</span>
          ${g.given_at
            ? `<span style="color:var(--success);font-size:12px;">&#10003; Given on ${g.given_at.slice(0, 10)}</span>`
            : `<span style="color:var(--warning);font-size:12px;">&#9888; Pending</span>`}
        </div>
      `).join('')
    : `<div style="color:var(--text-muted);font-size:12px;">No gifts earned this cycle yet.</div>`;

  body.innerHTML = `
    <div>
      <div class="text-muted" style="font-size:11.5px;font-weight:600;text-transform:uppercase;
           letter-spacing:.4px;margin-bottom:4px;">Current Tier</div>
      ${tierBadge}
    </div>
    <div>
      <div class="text-muted" style="font-size:11.5px;font-weight:600;text-transform:uppercase;
           letter-spacing:.4px;margin-bottom:4px;">Cycle Spend</div>
      <div style="font-size:18px;font-weight:700;">${fmt(loyalty.cycle_spent)}</div>
      ${progressLine}
    </div>
    <div>
      <div class="text-muted" style="font-size:11.5px;font-weight:600;text-transform:uppercase;
           letter-spacing:.4px;margin-bottom:4px;">Gifts Earned</div>
      ${giftsHtml}
    </div>
  `;

  card.style.display = '';
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
