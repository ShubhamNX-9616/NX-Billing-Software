/* ============================================================
   tailoring.js — Tailoring Delivery System page
   Standalone: does not depend on billing JS modules.
   ============================================================ */

let TL_STAGES = [];
let TL_GARMENTS = [];
let tlOrders = [];
let tlEditingOrderId = null;   // null → creating
let tlDetailOrderId = null;

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
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function stageBadge(stage) {
  const idx = Math.max(0, TL_STAGES.indexOf(stage));
  return `<span class="tl-badge s${idx}">${tlEsc(stage)}</span>`;
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
  const meta = await tlFetch('/api/tailoring/meta');
  TL_STAGES = meta.stages;
  TL_GARMENTS = meta.garment_types;
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
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (stage) params.set('stage', stage);
  if (due) params.set('due', due);

  const data = await tlFetch('/api/tailoring/orders?' + params.toString());
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
    const balText = o.balance > 0 ? `Balance ${tlFmt(o.balance)}` : 'Fully paid';

    row.innerHTML = `
      <div class="tl-order-main">
        <span class="tl-order-no">#${o.order_number}</span>
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
    const d = await tlFetch('/api/tailoring/dashboard');
    tlDashDays = d.days;
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
  d.days.forEach(day => {
    const card = document.createElement('div');
    card.className = 'tl-day'
      + (day.date === d.today ? ' today' : '')
      + (day.date === tlSelectedDay ? ' selected' : '');
    const garmentLines = Object.entries(day.garments)
      .map(([g, n]) => `${tlEsc(g)} – ${n}`).join('<br/>');
    const countHtml = day.orders
      ? `<div class="tl-day-count${day.orders >= 4 ? ' busy' : ''}">${day.orders} order${day.orders > 1 ? 's' : ''}</div>`
      : `<div class="tl-day-count free">Free</div>`;
    card.innerHTML = `
      <div class="tl-day-name">${tlDayName(day.date, d.today)} · ${tlFmtDate(day.date)}</div>
      ${countHtml}
      <div class="tl-day-garments">${garmentLines}</div>
      ${day.trials ? `<div class="tl-day-trials">${day.trials} trial${day.trials > 1 ? 's' : ''}</div>` : ''}`;
    card.onclick = () => {
      tlSelectedDay = tlSelectedDay === day.date ? null : day.date;
      renderDayStrip(d);
      renderDayDetail();
    };
    strip.appendChild(card);
  });
}

function renderDayDetail() {
  const box = document.getElementById('tl-day-detail');
  const day = tlDashDays.find(x => x.date === tlSelectedDay);
  if (!day) { box.style.display = 'none'; box.innerHTML = ''; return; }
  box.style.display = '';
  box.innerHTML = `
    <div style="font-weight:600;font-size:13px;margin-bottom:2px;">
      Deliveries on ${tlFmtDate(day.date)}</div>
    ${day.order_list.length
      ? day.order_list.map(dashRowHtml).join('')
      : '<div class="tl-dash-empty">No deliveries planned — good day to promise.</div>'}`;
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
    ? `<div class="tl-balance pending">Balance ${tlFmt(b.balance)}</div>` : '';
  return `
    <div class="tl-dash-row" onclick="openDetailModal(${b.id})">
      <div class="tl-dash-main">
        <span class="tl-order-no">#${b.order_number}</span>
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
    const data = await tlFetch('/api/tailoring/customers' + params);
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
  const isCustom = item.garment_type && !TL_GARMENTS.includes(item.garment_type);
  row.innerHTML = `
    <select class="input tlf-garment" onchange="onGarmentChange(this)">
      <option value="">— garment —</option>${garmentOptions(item.garment_type)}
    </select>
    <input type="text" class="input tlf-custom" placeholder="Garment name"
           style="flex:2;min-width:120px;${isCustom ? '' : 'display:none;'}"
           value="${isCustom ? tlEsc(item.garment_type) : ''}" oninput="recalcTotals()" />
    <input type="number" class="input tlf-qty" min="1" value="${item.qty}" oninput="recalcTotals()" />
    <input type="number" class="input tlf-rate" min="0" placeholder="Rate"
           value="${item.rate === '' ? '' : item.rate}" oninput="recalcTotals()" />
    <span class="tlf-amount">0.00</span>
    <button type="button" class="btn btn-danger btn-sm" title="Remove"
            onclick="this.parentElement.remove(); recalcTotals();">&#215;</button>`;
  wrap.appendChild(row);
  recalcTotals();
}

function onGarmentChange(sel) {
  const custom = sel.parentElement.querySelector('.tlf-custom');
  custom.style.display = sel.value === '__other__' ? '' : 'none';
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

function recalcTotals() {
  let total = 0;
  document.querySelectorAll('#tlf-items .tlf-item-row').forEach(r => {
    const qty = parseInt(r.querySelector('.tlf-qty').value, 10) || 0;
    const rate = parseFloat(r.querySelector('.tlf-rate').value) || 0;
    const amt = qty * rate;
    r.querySelector('.tlf-amount').textContent = amt.toFixed(2);
    total += amt;
  });
  const advance = parseFloat(document.getElementById('tlf-advance').value) || 0;
  document.getElementById('tlf-total').value = total.toFixed(2);
  document.getElementById('tlf-balance').value = Math.max(0, total - advance).toFixed(2);

  // Nothing was paid yet — a payment mode has nothing to describe.
  const modeSel = document.getElementById('tlf-payment-mode');
  modeSel.disabled = advance <= 0;
  if (advance <= 0) modeSel.value = '';
}

function openOrderModal(order) {
  tlEditingOrderId = order ? order.id : null;
  document.getElementById('tl-order-modal-title').textContent =
    order ? `Edit Order #${order.order_number}` : 'New Tailoring Order';
  document.getElementById('tlf-error').style.display = 'none';
  document.getElementById('tlf-order-no').value = order ? order.order_number : '';
  document.getElementById('tlf-name').value = order ? order.customer_name : '';
  document.getElementById('tlf-mobile').value = order ? (order.mobile || '') : '';
  document.getElementById('tlf-address').value = order ? (order.address || '') : '';
  document.getElementById('tlf-order-date').value = order ? order.order_date : tlToday();
  document.getElementById('tlf-trial-date').value = order ? (order.trial_date || '') : '';
  document.getElementById('tlf-delivery-date').value = order ? (order.delivery_date || '') : '';
  document.getElementById('tlf-advance').value = order ? order.advance : 0;
  document.getElementById('tlf-payment-mode').value = order ? (order.payment_mode || '') : '';
  document.getElementById('tlf-notes').value = order ? (order.notes || '') : '';
  document.getElementById('tlf-items').innerHTML = '';
  if (order) order.items.forEach(i => addItemRow(i));
  else addItemRow();
  recalcTotals();
  document.getElementById('tl-order-modal').classList.remove('hidden');
}

function closeOrderModal() {
  document.getElementById('tl-order-modal').classList.add('hidden');
}

async function saveOrder() {
  const err = document.getElementById('tlf-error');
  const btn = document.getElementById('tlf-save-btn');
  err.style.display = 'none';

  const body = {
    order_number: document.getElementById('tlf-order-no').value.trim(),
    customer_name: document.getElementById('tlf-name').value.trim(),
    mobile: document.getElementById('tlf-mobile').value.trim(),
    address: document.getElementById('tlf-address').value.trim(),
    order_date: document.getElementById('tlf-order-date').value,
    trial_date: document.getElementById('tlf-trial-date').value,
    delivery_date: document.getElementById('tlf-delivery-date').value,
    advance: parseFloat(document.getElementById('tlf-advance').value) || 0,
    payment_mode: document.getElementById('tlf-payment-mode').value,
    notes: document.getElementById('tlf-notes').value.trim(),
    items: readItemRows(),
  };

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

  btn.disabled = true; btn.textContent = 'Saving...';
  try {
    const url = tlEditingOrderId
      ? `/api/tailoring/orders/${tlEditingOrderId}` : '/api/tailoring/orders';
    const method = tlEditingOrderId ? 'PUT' : 'POST';
    const saved = await tlFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
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
  const o = await tlFetch(`/api/tailoring/orders/${orderId}`);
  renderDetail(o);
  document.getElementById('tl-detail-modal').classList.remove('hidden');
}

function closeDetailModal() {
  document.getElementById('tl-detail-modal').classList.add('hidden');
  tlDetailOrderId = null;
}

function renderDetail(o) {
  document.getElementById('tl-detail-title').textContent =
    `Order #${o.order_number} — ${o.customer_name}`;

  const stageOpts = s => TL_STAGES.map(st =>
    `<option value="${tlEsc(st)}" ${st === s ? 'selected' : ''}>${tlEsc(st)}</option>`).join('');

  const photoThumb = p => `
    <div class="tl-photo-thumb">
      <img src="/tailoring/photos/${tlEsc(p.filename)}" loading="lazy"
           onclick="openLightbox('/tailoring/photos/${tlEsc(p.filename)}')" />
      <button type="button" class="tl-photo-del" title="Delete photo"
              onclick="deletePhoto(${p.id})">&#215;</button>
    </div>`;

  const photoButtons = itemId => `
    <div class="tl-photo-btns">
      <button type="button" class="btn btn-secondary btn-sm"
              onclick="addPhotoFor(${itemId}, 'camera')">&#128247; Camera</button>
      <button type="button" class="btn btn-secondary btn-sm"
              onclick="addPhotoFor(${itemId}, 'gallery')">&#128444; Gallery</button>
    </div>`;

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

    <div style="margin-top:14px;">
      <div style="font-weight:600;margin-bottom:4px;">Payment</div>
      <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:14px;">
        <span>Total: <strong>${tlFmt(o.total)}</strong></span>
        <span>Paid: <strong>${tlFmt(o.advance)}</strong></span>
        <span>Balance: <strong style="color:${o.balance > 0 ? '#dc2626' : '#057a55'};">${tlFmt(o.balance)}</strong></span>
      </div>
      ${paymentHistoryHtml(o)}
      ${o.balance > 0 ? `
      <div style="display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap;">
        <input type="number" class="input" id="tl-pay-amount" placeholder="Amount received now"
               style="max-width:180px;" min="0" />
        <select class="input" id="tl-pay-mode" style="max-width:140px;">
          <option value="" ${!o.payment_mode ? 'selected' : ''}>— mode —</option>
          <option value="Phone Pay" ${o.payment_mode === 'Phone Pay' ? 'selected' : ''}>Phone Pay</option>
          <option value="Cash" ${o.payment_mode === 'Cash' ? 'selected' : ''}>Cash</option>
        </select>
        <button type="button" class="btn btn-secondary btn-sm" onclick="recordPayment()">Record Payment</button>
      </div>` : ''}
    </div>

    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:18px;">
      <a class="btn btn-primary" target="_blank" rel="noopener"
         href="${buildTlWhatsAppURL(o)}">&#128172; WhatsApp</a>
      <a class="btn btn-secondary" target="_blank" rel="noopener"
         href="/tailoring/share/${o.order_number}">&#128424; Receipt / Print</a>
      <button type="button" class="btn btn-secondary" onclick="copyTlLink(${o.order_number}, this)">Copy Link</button>
      <button type="button" class="btn btn-secondary" onclick='openOrderModal(${JSON.stringify(o).replace(/'/g, "&#39;")})'>Edit</button>
      <button type="button" class="btn btn-danger" onclick="deleteOrder(${o.id})">Delete</button>
    </div>`;
}

async function changeItemStage(itemId, stage) {
  const o = await tlFetch(`/api/tailoring/items/${itemId}/stage`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stage }),
  });
  renderDetail(o);
  loadOrders();
}

async function setWholeOrderStage(stage) {
  if (!tlDetailOrderId) return;
  const o = await tlFetch(`/api/tailoring/orders/${tlDetailOrderId}/stage`, {
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

async function recordPayment() {
  if (!tlDetailOrderId) return;
  const amount = parseFloat(document.getElementById('tl-pay-amount').value);
  if (!(amount > 0)) { alert('Enter the amount received now.'); return; }
  try {
    const o = await tlFetch(`/api/tailoring/orders/${tlDetailOrderId}/payments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount, mode: document.getElementById('tl-pay-mode').value }),
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
    const o = await tlFetch(`/api/tailoring/payments/${paymentId}`, { method: 'DELETE' });
    renderDetail(o);
    loadOrders();
  } catch (e) {
    alert(e.message);
  }
}

async function deleteOrder(orderId) {
  if (!confirm('Delete this order permanently? Photos will also be removed.')) return;
  try {
    await tlFetch(`/api/tailoring/orders/${orderId}`, { method: 'DELETE' });
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
      o = await tlFetch(`/api/tailoring/orders/${orderId}/photos`, {
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
    await tlFetch(`/api/tailoring/photos/${photoId}`, { method: 'DELETE' });
    if (tlDetailOrderId) openDetailModal(tlDetailOrderId);
    loadOrders();
  } catch (e) {
    alert(e.message);
  }
}

function openLightbox(src) {
  document.getElementById('tl-lightbox-img').src = src;
  document.getElementById('tl-lightbox').classList.remove('hidden');
}

/* ---------- WhatsApp & share link ---------- */

function buildTlShareLink(orderNumber) {
  const base = window.SHARE_BASE_URL || window.location.origin;
  return base + '/tailoring/share/' + orderNumber;
}

function buildTlWhatsAppURL(o) {
  const lines = [];
  lines.push('Dear ' + o.customer_name + ',');
  lines.push('');
  lines.push('Thank you for choosing *' + SHOP.name + '*! \u{1F64F}');
  lines.push('');
  lines.push('*Order Details:*');
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
  lines.push(buildTlShareLink(o.order_number));
  lines.push('');
  lines.push('\u{1F4CD} ' + SHOP.address);
  lines.push('\u{1F4DE} ' + SHOP.phone);
  lines.push('');
  lines.push('_Delivery after 7 pm. Monday closed._');

  let m = (o.mobile || '').replace(/\D/g, '');
  if (m.length === 10) m = '91' + m;
  else if (m.length === 11 && m.startsWith('0')) m = '91' + m.slice(1);
  return 'https://wa.me/' + m + '?text=' + encodeURIComponent(lines.join('\n'));
}

function copyTlLink(orderNumber, btn) {
  const link = buildTlShareLink(orderNumber);
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
