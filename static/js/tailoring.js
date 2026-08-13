/* ============================================================
   tailoring.js — Tailoring Delivery System page
   Standalone: does not depend on billing JS modules.
   Shared by both the general Tailoring page and the Suits page —
   window.TL_CONFIG (set by the page template) picks which backend
   this instance talks to and whether the Book No field applies.
   ============================================================ */

const TL_CFG = window.TL_CONFIG || {};
const TL_API = TL_CFG.apiBase || '/api/tailoring';
const TL_SHARE_PATH = TL_CFG.sharePath || '/tailoring/share';
const TL_HAS_BOOK_NO = !!TL_CFG.hasBookNo;

let TL_STAGES = [];
let TL_GARMENTS = [];
let TL_GARMENT_RATES = {};   // garment_type -> last-used stitching rate
let TL_LAST_BOOK_NO = '';    // sticky default for a brand-new order's Book No
let tlOrders = [];
let tlEditingOrderId = null;   // null → creating
let tlDetailOrderId = null;
let tlDetailOrder = null;      // last-rendered order object, for the payment popup

const SHOP = {
  name: 'Tailoring Needs',
  address: 'New Sangvi, Pune - 27',
  phone: '+91 9284630254',
};

/* ---------- helpers ---------- */

function tlEsc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function tlFmt(n) {
  return '₹' + Number(n || 0).toLocaleString('en-IN', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

function tlFmtDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${parseInt(d, 10)} ${months[parseInt(m, 10) - 1]} ${y}`;
}

function tlToday() {
  return istToday();  // IST calendar day, independent of operator timezone
}

function stageBadge(stage) {
  const idx = Math.max(0, TL_STAGES.indexOf(stage));
  return `<span class="tl-badge s${idx}">${tlEsc(stage)}</span>`;
}

// "Book 4 · #12" when this order carries a Book No, else just "#12".
function tlOrderLabel(o) {
  return (o.book_no ? `Book ${tlEsc(o.book_no)} · ` : '') + `#${o.order_number}`;
}

async function tlFetch(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

/* ---------- load & render list ---------- */

let tlDebounce = null;
function debouncedLoad() {
  clearTimeout(tlDebounce);
  tlDebounce = setTimeout(loadOrders, 300);
}

async function loadMeta() {
  const meta = await tlFetch(`${TL_API}/meta`);
  TL_STAGES = meta.stages;
  TL_GARMENTS = meta.garment_types;
  TL_GARMENT_RATES = meta.garment_rates || {};
  TL_LAST_BOOK_NO = meta.last_book_no || '';
  const sel = document.getElementById('tl-stage-filter');
  TL_STAGES.forEach(s => {
    const o = document.createElement('option');
    o.value = s; o.textContent = s;
    sel.appendChild(o);
  });
}

async function loadOrders() {
  const q     = document.getElementById('tl-search').value.trim();
  const stage = document.getElementById('tl-stage-filter').value;
  const due   = document.getElementById('tl-due-filter').value;
  const sort  = document.getElementById('tl-sort').value;
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (stage) params.set('stage', stage);
  if (due) params.set('due', due);
  if (sort) params.set('sort', sort);

  const data = await tlFetch(`${TL_API}/orders?` + params.toString());
  tlOrders = data.orders;
  renderStats(data.counts);
  renderList();
  // Every mutation ends in loadOrders(), so piggy-back the dashboard refresh here.
  if (tlActiveTab === 'dashboard') loadDashboard();
}

function renderStats(c) {
  const wrap = document.getElementById('tl-stats');
  const stage = document.getElementById('tl-stage-filter').value;
  const due   = document.getElementById('tl-due-filter').value;
  const chips = [
    { label: 'Total Orders', num: c.total, filter: () => setFilters('', '') , active: !stage && !due },
    ...TL_STAGES.map(s => ({
      label: s, num: c.stages[s] || 0, filter: () => setFilters(s, ''), active: stage === s,
    })),
    { label: 'Trial Today', num: c.trial_today, filter: () => setFilters('', 'trial-today'),
      active: due === 'trial-today' },
    { label: 'Delivery Today', num: c.delivery_today, filter: () => setFilters('', 'delivery-today'),
      active: due === 'delivery-today' },
    { label: 'Overdue', num: c.overdue, filter: () => setFilters('', 'overdue'),
      active: due === 'overdue', danger: c.overdue > 0 },
  ];
  wrap.innerHTML = '';
  chips.forEach(ch => {
    const div = document.createElement('div');
    div.className = 'tl-stat' + (ch.active ? ' active' : '') + (ch.danger ? ' danger' : '');
    div.innerHTML = `<div class="tl-stat-num">${ch.num}</div>
                     <div class="tl-stat-label">${tlEsc(ch.label)}</div>`;
    div.onclick = ch.filter;
    wrap.appendChild(div);
  });
}

function setFilters(stage, due) {
  document.getElementById('tl-stage-filter').value = stage;
  document.getElementById('tl-due-filter').value = due;
  loadOrders();
}

function itemsSummary(items) {
  return items.map(i => `${tlEsc(i.garment_type)} × ${i.qty}`).join(', ');
}

function renderList() {
  const list = document.getElementById('tl-orders-list');
  const empty = document.getElementById('tl-empty');
  list.innerHTML = '';
  empty.style.display = tlOrders.length ? 'none' : 'block';
  const today = tlToday();

  tlOrders.forEach(o => {
    const row = document.createElement('div');
    row.className = 'tl-order-row';
    const notDone = o.stage !== 'Delivered';
    // Matches the server's _is_overdue: once every garment is Full Stitched,
    // a late pickup is on the customer, not a stitching delay — no red flag.
    const stitchingPending = notDone && o.stage !== 'Full Stitched';
    const trialCls = notDone && o.trial_date === today ? 'due-today'
                   : notDone && o.trial_date && o.trial_date < today ? 'overdue' : '';
    const delCls   = notDone && o.delivery_date === today ? 'due-today'
                   : stitchingPending && o.delivery_date && o.delivery_date < today ? 'overdue' : '';
    const balCls = o.balance > 0 ? 'pending' : 'paid';
    const balText = o.balance > 0
      ? `Balance ${tlFmt(o.balance)}${o.cloth_balance > 0 ? ` (incl. cloth ${tlFmt(o.cloth_balance)})` : ''}`
      : 'Fully paid';

    row.innerHTML = `
      <div class="tl-order-main">
        <span class="tl-order-no">${tlOrderLabel(o)}</span>
        <span class="tl-order-cust">&nbsp; ${tlEsc(o.customer_name)}${o.mobile ? ' · ' + tlEsc(o.mobile) : ''}</span>
        <div class="tl-order-items">${itemsSummary(o.items)}
          ${o.photos.length ? `&nbsp;· \u{1F4F7} ${o.photos.length}` : ''}</div>
      </div>
      <div class="tl-order-dates">
        <div class="${trialCls}">Trial: ${tlFmtDate(o.trial_date)}</div>
        <div class="${delCls}">Delivery: ${tlFmtDate(o.delivery_date)}</div>
      </div>
      <div class="tl-order-right">
        ${stageBadge(o.stage)}
        <div class="tl-balance ${balCls}">${balText}</div>
      </div>`;
    row.onclick = () => openDetailModal(o.id);
    list.appendChild(row);
  });
}

/* ---------- dashboard tab ---------- */

let tlActiveTab = 'dashboard';
let tlSelectedDay = null;   // date whose orders are expanded under the strip
let tlDashDays = [];        // last-loaded 15-day data, for the day detail
let tlOverdueDay = null;    // same shape as a day, shown first in the strip
const TL_OVERDUE_KEY = 'overdue';   // stands in for a date in tlSelectedDay

function switchTlTab(tab) {
  tlActiveTab = tab;
  ['dashboard', 'orders', 'customers'].forEach(t => {
    document.getElementById('tl-tab-' + t).style.display = t === tab ? '' : 'none';
  });
  document.querySelectorAll('.tl-tab').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === tab));
  if (tab === 'dashboard') loadDashboard();
  if (tab === 'customers') loadCustomers();
}

async function loadDashboard() {
  try {
    const d = await tlFetch(`${TL_API}/dashboard`);
    tlDashDays = d.days;
    tlOverdueDay = d.overdue_day;
    renderDayStrip(d);
    renderDashSections(d);
    renderDayDetail();   // keep the expanded day (if any) in sync
  } catch (e) {
    console.error(e);
  }
}

function tlDayName(iso, todayIso) {
  const dt = new Date(iso + 'T00:00:00');
  const names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const tomorrow = new Date(todayIso + 'T00:00:00');
  tomorrow.setDate(tomorrow.getDate() + 1);
  if (iso === todayIso) return 'Today';
  if (dt.getTime() === tomorrow.getTime()) return 'Tomorrow';
  return names[dt.getDay()];
}

function renderDayStrip(d) {
  const strip = document.getElementById('tl-day-strip');
  strip.innerHTML = '';
  // Overdue rides at the head of the strip in the same format as a day, but
  // only when there is something overdue — an always-on zero card would just
  // push the real days out of view.
  if (d.overdue_day && d.overdue_day.orders) {
    strip.appendChild(dayCard(d, d.overdue_day, TL_OVERDUE_KEY, 'Overdue', 'overdue'));
  }
  d.days.forEach(day => {
    const cls = day.date === d.today ? 'today' : '';
    const title = `${tlDayName(day.date, d.today)} · ${tlFmtDate(day.date)}`;
    strip.appendChild(dayCard(d, day, day.date, title, cls));
  });
}

function dayCard(d, day, key, title, extraCls) {
  const overdue = key === TL_OVERDUE_KEY;
  const card = document.createElement('div');
  card.className = 'tl-day' + (extraCls ? ' ' + extraCls : '')
    + (key === tlSelectedDay ? ' selected' : '');
  const garmentLines = Object.entries(day.garments)
    .map(([g, n]) => `${tlEsc(g)} <span class="tl-day-qty">${n}</span>`)
    .join('<br/>');
  const countHtml = day.orders
    ? `<div class="tl-day-count${overdue || day.orders >= 4 ? ' busy' : ''}">${day.orders} order${day.orders > 1 ? 's' : ''}</div>`
    : `<div class="tl-day-count free">Free</div>`;
  const trialWord = overdue ? 'missed trial' : 'trial';
  card.innerHTML = `
    <div class="tl-day-name">${title}</div>
    ${countHtml}
    <div class="tl-day-garments">${garmentLines}</div>
    ${day.trials ? `<div class="tl-day-trials">${day.trials} ${trialWord}${day.trials > 1 ? 's' : ''}</div>` : ''}`;
  card.onclick = () => {
    tlSelectedDay = tlSelectedDay === key ? null : key;
    renderDayStrip(d);
    renderDayDetail();
  };
  return card;
}

function renderDayDetail() {
  const box = document.getElementById('tl-day-detail');
  const overdue = tlSelectedDay === TL_OVERDUE_KEY;
  // A reload that clears the last overdue order also drops its card, so the
  // panel below must close with it instead of lingering as an empty box.
  const day = overdue
    ? (tlOverdueDay && tlOverdueDay.orders ? tlOverdueDay : null)
    : tlDashDays.find(x => x.date === tlSelectedDay);
  if (!day) { box.style.display = 'none'; box.innerHTML = ''; return; }
  box.style.display = '';
  box.innerHTML = `
    <div style="font-weight:600;font-size:13px;margin-bottom:2px;">
      ${overdue ? 'Overdue deliveries — stitching pending'
                : `Deliveries on ${tlFmtDate(day.date)}`}</div>
    ${day.order_list.length
      ? day.order_list.map(dashRowHtml).join('')
      : `<div class="tl-dash-empty">${overdue ? 'Nothing overdue. 🎉'
           : 'No deliveries planned — good day to promise.'}</div>`}`;
}

function dashRowHtml(b) {
  const allReady = b.ready_items === b.total_items;
  const readiness = allReady
    ? '<span class="tl-ready">✓ Ready</span>'
    : `<span class="tl-not-ready">${b.ready_items}/${b.total_items} stitched</span>`;
  const late = b.days_late
    ? ` · <span class="tl-late">${b.days_late} day${b.days_late > 1 ? 's' : ''} late</span>` : '';
  const waiting = b.days_waiting
    ? ` · <span class="tl-late">waiting ${b.days_waiting} day${b.days_waiting > 1 ? 's' : ''}</span>` : '';
  const bal = b.balance > 0
    ? `<div class="tl-balance pending">Balance ${tlFmt(b.balance)}${b.cloth_balance > 0 ? ` (incl. cloth ${tlFmt(b.cloth_balance)})` : ''}</div>`
    : '';
  return `
    <div class="tl-dash-row" onclick="openDetailModal(${b.id})">
      <div class="tl-dash-main">
        <span class="tl-order-no">${tlOrderLabel(b)}</span>
        <span class="tl-order-cust">&nbsp;${tlEsc(b.customer_name)}${b.mobile ? ' · ' + tlEsc(b.mobile) : ''}</span>
        <div class="tl-order-items">${itemsSummary(b.items)}</div>
      </div>
      <div class="tl-dash-meta">
        ${stageBadge(b.stage)}
        <div>${readiness}${late}${waiting}</div>
        ${bal}
      </div>
    </div>`;
}

function renderDashSections(d) {
  const sections = [
    { title: '🔴 Overdue — stitching pending', rows: d.overdue, danger: true,
      empty: 'Nothing overdue. 🎉' },
    { title: '📞 Ready & waiting pickup — call the customer', rows: d.ready_waiting,
      empty: 'No stitched orders waiting for pickup.' },
    { title: '📦 Deliveries today', rows: d.deliveries_today,
      empty: 'No deliveries due today.' },
    { title: '📦 Deliveries tomorrow', rows: d.deliveries_tomorrow,
      empty: 'No deliveries due tomorrow.' },
    { title: '👕 Trials today', rows: d.trials_today,
      empty: 'No trials due today.' },
    { title: '👕 Trials tomorrow', rows: d.trials_tomorrow,
      empty: 'No trials due tomorrow.' },
  ];
  const wrap = document.getElementById('tl-dash-sections');
  wrap.innerHTML = sections.map(s => `
    <div class="card tl-dash-section">
      <div class="tl-dash-head">${s.title}
        <span class="tl-dash-count${s.danger && s.rows.length ? ' danger' : ''}">${s.rows.length}</span>
      </div>
      ${s.rows.length
        ? s.rows.map(dashRowHtml).join('')
        : `<div class="tl-dash-empty">${s.empty}</div>`}
    </div>`).join('');
}

/* ---------- customers tab ---------- */

let tlCustDebounce = null;
function debouncedLoadCustomers() {
  clearTimeout(tlCustDebounce);
  tlCustDebounce = setTimeout(loadCustomers, 300);
}

async function loadCustomers() {
  const q = document.getElementById('tl-cust-search').value.trim();
  const params = q ? '?q=' + encodeURIComponent(q) : '';
  try {
    const data = await tlFetch(`${TL_API}/customers` + params);
    renderCustomers(data);
  } catch (e) {
    console.error(e);
  }
}

function renderCustomers(data) {
  const list = document.getElementById('tl-customers-list');
  const empty = document.getElementById('tl-cust-empty');
  document.getElementById('tl-cust-count').textContent =
    data.total ? `${data.total} customer${data.total > 1 ? 's' : ''}` : '';
  list.innerHTML = '';
  empty.style.display = data.customers.length ? 'none' : 'block';

  data.customers.forEach(c => {
    const row = document.createElement('div');
    row.className = 'tl-order-row';
    const balHtml = c.pending_balance > 0
      ? `<div class="tl-balance pending">Balance ${tlFmt(c.pending_balance)}</div>`
      : '<div class="tl-balance paid">Fully paid</div>';
    row.innerHTML = `
      <div class="tl-order-main">
        <span class="tl-order-no">${tlEsc(c.customer_name)}</span>
        <span class="tl-order-cust">${c.mobile ? '&nbsp;· ' + tlEsc(c.mobile) : ''}</span>
        <div class="tl-order-items">
          ${c.address ? tlEsc(c.address) + ' · ' : ''}Customer since ${tlFmtDate(c.first_order_date)}
        </div>
      </div>
      <div class="tl-order-dates">
        <div>${c.orders} order${c.orders > 1 ? 's' : ''}${c.open_orders ? ` (${c.open_orders} open)` : ''}</div>
        <div>Last: ${tlFmtDate(c.last_order_date)}</div>
      </div>
      <div class="tl-order-right">
        <div style="font-weight:600;">${tlFmt(c.total_business)}</div>
        ${balHtml}
      </div>`;
    row.onclick = () => showCustomerOrders(c);
    list.appendChild(row);
  });
}

function showCustomerOrders(c) {
  // Jump to the Orders tab pre-filtered to this customer
  document.getElementById('tl-search').value = c.mobile || c.customer_name;
  document.getElementById('tl-stage-filter').value = '';
  document.getElementById('tl-due-filter').value = '';
  switchTlTab('orders');
  loadOrders();
}

/* ---------- new / edit order modal ---------- */

function garmentOptions(selected) {
  let opts = TL_GARMENTS.map(g =>
    `<option value="${tlEsc(g)}" ${g === selected ? 'selected' : ''}>${tlEsc(g)}</option>`);
  const isCustom = selected && !TL_GARMENTS.includes(selected);
  opts.push(`<option value="__other__" ${isCustom ? 'selected' : ''}>Other…</option>`);
  return opts.join('');
}

function addItemRow(item) {
  item = item || { garment_type: '', qty: 1, rate: '', id: null };
  const wrap = document.getElementById('tlf-items');
  const row = document.createElement('div');
  row.className = 'tlf-item-row';
  row.dataset.itemId = item.id || '';
  // A row loaded with its own saved rate (existing item, or a rate already
  // typed) must never have that rate silently replaced by a garment's
  // default — only a still-untouched rate field auto-fills.
  row.dataset.rateAuto = item.rate === '' ? 'true' : 'false';
  const isCustom = item.garment_type && !TL_GARMENTS.includes(item.garment_type);
  row.innerHTML = `
    <select class="input tlf-garment" onchange="onGarmentChange(this)">
      <option value="">— garment —</option>${garmentOptions(item.garment_type)}
    </select>
    <input type="text" class="input tlf-custom" placeholder="Garment name"
           style="flex:2;min-width:120px;${isCustom ? '' : 'display:none;'}"
           value="${isCustom ? tlEsc(item.garment_type) : ''}" oninput="onCustomGarmentInput(this)" />
    <input type="number" class="input tlf-qty" min="1" value="${item.qty}" oninput="recalcTotals()" />
    <input type="number" class="input tlf-rate" min="0" placeholder="Rate"
           value="${item.rate === '' ? '' : item.rate}" oninput="onRateInput(this)" />
    <span class="tlf-amount">0.00</span>
    <button type="button" class="btn btn-danger btn-sm" title="Remove"
            onclick="this.parentElement.remove(); recalcTotals();">&#215;</button>`;
  wrap.appendChild(row);
  recalcTotals();
}

// Fills the rate field with that garment's last-used rate — but only while
// the field is still "auto" (untouched by hand since the row was created or
// since the garment was last changed). Typing a rate marks the row so the
// default never overwrites a deliberate override.
function applyDefaultRate(row, garmentType) {
  if (row.dataset.rateAuto === 'false') return;
  const rate = garmentType && TL_GARMENT_RATES[garmentType];
  if (rate === undefined || rate === null) return;
  row.querySelector('.tlf-rate').value = rate;
}

function onGarmentChange(sel) {
  const row = sel.parentElement;
  const custom = row.querySelector('.tlf-custom');
  custom.style.display = sel.value === '__other__' ? '' : 'none';
  if (sel.value !== '__other__') applyDefaultRate(row, sel.value);
  recalcTotals();
}

function onCustomGarmentInput(el) {
  applyDefaultRate(el.closest('.tlf-item-row'), el.value.trim());
  recalcTotals();
}

function onRateInput(el) {
  el.closest('.tlf-item-row').dataset.rateAuto = 'false';
  recalcTotals();
}

function readItemRows() {
  const rows = [...document.querySelectorAll('#tlf-items .tlf-item-row')];
  return rows.map(r => {
    const sel = r.querySelector('.tlf-garment').value;
    const garment = sel === '__other__'
      ? r.querySelector('.tlf-custom').value.trim()
      : sel;
    return {
      id: r.dataset.itemId ? parseInt(r.dataset.itemId, 10) : null,
      garment_type: garment,
      qty: parseInt(r.querySelector('.tlf-qty').value, 10) || 0,
      rate: parseFloat(r.querySelector('.tlf-rate').value) || 0,
    };
  });
}

// The advance split (Cash + UPI boxes instead of one Advance field) is only
// offered while creating a brand-new order — an existing order's advance is
// a single stored number with no per-leg breakdown to edit against, so
// editing always falls back to the plain single field regardless of mode.
function formComboActive() {
  return document.getElementById('tlf-payment-mode').value === 'Combination' && !tlEditingOrderId;
}

function onFormPayModeChange() {
  const combo = formComboActive();
  document.getElementById('tlf-advance-single').style.display = combo ? 'none' : 'inline-flex';
  document.getElementById('tlf-advance-combo').style.display = combo ? 'inline-flex' : 'none';
  recalcTotals();
}

function recalcTotals() {
  let total = 0;
  document.querySelectorAll('#tlf-items .tlf-item-row').forEach(r => {
    const qty = parseInt(r.querySelector('.tlf-qty').value, 10) || 0;
    const rate = parseFloat(r.querySelector('.tlf-rate').value) || 0;
    const amt = qty * rate;
    r.querySelector('.tlf-amount').textContent = amt.toFixed(2);
    total += amt;
  });

  const combo = formComboActive();
  let advance;
  if (combo) {
    const cash = parseFloat(document.getElementById('tlf-advance-cash').value) || 0;
    const upi = parseFloat(document.getElementById('tlf-advance-upi').value) || 0;
    advance = cash + upi;
    document.getElementById('tlf-advance').value = advance;
  } else {
    advance = parseFloat(document.getElementById('tlf-advance').value) || 0;
  }
  const clothBalance = parseFloat(document.getElementById('tlf-cloth-balance').value) || 0;
  const finalTotal = total + clothBalance;
  document.getElementById('tlf-total').value = total.toFixed(2);
  document.getElementById('tlf-final-total').value = finalTotal.toFixed(2);
  document.getElementById('tlf-balance').value = Math.max(0, finalTotal - advance).toFixed(2);

  // Nothing was paid yet — a payment mode has nothing to describe. Leave the
  // mode alone while combo is active, since 0 is just its starting point
  // before the user has typed either amount.
  const modeSel = document.getElementById('tlf-payment-mode');
  modeSel.disabled = advance <= 0 && !combo;
  if (advance <= 0 && !combo) modeSel.value = '';
}

/* ---------- customer lookup (mobile + name) ---------- */

// Customers here are derived from past tailoring orders only, so someone who
// has bought cloth but never ordered stitching will show up as new.

function tlNormalizeMobile(raw) {
  const digits = String(raw).replace(/\D/g, '');
  if (digits.length === 12 && digits.startsWith('91')) return digits.slice(2);
  if (digits.length === 11 && digits.startsWith('0'))  return digits.slice(1);
  return digits;
}

function tlDebounced(fn, ms) {
  let timer = null;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

function tlSetCustomerStatus(found) {
  const el = document.getElementById('tlf-cust-status');
  if (el) el.innerHTML = found
    ? '<span class="badge badge-success">&#10003; Existing Customer</span>' : '';
}

function tlFlashField(el) {
  el.style.transition = 'background 0.15s';
  el.style.background = '#fef9c3';
  setTimeout(() => {
    el.style.background = '';
    setTimeout(() => { el.style.transition = ''; }, 300);
  }, 600);
}

function tlApplyCustomer(c, { flash }) {
  const nameEl = document.getElementById('tlf-name');
  const addrEl = document.getElementById('tlf-address');
  nameEl.value = c.customer_name || '';
  // An address typed just now is more current than the one on file.
  if (!addrEl.value.trim() && c.address) addrEl.value = c.address;
  tlSetCustomerStatus(true);
  if (flash) tlFlashField(nameEl);
}

async function tlMobileSearch() {
  const norm = tlNormalizeMobile(document.getElementById('tlf-mobile').value);
  const spinner = document.getElementById('tlf-mobile-spinner');
  if (norm.length !== 10) { tlSetCustomerStatus(false); return; }

  spinner.style.display = 'inline-block';
  try {
    const data = await tlFetch(`${TL_API}/customers/search?mobile=${norm}`);
    if (data.found) tlApplyCustomer(data.customer, { flash: true });
    else tlSetCustomerStatus(false);
  } catch (e) {
    tlSetCustomerStatus(false);
  } finally {
    spinner.style.display = 'none';
  }
}

let tlNameActiveIdx = -1;

function tlHideNameSuggestions() {
  const box = document.getElementById('tlf-name-suggestions');
  if (box) { box.innerHTML = ''; box.style.display = 'none'; }
  tlNameActiveIdx = -1;
}

function tlHighlightSuggestion(idx) {
  const box = document.getElementById('tlf-name-suggestions');
  if (!box) return;
  const items = box.querySelectorAll('[data-suggest-item]');
  items.forEach((el, i) => { el.style.background = i === idx ? 'var(--bg)' : ''; });
  if (items[idx]) items[idx].scrollIntoView({ block: 'nearest' });
}

function tlOnNameKeydown(e) {
  const box = document.getElementById('tlf-name-suggestions');
  if (!box || box.style.display === 'none') return;
  const items = box.querySelectorAll('[data-suggest-item]');
  if (!items.length) return;

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    tlNameActiveIdx = (tlNameActiveIdx + 1) % items.length;
    tlHighlightSuggestion(tlNameActiveIdx);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    tlNameActiveIdx = (tlNameActiveIdx - 1 + items.length) % items.length;
    tlHighlightSuggestion(tlNameActiveIdx);
  } else if (e.key === 'Enter' && tlNameActiveIdx >= 0) {
    e.preventDefault();
    items[tlNameActiveIdx].dispatchEvent(new MouseEvent('mousedown'));
  } else if (e.key === 'Escape') {
    tlHideNameSuggestions();
  }
}

async function tlNameSuggest() {
  const box = document.getElementById('tlf-name-suggestions');
  if (!box) return;
  const q = document.getElementById('tlf-name').value.trim();
  if (q.length < 2) { tlHideNameSuggestions(); return; }

  let list;
  try {
    list = await tlFetch(`${TL_API}/customers/suggest?q=${encodeURIComponent(q)}`);
  } catch (e) {
    tlHideNameSuggestions(); return;
  }
  if (!Array.isArray(list) || !list.length) { tlHideNameSuggestions(); return; }

  tlNameActiveIdx = -1;
  box.innerHTML = '';
  list.forEach(c => {
    const item = document.createElement('div');
    item.setAttribute('data-suggest-item', '');
    item.style.cssText = 'padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--border);font-size:14px;color:var(--text);';
    const nameSpan = document.createElement('span');
    nameSpan.textContent = c.customer_name;
    const mobileSpan = document.createElement('span');
    mobileSpan.textContent = c.mobile ? ` ${c.mobile}` : '';
    mobileSpan.style.cssText = 'color:var(--text-muted);font-size:12px;margin-left:6px;';
    item.appendChild(nameSpan);
    item.appendChild(mobileSpan);
    item.addEventListener('mouseover', () => { item.style.background = 'var(--bg)'; });
    item.addEventListener('mouseout', () => {
      const items = box.querySelectorAll('[data-suggest-item]');
      if (item !== items[tlNameActiveIdx]) item.style.background = '';
    });
    item.addEventListener('mousedown', () => {
      document.getElementById('tlf-mobile').value = c.mobile || '';
      tlApplyCustomer(c, { flash: false });
      tlHideNameSuggestions();
    });
    box.appendChild(item);
  });
  box.style.display = 'block';
}

function setupCustomerLookup() {
  const mobileEl = document.getElementById('tlf-mobile');
  const nameEl = document.getElementById('tlf-name');
  if (mobileEl) mobileEl.addEventListener('input', tlDebounced(tlMobileSearch, 300));
  if (nameEl) {
    nameEl.addEventListener('input', tlDebounced(tlNameSuggest, 250));
    nameEl.addEventListener('keydown', tlOnNameKeydown);
    nameEl.addEventListener('blur', () => setTimeout(tlHideNameSuggestions, 150));
  }
}

function openOrderModal(order) {
  tlEditingOrderId = order ? order.id : null;
  tlSetCustomerStatus(false);
  tlHideNameSuggestions();
  document.getElementById('tl-order-modal-title').textContent =
    order ? `Edit Order #${order.order_number}` : 'New Tailoring Order';
  document.getElementById('tlf-error').style.display = 'none';
  const bookNoEl = document.getElementById('tlf-book-no');
  // New order: default to whatever Book No was last used, since a shop
  // works through one book at a time — retyping it every order isn't worth it.
  if (bookNoEl) bookNoEl.value = order ? (order.book_no || '') : TL_LAST_BOOK_NO;
  document.getElementById('tlf-order-no').value = order ? order.order_number : '';
  document.getElementById('tlf-name').value = order ? order.customer_name : '';
  document.getElementById('tlf-mobile').value = order ? (order.mobile || '') : '';
  document.getElementById('tlf-address').value = order ? (order.address || '') : '';
  document.getElementById('tlf-order-date').value = order ? order.order_date : tlToday();
  document.getElementById('tlf-trial-date').value = order ? (order.trial_date || '') : '';
  document.getElementById('tlf-delivery-date').value = order ? (order.delivery_date || '') : '';
  document.getElementById('tlf-advance').value = order ? order.advance : 0;
  document.getElementById('tlf-advance-cash').value = '';
  document.getElementById('tlf-advance-upi').value = '';
  document.getElementById('tlf-payment-mode').value = order ? (order.payment_mode || '') : '';
  document.getElementById('tlf-cloth-balance').value = order ? (order.cloth_balance || 0) : 0;
  document.getElementById('tlf-notes').value = order ? (order.notes || '') : '';
  document.getElementById('tlf-items').innerHTML = '';
  if (order) order.items.forEach(i => addItemRow(i));
  else addItemRow();
  onFormPayModeChange();
  document.getElementById('tl-order-modal').classList.remove('hidden');
}

function closeOrderModal() {
  document.getElementById('tl-order-modal').classList.add('hidden');
}

async function saveOrder() {
  const err = document.getElementById('tlf-error');
  const btn = document.getElementById('tlf-save-btn');
  err.style.display = 'none';

  // A new order's advance can be split Cash + UPI; if so, the order itself
  // is created with no advance and the two legs are recorded as separate
  // payments right after, same as the Combination flow in the detail modal.
  const isNewCombo = formComboActive();
  const cashAdv = isNewCombo ? (parseFloat(document.getElementById('tlf-advance-cash').value) || 0) : 0;
  const upiAdv = isNewCombo ? (parseFloat(document.getElementById('tlf-advance-upi').value) || 0) : 0;

  const bookNoEl = document.getElementById('tlf-book-no');

  const body = {
    order_number: document.getElementById('tlf-order-no').value.trim(),
    customer_name: document.getElementById('tlf-name').value.trim(),
    mobile: document.getElementById('tlf-mobile').value.trim(),
    address: document.getElementById('tlf-address').value.trim(),
    order_date: document.getElementById('tlf-order-date').value,
    trial_date: document.getElementById('tlf-trial-date').value,
    delivery_date: document.getElementById('tlf-delivery-date').value,
    advance: isNewCombo ? 0 : (parseFloat(document.getElementById('tlf-advance').value) || 0),
    payment_mode: isNewCombo ? '' : document.getElementById('tlf-payment-mode').value,
    cloth_balance: parseFloat(document.getElementById('tlf-cloth-balance').value) || 0,
    notes: document.getElementById('tlf-notes').value.trim(),
    items: readItemRows(),
  };
  if (bookNoEl) body.book_no = bookNoEl.value.trim();

  if (bookNoEl && !body.book_no) {
    err.textContent = 'Book number is required.'; err.style.display = 'block'; return;
  }
  if (!body.order_number || !(parseInt(body.order_number, 10) > 0)) {
    err.textContent = 'Order number from the receipt book is required.'; err.style.display = 'block'; return;
  }
  if (!body.customer_name) { err.textContent = 'Customer name is required.'; err.style.display = 'block'; return; }
  if (!body.items.length || body.items.some(i => !i.garment_type)) {
    err.textContent = 'Every item needs a garment selected.'; err.style.display = 'block'; return;
  }
  if (body.items.some(i => i.qty <= 0)) {
    err.textContent = 'Every item needs quantity of at least 1.'; err.style.display = 'block'; return;
  }
  if (isNewCombo && !(cashAdv > 0) && !(upiAdv > 0)) {
    err.textContent = 'Enter the cash and/or UPI advance amount.'; err.style.display = 'block'; return;
  }

  btn.disabled = true; btn.textContent = 'Saving...';
  try {
    const url = tlEditingOrderId
      ? `${TL_API}/orders/${tlEditingOrderId}` : `${TL_API}/orders`;
    const method = tlEditingOrderId ? 'PUT' : 'POST';
    let saved = await tlFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    // The server just remembered these as the new defaults — mirror that
    // in the page's cache so the very next order (same tab, no reload)
    // auto-fills the rate (and Book No) just typed instead of the stale one.
    body.items.forEach(it => {
      if (it.rate > 0) TL_GARMENT_RATES[it.garment_type] = it.rate;
    });
    if (bookNoEl) TL_LAST_BOOK_NO = body.book_no;

    if (isNewCombo) {
      if (cashAdv > 0) {
        saved = await tlFetch(`${TL_API}/orders/${saved.id}/payments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ amount: cashAdv, mode: 'Cash' }),
        });
      }
      if (upiAdv > 0) {
        saved = await tlFetch(`${TL_API}/orders/${saved.id}/payments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ amount: upiAdv, mode: 'Phone Pay' }),
        });
      }
      if (cashAdv > 0 && upiAdv > 0) {
        saved = await tlFetch(`${TL_API}/orders/${saved.id}/payment`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ advance: saved.advance, payment_mode: 'Combination' }),
        });
      }
    }

    closeOrderModal();
    await loadOrders();
    openDetailModal(saved.id);   // show detail so photos can be added right away
  } catch (e) {
    err.textContent = e.message; err.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = 'Save Order';
  }
}

/* ---------- detail modal ---------- */

async function openDetailModal(orderId) {
  tlDetailOrderId = orderId;
  closePaymentModal();   // start clean in case it was left open on a previous order
  const o = await tlFetch(`${TL_API}/orders/${orderId}`);
  renderDetail(o);
  document.getElementById('tl-detail-modal').classList.remove('hidden');
}

function closeDetailModal() {
  document.getElementById('tl-detail-modal').classList.add('hidden');
  closePaymentModal();
  tlDetailOrderId = null;
  tlDetailOrder = null;
}

function renderDetail(o) {
  tlDetailOrder = o;
  document.getElementById('tl-detail-title').textContent =
    `${o.book_no ? 'Book ' + o.book_no + ' · ' : ''}Order #${o.order_number} — ${o.customer_name}`;

  const stageOpts = s => TL_STAGES.map(st =>
    `<option value="${tlEsc(st)}" ${st === s ? 'selected' : ''}>${tlEsc(st)}</option>`).join('');

  const photoItemOptions = currentItemId => {
    const opts = [`<option value="" ${!currentItemId ? 'selected' : ''}>General</option>`].concat(
      o.items.map(i => `<option value="${i.id}" ${i.id === currentItemId ? 'selected' : ''}>` +
        `${tlEsc(i.garment_type)} × ${i.qty}</option>`));
    return opts.join('');
  };

  const itemById = {};
  o.items.forEach(i => { itemById[i.id] = i; });

  // Photos already linked to a garment get a stage selector: picking a new
  // stage advances just that one garment (splitting it off its line if it's
  // still sharing a qty>1 row with others) in a single click. Unlinked
  // ("General") photos get an assign-to-garment selector instead, since they
  // need a garment before they can have a stage of their own.
  const photoThumb = p => {
    const linkedItem = p.item_id ? itemById[p.item_id] : null;
    const control = linkedItem
      ? `<select class="input tl-photo-move" title="Advance the garment this photo shows"
                 onchange="setPhotoStage(${p.id}, this.value)">${stageOpts(linkedItem.stage)}</select>`
      : `<select class="input tl-photo-move" title="Assign this photo to a garment"
                 onchange="movePhoto(${p.id}, this.value)">${photoItemOptions(p.item_id)}</select>`;
    return `
    <div class="tl-photo-thumb">
      <img src="/tailoring/photos/${tlEsc(p.filename)}" loading="lazy"
           onclick="openLightbox('/tailoring/photos/${tlEsc(p.filename)}')" />
      <button type="button" class="tl-photo-del" title="Delete photo"
              onclick="deletePhoto(${p.id})">&#215;</button>
      ${control}
    </div>`;
  };

  const photoButtons = itemId => `
    <div class="tl-photo-btns">
      <button type="button" class="btn btn-secondary btn-sm"
              onclick="addPhotoFor(${itemId}, 'camera')">&#128247; Camera</button>
      <button type="button" class="btn btn-secondary btn-sm"
              onclick="addPhotoFor(${itemId}, 'gallery')">&#128444; Gallery</button>
    </div>`;

  const splitControl = i => i.qty > 1 ? `
        <span style="display:flex;gap:4px;align-items:center;">
          <span style="color:var(--text-muted);font-size:12px;">Split off:</span>
          <input type="number" class="input" id="tl-split-qty-${i.id}"
                 min="1" max="${i.qty - 1}" value="1" style="width:56px;padding:4px;" />
          <button type="button" class="btn btn-secondary btn-sm"
                  onclick="splitItem(${i.id}, ${i.qty})" title="Move that many units to their own row so they can change stage independently">Split off</button>
        </span>` : '';

  const itemsHtml = o.items.map(i => `
    <div class="tl-item-line" style="display:block;">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
        <span style="flex:1;min-width:130px;">
          <strong>${tlEsc(i.garment_type)}</strong> × ${i.qty}
          <span style="color:var(--text-muted);font-size:12px;">@ ${tlFmt(i.rate)} = ${tlFmt(i.amount)}</span>
        </span>
        ${stageBadge(i.stage)}
        <select class="input" style="max-width:150px;"
                onchange="changeItemStage(${i.id}, this.value)">${stageOpts(i.stage)}</select>
        ${splitControl(i)}
      </div>
      <div class="tl-photos small">${i.photos.map(photoThumb).join('')}</div>
      ${photoButtons(i.id)}
    </div>`).join('');

  const generalPhotosHtml = o.general_photos.map(photoThumb).join('');

  const body = document.getElementById('tl-detail-body');
  body.innerHTML = `
    <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;">
      <div style="font-size:13px;color:var(--text-muted);">
        Order date: <strong>${tlFmtDate(o.order_date)}</strong><br/>
        Trial: <strong>${tlFmtDate(o.trial_date)}</strong> ·
        Delivery: <strong>${tlFmtDate(o.delivery_date)}</strong><br/>
        ${o.mobile ? `Mobile: <a href="tel:${tlEsc(o.mobile)}">${tlEsc(o.mobile)}</a><br/>` : ''}
        ${o.address ? `Address: ${tlEsc(o.address)}<br/>` : ''}
        ${o.notes ? `Notes: ${tlEsc(o.notes)}` : ''}
      </div>
      <div>${stageBadge(o.stage)}</div>
    </div>

    ${o.cloth_balance > 0 ? `
    <div style="margin-top:10px;padding:8px 12px;border:1px solid #dc2626;background:#fef2f2;
                border-radius:6px;color:#991b1b;font-size:13px;font-weight:600;">
      &#9888; Includes ${tlFmt(o.cloth_balance)} cloth balance — collect the full balance below at delivery
    </div>` : ''}

    <div style="margin-top:14px;">
      <div style="font-weight:600;margin-bottom:4px;">Items &amp; Stages</div>
      ${itemsHtml}
      <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;">
        <button type="button" class="btn btn-secondary btn-sm"
                onclick="setWholeOrderStage('Delivered')">&#10003; Mark all Delivered</button>
      </div>
    </div>

    <div style="margin-top:14px;">
      <div style="font-weight:600;">Measurement Photos
        <span style="font-weight:400;font-size:12px;color:var(--text-muted);">(internal — never shown on the customer receipt)</span>
      </div>
      <div class="tl-photos">${generalPhotosHtml || '<span style="color:var(--text-muted);font-size:13px;">No photos yet.</span>'}</div>
      ${photoButtons(null)}
    </div>

    <div style="margin-top:14px;display:flex;justify-content:space-between;align-items:center;gap:12px;
                flex-wrap:wrap;padding:10px 12px;border:1px solid var(--border);border-radius:8px;">
      <div style="font-size:14px;">
        Balance: <strong style="color:${o.balance > 0 ? '#dc2626' : '#057a55'};">${tlFmt(o.balance)}</strong>
        ${o.cloth_balance > 0
          ? `<span style="color:var(--text-muted);font-size:12px;"> (incl. cloth ${tlFmt(o.cloth_balance)})</span>`
          : ''}
      </div>
      <button type="button" class="btn btn-secondary btn-sm" onclick="openPaymentModal()">&#128176; Payment</button>
    </div>

    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:18px;">
      <a class="btn btn-primary" target="_blank" rel="noopener"
         href="${buildTlWhatsAppURL(o)}">&#128172; WhatsApp</a>
      <a class="btn btn-secondary" href="${buildTlPhoneURL(o)}">&#128222; Call</a>
      <a class="btn btn-secondary" target="_blank" rel="noopener"
         href="${buildTlShareLink(o)}">&#128424; Receipt / Print</a>
      <button type="button" class="btn btn-secondary" onclick="copyTlLink(this)">Copy Link</button>
      <button type="button" class="btn btn-secondary" onclick='openOrderModal(${JSON.stringify(o).replace(/'/g, "&#39;")})'>Edit</button>
      <button type="button" class="btn btn-danger" onclick="deleteOrder(${o.id})">Delete</button>
    </div>`;

  // Keep an already-open payment popup in step with whatever just changed
  // (e.g. a stage change doesn't touch money, but re-rendering is cheap and
  // means the popup is never left showing stale figures).
  if (!document.getElementById('tl-payment-modal').classList.contains('hidden')) {
    renderPaymentModal(o);
  }
}

function renderPaymentModal(o) {
  document.getElementById('tl-payment-title').textContent =
    `Payment — Order #${o.order_number}`;
  const body = document.getElementById('tl-payment-body');
  body.innerHTML = `
    <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:14px;">
      <span>Total (stitching): <strong>${tlFmt(o.total)}</strong></span>
      <span>Final Total: <strong>${tlFmt(o.final_total)}</strong></span>
      <span>Paid: <strong>${tlFmt(o.advance)}</strong></span>
      <span>Balance: <strong style="color:${o.balance > 0 ? '#dc2626' : '#057a55'};">${tlFmt(o.balance)}</strong></span>
    </div>
    <div style="display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap;">
      <span style="font-size:14px;">Cloth Balance:</span>
      <input type="number" class="input" id="tl-cloth-balance" min="0" style="max-width:120px;"
             value="${o.cloth_balance || 0}" />
      <button type="button" class="btn btn-secondary btn-sm" onclick="updateClothBalance()">Update</button>
      <span style="font-size:12px;color:var(--text-muted);">included in Final Total &amp; Balance above</span>
    </div>
    ${paymentHistoryHtml(o)}
    ${o.balance > 0 ? `
    <div style="display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap;">
      <select class="input" id="tl-pay-mode" style="max-width:140px;" onchange="onPayModeChange()">
        <option value="" ${!o.payment_mode ? 'selected' : ''}>— mode —</option>
        <option value="Phone Pay" ${o.payment_mode === 'Phone Pay' ? 'selected' : ''}>Phone Pay</option>
        <option value="Cash" ${o.payment_mode === 'Cash' ? 'selected' : ''}>Cash</option>
        <option value="Combination" ${o.payment_mode === 'Combination' ? 'selected' : ''}>Combination</option>
      </select>
      <span id="tl-pay-single" style="display:${o.payment_mode === 'Combination' ? 'none' : 'inline-flex'};">
        <input type="number" class="input" id="tl-pay-amount" placeholder="Amount received now"
               style="max-width:180px;" min="0" />
      </span>
      <span id="tl-pay-combo" style="display:${o.payment_mode === 'Combination' ? 'inline-flex' : 'none'};gap:8px;flex-wrap:wrap;">
        <input type="number" class="input" id="tl-pay-cash" placeholder="Cash amount" style="max-width:130px;" min="0" />
        <input type="number" class="input" id="tl-pay-upi" placeholder="UPI (Phone Pay) amount" style="max-width:160px;" min="0" />
      </span>
      <button type="button" class="btn btn-secondary btn-sm" onclick="recordPayment()">Record Payment</button>
    </div>` : ''}`;
}

function openPaymentModal() {
  if (!tlDetailOrder) return;
  renderPaymentModal(tlDetailOrder);
  document.getElementById('tl-payment-modal').classList.remove('hidden');
}

function closePaymentModal() {
  document.getElementById('tl-payment-modal').classList.add('hidden');
}

async function changeItemStage(itemId, stage) {
  const o = await tlFetch(`${TL_API}/items/${itemId}/stage`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stage }),
  });
  renderDetail(o);
  loadOrders();
}

async function splitItem(itemId, currentQty) {
  const input = document.getElementById(`tl-split-qty-${itemId}`);
  const qty = parseInt(input.value, 10);
  if (!qty || qty < 1 || qty >= currentQty) {
    alert(`Enter a number between 1 and ${currentQty - 1}`);
    return;
  }
  const o = await tlFetch(`${TL_API}/items/${itemId}/split`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ qty }),
  });
  renderDetail(o);
  loadOrders();
}

async function setWholeOrderStage(stage) {
  if (!tlDetailOrderId) return;
  const o = await tlFetch(`${TL_API}/orders/${tlDetailOrderId}/stage`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stage }),
  });
  renderDetail(o);
  loadOrders();
}

function tlFmtDateTime(ts) {
  // "2026-07-08 14:22:33" → "8 Jul 2026, 2:22 pm"
  if (!ts) return '';
  const [d, t] = ts.split(' ');
  let out = tlFmtDate(d);
  if (t) {
    let [h, m] = t.split(':');
    h = parseInt(h, 10);
    const ap = h >= 12 ? 'pm' : 'am';
    out += `, ${h % 12 || 12}:${m} ${ap}`;
  }
  return out;
}

function paymentHistoryHtml(o) {
  const legacy = o.unrecorded_paid > 0 ? `
    <div class="tl-pay-row">
      <span><strong>${tlFmt(o.unrecorded_paid)}</strong> · earlier payments</span>
      <span style="color:var(--text-muted);">no details recorded</span>
    </div>` : '';
  const rows = o.payments.map(p => `
    <div class="tl-pay-row">
      <span><strong>${tlFmt(p.amount)}</strong>${p.mode ? ' · ' + tlEsc(p.mode) : ''}${p.note ? ' · ' + tlEsc(p.note) : ''}</span>
      <span style="color:var(--text-muted);">${tlFmtDateTime(p.paid_at)}
        <button type="button" class="tl-pay-del" title="Delete this payment entry"
                onclick="deleteTlPayment(${p.id})">&#215;</button>
      </span>
    </div>`).join('');
  return legacy || rows ? `<div style="margin-top:6px;">${legacy}${rows}</div>` : '';
}

function onPayModeChange() {
  const combo = document.getElementById('tl-pay-mode').value === 'Combination';
  document.getElementById('tl-pay-single').style.display = combo ? 'none' : 'inline-flex';
  document.getElementById('tl-pay-combo').style.display = combo ? 'inline-flex' : 'none';
}

async function recordPayment() {
  if (!tlDetailOrderId) return;
  const mode = document.getElementById('tl-pay-mode').value;

  if (mode === 'Combination') {
    const cash = parseFloat(document.getElementById('tl-pay-cash').value) || 0;
    const upi = parseFloat(document.getElementById('tl-pay-upi').value) || 0;
    if (!(cash > 0) && !(upi > 0)) {
      alert('Enter the cash and/or UPI amount received.');
      return;
    }
    let o = null;
    try {
      if (cash > 0) {
        o = await tlFetch(`${TL_API}/orders/${tlDetailOrderId}/payments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ amount: cash, mode: 'Cash' }),
        });
      }
      if (upi > 0) {
        o = await tlFetch(`${TL_API}/orders/${tlDetailOrderId}/payments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ amount: upi, mode: 'Phone Pay' }),
        });
      }
      // Both legs recorded under their real mode (for an accurate history);
      // relabel the order's overall mode back to "Combination" so it doesn't
      // just show whichever leg happened to be posted last.
      if (cash > 0 && upi > 0) {
        o = await tlFetch(`${TL_API}/orders/${tlDetailOrderId}/payment`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ advance: o.advance, payment_mode: 'Combination' }),
        });
      }
    } catch (e) {
      alert(e.message);
    }
    if (o) { renderDetail(o); loadOrders(); }
    return;
  }

  const amount = parseFloat(document.getElementById('tl-pay-amount').value);
  if (!(amount > 0)) { alert('Enter the amount received now.'); return; }
  try {
    const o = await tlFetch(`${TL_API}/orders/${tlDetailOrderId}/payments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount, mode }),
    });
    renderDetail(o);
    loadOrders();
  } catch (e) {
    alert(e.message);
  }
}

async function updateClothBalance() {
  if (!tlDetailOrderId) return;
  const cloth_balance = parseFloat(document.getElementById('tl-cloth-balance').value) || 0;
  try {
    const o = await tlFetch(`${TL_API}/orders/${tlDetailOrderId}/cloth-balance`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cloth_balance }),
    });
    renderDetail(o);
    loadOrders();
  } catch (e) {
    alert(e.message);
  }
}

async function deleteTlPayment(paymentId) {
  if (!confirm('Delete this payment entry? The balance will go back up.')) return;
  try {
    const o = await tlFetch(`${TL_API}/payments/${paymentId}`, { method: 'DELETE' });
    renderDetail(o);
    loadOrders();
  } catch (e) {
    alert(e.message);
  }
}

async function deleteOrder(orderId) {
  if (!confirm('Delete this order permanently? Photos will also be removed.')) return;
  try {
    await tlFetch(`${TL_API}/orders/${orderId}`, { method: 'DELETE' });
    closeDetailModal();
    loadOrders();
  } catch (e) {
    alert(e.message);
  }
}

/* ---------- photos ---------- */

let tlPhotoItemId = null;   // garment line the next photo(s) attach to; null → whole order

/* On low-RAM tablets Android may kill the browser while the camera app is
   open; the page reloads on return and the in-memory modal state is lost.
   Persist the upload target in sessionStorage so we can recover after the
   reload (and warn the user if the photo itself was lost). */
const TL_PENDING_PHOTO_KEY = 'tl-pending-photo';

function readPendingPhoto() {
  try {
    const p = JSON.parse(sessionStorage.getItem(TL_PENDING_PHOTO_KEY));
    if (!p || !p.orderId || Date.now() - (p.at || 0) > 10 * 60 * 1000) return null;
    return p;
  } catch (e) { return null; }
}

function clearPendingPhoto() {
  try { sessionStorage.removeItem(TL_PENDING_PHOTO_KEY); } catch (e) { /* ignore */ }
}

function addPhotoFor(itemId, source) {
  tlPhotoItemId = itemId;
  try {
    sessionStorage.setItem(TL_PENDING_PHOTO_KEY, JSON.stringify({
      orderId: tlDetailOrderId, itemId: itemId, at: Date.now(),
    }));
  } catch (e) { /* ignore */ }
  document.getElementById(source === 'camera' ? 'tl-photo-camera' : 'tl-photo-gallery').click();
}

let tlPendingFiles = [];
let tlPendingPreviewUrls = [];

function uploadPhotos(input) {
  // Page may have been reloaded while the camera was open — recover the target.
  if (!tlDetailOrderId) {
    const pending = readPendingPhoto();
    if (pending) {
      tlDetailOrderId = pending.orderId;
      tlPhotoItemId = pending.itemId || null;
    }
  }
  if (!input.files || !input.files.length || !tlDetailOrderId) {
    clearPendingPhoto();
    return;
  }
  // The file itself is safely in hand now — no need for the reload-recovery flag.
  clearPendingPhoto();

  tlPendingFiles = [...input.files];
  input.value = '';

  const grid = document.getElementById('tl-photo-preview-grid');
  grid.innerHTML = '';
  tlPendingPreviewUrls = tlPendingFiles.map(f => {
    const url = URL.createObjectURL(f);
    const img = document.createElement('img');
    img.src = url;
    img.style.cssText = 'width:84px;height:84px;object-fit:cover;border-radius:8px;border:1px solid var(--border);';
    grid.appendChild(img);
    return url;
  });

  const n = tlPendingFiles.length;
  document.getElementById('tl-photo-preview-title').textContent =
    n > 1 ? `Save ${n} photos?` : 'Save this photo?';
  document.getElementById('tl-photo-save-btn').textContent =
    n > 1 ? `Save ${n} Photos` : 'Save Photo';
  document.getElementById('tl-photo-preview-modal').classList.remove('hidden');
}

function tlClosePhotoPreview() {
  tlPendingPreviewUrls.forEach(u => URL.revokeObjectURL(u));
  tlPendingPreviewUrls = [];
  tlPendingFiles = [];
  document.getElementById('tl-photo-preview-modal').classList.add('hidden');
}

function cancelPhotoPreview() {
  tlClosePhotoPreview();
}

async function confirmPhotoUpload() {
  if (!tlPendingFiles.length || !tlDetailOrderId) { tlClosePhotoPreview(); return; }
  const files = tlPendingFiles;
  const orderId = tlDetailOrderId;
  const itemId = tlPhotoItemId;
  const btn = document.getElementById('tl-photo-save-btn');
  btn.disabled = true;
  try {
    let o = null;
    for (const f of files) {
      const fd = new FormData();
      fd.append('photo', f);
      if (itemId) fd.append('item_id', itemId);
      o = await tlFetch(`${TL_API}/orders/${orderId}/photos`, {
        method: 'POST', body: fd,
      });
    }
    tlClosePhotoPreview();
    if (o) {
      renderDetail(o);
      document.getElementById('tl-detail-modal').classList.remove('hidden');
    }
    loadOrders();
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
  }
}

function showPhotoRecoveryNotice() {
  const body = document.getElementById('tl-detail-body');
  if (!body) return;
  const div = document.createElement('div');
  div.style.cssText = 'margin-bottom:12px;padding:10px 12px;border-radius:8px;' +
    'background:#fef3c7;color:#92400e;font-size:13px;line-height:1.4;';
  div.innerHTML = '&#9888;&#65039; If the photo you just took is not shown below, ' +
    'the browser reloaded before it could be saved. Please add it again — ' +
    'on this device the <strong>&#128444; Gallery</strong> button is more reliable ' +
    'than Camera (take photos with the camera app first, then attach them here).';
  body.prepend(div);
}

async function deletePhoto(photoId) {
  if (!confirm('Delete this photo?')) return;
  try {
    await tlFetch(`${TL_API}/photos/${photoId}`, { method: 'DELETE' });
    if (tlDetailOrderId) openDetailModal(tlDetailOrderId);
    loadOrders();
  } catch (e) {
    alert(e.message);
  }
}

async function movePhoto(photoId, itemId) {
  try {
    const o = await tlFetch(`${TL_API}/photos/${photoId}/item`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId || null }),
    });
    renderDetail(o);
    loadOrders();
  } catch (e) {
    alert(e.message);
  }
}

async function setPhotoStage(photoId, stage) {
  try {
    const o = await tlFetch(`${TL_API}/photos/${photoId}/stage`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stage }),
    });
    renderDetail(o);
    loadOrders();
  } catch (e) {
    alert(e.message);
  }
}

function openLightbox(src) {
  document.getElementById('tl-lightbox-img').src = src;
  document.getElementById('tl-lightbox').classList.remove('hidden');
}

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  const lb = document.getElementById('tl-lightbox');
  if (lb && !lb.classList.contains('hidden')) lb.classList.add('hidden');
});

/* ---------- WhatsApp & share link ---------- */

function buildTlShareLink(o) {
  const base = window.SHARE_BASE_URL || window.location.origin;
  if (TL_HAS_BOOK_NO) {
    return `${base}${TL_SHARE_PATH}/${encodeURIComponent(o.book_no)}/${o.order_number}`;
  }
  return `${base}${TL_SHARE_PATH}/${o.order_number}`;
}

function buildTlWhatsAppURL(o) {
  const lines = [];
  lines.push('Dear ' + o.customer_name + ',');
  lines.push('');
  lines.push('Thank you for choosing *' + SHOP.name + '*! \u{1F64F}');
  lines.push('');
  lines.push('*Order Details:*');
  if (o.book_no) lines.push('Book No : ' + o.book_no);
  lines.push('Order No : ' + o.order_number);
  lines.push('Date     : ' + tlFmtDate(o.order_date));
  lines.push('');
  lines.push('*Items:*');
  o.items.forEach(i => lines.push('• ' + i.garment_type + ' × ' + i.qty));
  lines.push('');
  if (o.trial_date)    lines.push('\u{1F455} Trial Date    : ' + tlFmtDate(o.trial_date));
  if (o.delivery_date) lines.push('\u{1F4E6} Delivery Date : ' + tlFmtDate(o.delivery_date));
  lines.push('');
  lines.push('Total   : ' + tlFmt(o.total));
  if (o.advance > 0) lines.push('Advance : ' + tlFmt(o.advance));
  if (o.balance > 0) lines.push('Balance : ' + tlFmt(o.balance) + ' (pending)');
  lines.push('');
  lines.push('\u{1F4C4} View your order here:');
  lines.push(buildTlShareLink(o));
  lines.push('');
  lines.push('\u{1F4CD} ' + SHOP.address);
  lines.push('\u{1F4DE} ' + SHOP.phone);
  lines.push('');
  lines.push('_Delivery after 7 pm. Monday closed._');

  return 'https://wa.me/' + tlNormalizeMobile(o.mobile) + '?text=' + encodeURIComponent(lines.join('\n'));
}

function tlNormalizeMobile(mobile) {
  let m = (mobile || '').replace(/\D/g, '');
  if (m.length === 10) m = '91' + m;
  else if (m.length === 11 && m.startsWith('0')) m = '91' + m.slice(1);
  return m;
}

function buildTlPhoneURL(o) {
  return 'tel:+' + tlNormalizeMobile(o.mobile);
}

function copyTlLink(btn) {
  if (!tlDetailOrder) return;
  const link = buildTlShareLink(tlDetailOrder);
  const done = () => {
    const t = btn.textContent;
    btn.textContent = 'Copied ✓';
    setTimeout(() => { btn.textContent = t; }, 2000);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(link).then(done).catch(() => { fallbackTlCopy(link); done(); });
  } else {
    fallbackTlCopy(link); done();
  }
}

function fallbackTlCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0;';
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  try { document.execCommand('copy'); } catch (e) { /* ignore */ }
  document.body.removeChild(ta);
}

/* ---------- init ---------- */

document.addEventListener('DOMContentLoaded', async () => {
  // Restore the upload target synchronously, in case the browser re-delivers
  // the camera file to the input right after a memory-kill reload.
  const pendingPhoto = readPendingPhoto();
  if (pendingPhoto) {
    tlDetailOrderId = pendingPhoto.orderId;
    tlPhotoItemId = pendingPhoto.itemId || null;
  }

  // A cancelled picker should not trigger the recovery notice later.
  ['tl-photo-camera', 'tl-photo-gallery'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('cancel', clearPendingPhoto);
  });

  setupCustomerLookup();

  try {
    await loadMeta();
    await loadOrders();
  } catch (e) {
    console.error(e);
    const list = document.getElementById('tl-orders-list');
    if (list) list.innerHTML = `<div style="padding:20px;color:#dc2626;">${tlEsc(e.message)}</div>`;
    return;
  }

  if (pendingPhoto) {
    clearPendingPhoto();
    try {
      await openDetailModal(pendingPhoto.orderId);
      showPhotoRecoveryNotice();
    } catch (e) { /* order may have been deleted meanwhile */ }
  }
});
