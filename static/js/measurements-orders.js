/* Measurements trial — billing screens: New Order form, Orders list, Order detail.
   Builds on the helpers measurements.js publishes as window.MApp. */
(function () {
  'use strict';

  var M = window.MApp;
  var $ = M.$, esc = M.esc, api = M.api, say = M.say, fmt = M.fmtMoney, fmtDate = M.fmtDate;

  var draft = null;           // the New Order form: { customer, returnTo, items: [{uid, type, rateTouched}] }
  var uid = 0;
  var currentOrder = null;    // order open in the detail view
  var listTimer = null;
  var custTimer = null;

  function meta() { return M.getMeta(); }

  // -------------------------------------------------------------------------
  // Orders list
  // -------------------------------------------------------------------------
  function loadOrders() {
    var q = $('m-order-search').value.trim();
    var type = $('m-order-type').value;
    var url = '/api/measurements/orders?q=' + encodeURIComponent(q) +
      (type ? '&type=' + encodeURIComponent(type) : '');
    api('GET', url).then(function (rows) {
      var box = $('m-order-list');
      if (!rows.length) {
        box.innerHTML = '<div class="m-empty">' + (q || type
          ? 'No order matches.'
          : 'No orders yet. Use “+ New Order” to take the first one.') + '</div>';
        return;
      }
      box.innerHTML = rows.map(orderRow).join('');
    }).catch(function (e) { say(e.message, true); });
  }

  function orderRow(o) {
    var garments = o.garments.map(function (g) {
      return g.label + (g.qty > 1 ? ' x' + g.qty : '');
    }).join(', ');
    var dates = [];
    if (o.trial_date) dates.push('Trial ' + fmtDate(o.trial_date));
    if (o.delivery_date) dates.push('Delivery ' + fmtDate(o.delivery_date));
    var owed = o.total + o.cloth_balance;
    var money = !owed ? 'No amount' : (o.balance > 0 ? 'Balance ' + fmt(o.balance) : 'Fully paid');
    return '<button type="button" class="m-order-row" data-id="' + o.id + '">' +
      '<span class="m-or-main">' +
        '<span class="m-or-label">' + esc(o.label) + '</span> ' +
        '<span class="m-or-name">' + esc(o.customer_name) + '</span> ' +
        '<span class="m-brief-sub">' + esc(o.mobile) + '</span>' +
        '<span class="m-brief-sub">' + esc(garments + (dates.length ? ' · ' + dates.join(' · ') : '')) + '</span>' +
      '</span>' +
      '<span class="m-or-right">' +
        '<span class="badge ' + (M.STATUS_BADGE[o.status] || 'badge-neutral') + '">' + esc(o.status) + '</span>' +
        '<span class="m-or-money' + (o.balance > 0 ? ' due' : '') + '">' + esc(money) + '</span>' +
      '</span></button>';
  }

  // -------------------------------------------------------------------------
  // Order detail
  // -------------------------------------------------------------------------
  function openOrder(id) {
    return api('GET', '/api/measurements/orders/' + id).then(renderOrder)
      .catch(function (e) { say(e.message, true); });
  }

  // Re-read the open order after a change made on its screen. If the user has
  // already gone back to the list by the time the answer arrives, leave them there.
  function reloadOrder() {
    if (!currentOrder) return null;
    var id = currentOrder.id;
    return api('GET', '/api/measurements/orders/' + id).then(function (o) {
      if (currentOrder && currentOrder.id === id && M.getView() === 'order') renderOrder(o);
    }).catch(function (e) { say(e.message, true); });
  }

  function moneyRow(label, value, cls) {
    return '<div class="m-money-row' + (cls ? ' ' + cls : '') + '"><span>' + esc(label) +
      '</span><b>' + esc(value) + '</b></div>';
  }

  function renderOrder(o) {
    currentOrder = o;
    M.showView('order');

    var dates = ['Order ' + fmtDate(o.order_date)];
    if (o.trial_date) dates.push('Trial ' + fmtDate(o.trial_date));
    if (o.delivery_date) dates.push('Delivery ' + fmtDate(o.delivery_date));
    $('m-order-head').innerHTML =
      '<div class="card m-customer-card"><div class="m-customer-head"><div>' +
        '<div class="m-customer-name">' + esc(o.label) + ' ' +
          '<span class="badge ' + (M.STATUS_BADGE[o.status] || 'badge-neutral') + '">' + esc(o.status) + '</span>' +
          (o.order_type === 'suit' ? ' <span class="badge badge-info">Suits</span>' : '') + '</div>' +
        '<div class="m-customer-sub"><button type="button" class="m-link" data-customer="' +
          o.customer.id + '">' + esc(o.customer.name) + '</button> · ' + esc(o.customer.mobile) + '</div>' +
        '<div class="m-customer-sub">' + esc(dates.join(' · ')) + '</div>' +
        (o.delivered_at ? '<div class="m-customer-sub">Delivered ' + esc(o.delivered_at.slice(0, 10)) + '</div>' : '') +
        (o.notes ? '<div class="m-customer-sub">Notes: ' + esc(o.notes) + '</div>' : '') +
      '</div><div class="m-actions">' +
        '<a class="btn btn-secondary btn-sm" href="/measurements/orders/' + o.id +
          '/receipt" target="_blank" rel="noopener">' +
          '<svg class="ico" aria-hidden="true"><use href="#i-printer"/></svg> Receipt</a>' +
        '<button type="button" class="btn btn-secondary btn-sm" id="m-order-edit-btn">' +
          '<svg class="ico" aria-hidden="true"><use href="#i-pencil"/></svg> Edit</button>' +
        '<button type="button" class="btn btn-danger-outline btn-sm" id="m-order-delete-btn">' +
          '<svg class="ico" aria-hidden="true"><use href="#i-trash"/></svg> Delete order</button>' +
      '</div></div></div>';

    var payments = o.payments.length
      ? o.payments.map(function (p) {
          return '<div class="m-pay-row"><span>' + esc(fmtDate((p.paid_at || '').slice(0, 10))) +
            (p.mode ? ' · ' + esc(p.mode) : '') + (p.note ? ' · ' + esc(p.note) : '') +
            '</span><span class="m-pay-amt"><b>' + esc(fmt(p.amount)) + '</b>' +
            '<button type="button" class="m-icon-btn" data-pay-del="' + p.id + '" ' +
            'title="Remove this payment" aria-label="Remove payment of ' + esc(fmt(p.amount)) + '">' +
            '<svg class="ico" aria-hidden="true"><use href="#i-trash"/></svg></button></span></div>';
        }).join('')
      : '<div class="m-empty" style="padding:6px 0;">No payments recorded yet.</div>';
    $('m-order-money').innerHTML =
      '<div class="card"><div class="m-card-title">Payment</div>' +
        '<div class="m-money">' +
          moneyRow('Stitching total', fmt(o.total)) +
          moneyRow('Cloth balance', fmt(o.cloth_balance)) +
          moneyRow('Final total', fmt(o.final_total), 'is-strong') +
          moneyRow('Paid', fmt(o.advance)) +
          moneyRow(o.balance > 0 ? 'Balance due' : 'Balance', o.balance > 0 ? fmt(o.balance) : 'Fully paid',
            o.balance > 0 ? 'is-due' : 'is-paid') +
        '</div>' +
        '<div class="m-section-title" style="margin-top:12px;">Payments received</div>' + payments +
        (o.balance > 0 ? payForm(o) : '') +
      '</div>';

    $('m-order-items').innerHTML = o.items.map(M.measurementCard).join('');
    $('m-order-garment-pick').innerHTML = '<option value="">— Select garment —</option>' +
      meta().garments.map(function (g) {
        return '<option value="' + g.type + '">' + esc(g.label) + '</option>';
      }).join('');
  }

  function payForm(o) {
    var modes = (meta().payment_modes || []).map(function (m) {
      return '<option value="' + esc(m) + '"' + (m === o.payment_mode ? ' selected' : '') + '>' +
        esc(m) + '</option>';
    }).join('');
    return '<div class="m-payform">' +
      '<div class="m-section-title" style="margin:12px 0 6px;">Record a payment</div>' +
      '<div class="m-payform-row">' +
        '<div><label class="m-label" for="m-pay-amount">Amount (₹)</label>' +
          '<input type="number" id="m-pay-amount" class="input" min="0" step="any" inputmode="decimal" ' +
          'placeholder="' + esc(fmt(o.balance)) + ' due" /></div>' +
        '<div><label class="m-label" for="m-pay-mode">Mode</label>' +
          '<select id="m-pay-mode" class="input"><option value="">—</option>' + modes + '</select></div>' +
        '<div class="m-grow"><label class="m-label" for="m-pay-note">Note</label>' +
          '<input type="text" id="m-pay-note" class="input" maxlength="80" placeholder="Optional" /></div>' +
      '</div>' +
      '<div id="m-pay-error" class="m-error hidden" style="margin-top:8px;"></div>' +
      '<div class="m-payform-actions">' +
        '<button type="button" class="btn btn-secondary btn-sm" id="m-pay-full">Full balance</button>' +
        '<button type="button" class="btn btn-primary btn-sm" id="m-pay-save">Record payment</button>' +
      '</div></div>';
  }

  function recordPayment() {
    var o = currentOrder;
    var amount = $('m-pay-amount').value.trim();
    if (!amount) { M.showErr('m-pay-error', 'Enter the amount received'); return; }
    M.showErr('m-pay-error', '');
    $('m-pay-save').disabled = true;
    api('POST', '/api/measurements/orders/' + o.id + '/payments', {
      amount: amount, mode: $('m-pay-mode').value, note: $('m-pay-note').value.trim()
    }).then(function (updated) {
      renderOrder(updated);
      M.loadCounts();
      say('Payment of ' + fmt(parseFloat(amount)) + ' recorded');
    }).catch(function (e) {
      M.showErr('m-pay-error', e.message);
      var b = $('m-pay-save'); if (b) b.disabled = false;
    });
  }

  function deletePayment(id) {
    var p = null;
    currentOrder.payments.forEach(function (x) { if (x.id === id) p = x; });
    if (!p || !window.confirm('Remove the ' + fmt(p.amount) + ' payment? The balance will go back up.')) return;
    api('DELETE', '/api/measurements/payments/' + id).then(function (updated) {
      renderOrder(updated);
      say('Payment removed');
    }).catch(function (e) { say(e.message, true); });
  }

  // -------------------------------------------------------------------------
  // Edit the order header (dates, cloth balance, notes)
  // -------------------------------------------------------------------------
  function openEditOrder() {
    var o = currentOrder;
    $('m-order-modal-title').textContent = 'Edit ' + o.label;
    $('m-oe-order').value = o.order_date || '';
    $('m-oe-trial').value = o.trial_date || '';
    $('m-oe-delivery').value = o.delivery_date || '';
    $('m-oe-cloth').value = o.cloth_balance || '';
    $('m-oe-notes').value = o.notes || '';
    M.showErr('m-oe-error', '');
    M.openModal('m-order-modal');
  }

  function saveEditOrder() {
    var btn = $('m-oe-save');
    btn.disabled = true;
    api('PUT', '/api/measurements/orders/' + currentOrder.id, {
      order_date: $('m-oe-order').value,
      trial_date: $('m-oe-trial').value,
      delivery_date: $('m-oe-delivery').value,
      cloth_balance: $('m-oe-cloth').value.trim(),
      notes: $('m-oe-notes').value.trim()
    }).then(function (updated) {
      M.closeModal('m-order-modal');
      renderOrder(updated);
      say('Order updated');
    }).catch(function (e) { M.showErr('m-oe-error', e.message); })
      .then(function () { btn.disabled = false; });
  }

  // Adding a garment reuses the measurement form, in "add to this order" mode.
  function addGarmentToOrder() {
    var type = $('m-order-garment-pick').value;
    if (!type) { say('Choose a garment first', true); return; }
    api('GET', '/api/measurements/meta').then(function (fresh) { meta().rates = fresh.rates; })
      .catch(function () {})
      .then(function () {
        M.openMeasurementModal(null, type,
          { id: currentOrder.id, type: currentOrder.order_type, label: currentOrder.label });
      });
  }

  // Marking a garment Delivered while money is still owed asks first.
  function beforeStatusChange(status) {
    if (status !== 'Delivered' || !currentOrder || !(currentOrder.balance > 0)) return true;
    return window.confirm(fmt(currentOrder.balance) +
      ' is still due on this order. Mark this garment as Delivered anyway?');
  }

  function deleteOrder() {
    if (!currentOrder) return;
    var o = currentOrder;
    var warn = 'Delete order ' + o.label + ' with its ' + o.items.length + ' garment(s), ' +
      'measurements, photos and payments? This cannot be undone.';
    if (!window.confirm(warn)) return;
    api('DELETE', '/api/measurements/orders/' + o.id).then(function () {
      say('Order ' + o.label + ' deleted');
      backToOrders();
    }).catch(function (e) { say(e.message, true); });
  }

  function backToOrders() {
    currentOrder = null;
    M.showView('list');
    M.switchTab('orders');
    M.loadCounts();
  }

  // -------------------------------------------------------------------------
  // New order — customer
  // -------------------------------------------------------------------------
  function orderType() {
    return document.querySelector('input[name="m-no-type"]:checked').value;
  }

  function selectCustomer(c) {
    draft.customer = { id: c.id, name: c.name, mobile: c.mobile };
    renderCustomerPick();
  }

  function renderCustomerPick() {
    var c = draft.customer;
    $('m-no-cust-selected').classList.toggle('hidden', !c);
    $('m-no-cust-search-wrap').classList.toggle('hidden', !!c);
    if (c) {
      $('m-no-cust-selected').innerHTML =
        '<span><b>' + esc(c.name) + '</b> <span class="m-brief-sub">' + esc(c.mobile) + '</span></span>' +
        '<button type="button" class="btn btn-secondary btn-sm" id="m-no-change-cust">Change</button>';
    } else {
      searchCustomers();
    }
  }

  function searchCustomers() {
    var q = $('m-no-cust-search').value.trim();
    api('GET', '/api/measurements/customers?q=' + encodeURIComponent(q)).then(function (rows) {
      var box = $('m-no-cust-results');
      rows = rows.slice(0, 8);
      if (!rows.length) {
        box.innerHTML = '<div class="m-empty">' + (q ? 'No customer found — use “+ New customer”.'
          : 'No customers yet — use “+ New customer”.') + '</div>';
        return;
      }
      box.innerHTML = rows.map(function (c) {
        return '<button type="button" class="m-customer-row" data-id="' + c.id + '" data-name="' +
          esc(c.name) + '" data-mobile="' + esc(c.mobile) + '">' +
          '<span><span class="m-cr-name">' + esc(c.name) + '</span><br>' +
          '<span class="m-cr-mobile">' + esc(c.mobile) + '</span></span></button>';
      }).join('');
    }).catch(function (e) { say(e.message, true); });
  }

  // -------------------------------------------------------------------------
  // New order — garments
  // -------------------------------------------------------------------------
  function savedRate(type) {
    var rates = (meta().rates || {})[orderType()] || {};
    return rates[type] || '';
  }

  function addGarment(type) {
    var def = M.garmentDef(type);
    if (!def) return;
    var id = ++uid;
    draft.items.push({ uid: id, type: type, rateTouched: false });
    var block = document.createElement('div');
    block.className = 'm-gblock';
    block.dataset.uid = id;
    block.dataset.type = type;
    block.innerHTML =
      '<div class="m-gblock-head">' +
        '<div class="m-gblock-title">' + esc(def.label) + '</div>' +
        '<div class="m-gblock-money">' +
          '<label class="m-label" for="m-rate-' + id + '">Rate (₹)</label>' +
          '<input type="number" class="input m-rate" id="m-rate-' + id + '" min="0" step="any" ' +
            'inputmode="decimal" value="' + esc(savedRate(type)) + '" />' +
          '<span class="m-gblock-amt"></span>' +
        '</div>' +
        '<button type="button" class="btn btn-danger-outline btn-sm" data-act="remove-garment" ' +
          'aria-label="Remove ' + esc(def.label) + '"><svg class="ico" aria-hidden="true">' +
          '<use href="#i-trash"/></svg> Remove</button>' +
      '</div>' +
      '<div class="m-fields">' + M.fieldsHtml(def, {}) + '</div>' +
      '<div class="m-gblock-extra">' +
        '<div><label class="m-label">Notes</label>' +
          '<input type="text" class="input m-g-notes" maxlength="200" placeholder="Optional" /></div>' +
        '<div><label class="m-label">Fabric photo</label>' +
          '<input type="file" class="input m-g-photo" accept="image/*" /></div>' +
      '</div>';
    $('m-no-garments').appendChild(block);
    updateBlock(block);
    renderSummary();
  }

  // Same rule as the server: the garment's count field when it is a whole number >= 1.
  function blockQty(block) {
    var def = M.garmentDef(block.dataset.type);
    var countField = null;
    def.fields.forEach(function (f) { if (f.kind === 'count') countField = f; });
    if (!countField) return 1;
    var input = block.querySelector('[data-key="' + countField.key + '"]');
    var raw = input ? input.value.trim() : '';
    return /^\d+$/.test(raw) && parseInt(raw, 10) >= 1 ? parseInt(raw, 10) : 1;
  }

  function blockRate(block) {
    var v = parseFloat(block.querySelector('.m-rate').value);
    return isFinite(v) && v > 0 ? v : 0;
  }

  function updateBlock(block) {
    var qty = blockQty(block), rate = blockRate(block);
    block.querySelector('.m-gblock-amt').textContent =
      qty + ' x ' + fmt(rate) + ' = ' + fmt(qty * rate);
  }

  function blockAmount(block) { return blockQty(block) * blockRate(block); }

  function numberOf(id) {
    var v = parseFloat($(id).value);
    return isFinite(v) && v > 0 ? v : 0;
  }

  function renderSummary() {
    M.showErr('m-no-error', '');      // an old error is stale once the form changes
    var total = 0;
    var blocks = $('m-no-garments').querySelectorAll('.m-gblock');
    for (var i = 0; i < blocks.length; i++) total += blockAmount(blocks[i]);
    var cloth = numberOf('m-no-cloth'), advance = numberOf('m-no-advance');
    var finalTotal = total + cloth, balance = finalTotal - advance;
    $('m-no-summary').innerHTML =
      moneyRow('Stitching total', fmt(total)) +
      moneyRow('Cloth balance', fmt(cloth)) +
      moneyRow('Final total', fmt(finalTotal), 'is-strong') +
      moneyRow('Advance now', fmt(advance)) +
      (balance < -0.005
        ? '<div class="m-money-row is-due"><span>Advance is more than the total</span><b>' +
          esc(fmt(-balance)) + ' over</b></div>'
        : moneyRow('Balance', fmt(balance), balance > 0 ? 'is-due' : 'is-paid'));
  }

  // -------------------------------------------------------------------------
  // New order — open / save
  // -------------------------------------------------------------------------
  // The saved rates change every time an order is saved, so re-read them each
  // time the form opens instead of trusting what the page loaded with.
  function openNewOrder(customer) {
    if (!meta()) { say('Still loading — try again in a moment', true); return; }
    api('GET', '/api/measurements/meta').then(function (fresh) {
      meta().rates = fresh.rates;
      meta().today = fresh.today;
    }).catch(function () { /* keep the rates the page already has */ }).then(function () {
      showNewOrderForm(customer);
    });
  }

  function showNewOrderForm(customer) {
    draft = { customer: null, returnTo: customer ? 'customer' : 'list', items: [] };
    var pick = $('m-no-garment-pick');
    pick.innerHTML = '<option value="">— Select garment —</option>' +
      meta().garments.map(function (g) {
        return '<option value="' + g.type + '">' + esc(g.label) + '</option>';
      }).join('');
    $('m-no-mode').innerHTML = '<option value="">— Mode —</option>' +
      (meta().payment_modes || []).map(function (m) {
        return '<option value="' + esc(m) + '">' + esc(m) + '</option>';
      }).join('');
    document.querySelector('input[name="m-no-type"][value="general"]').checked = true;
    $('m-no-order-date').value = meta().today;
    ['m-no-trial-date', 'm-no-delivery-date', 'm-no-cloth', 'm-no-advance', 'm-no-notes',
     'm-no-cust-search'].forEach(function (id) { $(id).value = ''; });
    $('m-no-garments').innerHTML = '';
    M.showErr('m-no-error', '');
    $('m-no-save').disabled = false;
    if (customer) selectCustomer(customer); else renderCustomerPick();
    renderSummary();
    M.showView('neworder');
    window.scrollTo(0, 0);
  }

  function leaveNewOrder(force) {
    if (!force && draft && draft.items.length &&
        !window.confirm('Discard this order? The garments you entered will be lost.')) return;
    var back = draft ? draft.returnTo : 'list';
    var cust = draft ? draft.customer : null;
    draft = null;
    if (back === 'customer' && cust) { M.openCustomer(cust.id); return; }
    M.showList();
  }

  function collectItems() {
    var out = [];
    var blocks = $('m-no-garments').querySelectorAll('.m-gblock');
    for (var i = 0; i < blocks.length; i++) {
      var b = blocks[i], values = {};
      var inputs = b.querySelectorAll('[data-key]');
      for (var j = 0; j < inputs.length; j++) values[inputs[j].dataset.key] = inputs[j].value.trim();
      out.push({
        garment_type: b.dataset.type,
        values: values,
        notes: b.querySelector('.m-g-notes').value.trim(),
        // Always explicit: a cleared rate means 0, not "use the saved default".
        rate: b.querySelector('.m-rate').value.trim() || '0'
      });
    }
    return out;
  }

  function saveOrder() {
    var items = collectItems();
    if (!draft.customer) { M.showErr('m-no-error', 'Choose a customer first'); return; }
    if (!items.length) { M.showErr('m-no-error', 'Add at least one garment'); return; }
    M.showErr('m-no-error', '');

    var body = {
      customer_id: draft.customer.id,
      order_type: orderType(),
      order_date: $('m-no-order-date').value,
      trial_date: $('m-no-trial-date').value,
      delivery_date: $('m-no-delivery-date').value,
      cloth_balance: $('m-no-cloth').value.trim(),
      advance: $('m-no-advance').value.trim(),
      payment_mode: $('m-no-mode').value,
      notes: $('m-no-notes').value.trim(),
      items: items
    };
    var blocks = $('m-no-garments').querySelectorAll('.m-gblock');
    var btn = $('m-no-save');
    btn.disabled = true;

    api('POST', '/api/measurements/orders', body).then(function (order) {
      // The order is saved. Photos go up one by one afterwards; a failed photo
      // must not make the saved order look unsaved.
      var failed = 0, chain = Promise.resolve();
      for (var i = 0; i < blocks.length; i++) {
        (function (idx) {
          var file = blocks[idx].querySelector('.m-g-photo').files[0];
          if (!file || !order.items[idx]) return;
          chain = chain.then(function () {
            var fd = new FormData();
            fd.append('photo', file);
            return fetch('/api/measurements/' + order.items[idx].id + '/photo',
                         { method: 'POST', body: fd })
              .then(function (r) { if (!r.ok) failed++; })
              .catch(function () { failed++; });
          });
        })(i);
      }
      return chain.then(function () {
        draft = null;
        M.loadCounts();
        return openOrder(order.id).then(function () {
          say('Order ' + order.label + ' saved' +
              (failed ? ' — ' + failed + ' photo(s) could not be uploaded' : ''), failed > 0);
        });
      });
    }).catch(function (e) {
      M.showErr('m-no-error', e.message);
      btn.disabled = false;
    });
  }

  // -------------------------------------------------------------------------
  // Wiring
  // -------------------------------------------------------------------------
  function init() {
    M.loadOrders = loadOrders;
    M.openOrder = openOrder;
    M.reloadOrder = reloadOrder;

    $('m-new-order-btn').addEventListener('click', function () { openNewOrder(null); });
    $('m-cust-new-order-btn').addEventListener('click', function () {
      openNewOrder(M.getCurrent());
    });

    $('m-order-search').addEventListener('input', function () {
      clearTimeout(listTimer);
      listTimer = setTimeout(loadOrders, 250);
    });
    $('m-order-type').addEventListener('change', loadOrders);
    $('m-order-list').addEventListener('click', function (ev) {
      var row = ev.target.closest('.m-order-row');
      if (row) openOrder(parseInt(row.dataset.id, 10));
    });

    // order detail
    $('m-order-back-btn').addEventListener('click', backToOrders);
    M.beforeStatusChange = beforeStatusChange;
    $('m-order-head').addEventListener('click', function (ev) {
      if (ev.target.closest('#m-order-delete-btn')) { deleteOrder(); return; }
      if (ev.target.closest('#m-order-edit-btn')) { openEditOrder(); return; }
      var link = ev.target.closest('.m-link');
      if (link) M.openCustomer(parseInt(link.dataset.customer, 10));
    });
    $('m-order-money').addEventListener('click', function (ev) {
      if (ev.target.closest('#m-pay-save')) { recordPayment(); return; }
      if (ev.target.closest('#m-pay-full')) {
        $('m-pay-amount').value = currentOrder.balance; return;
      }
      var del = ev.target.closest('[data-pay-del]');
      if (del) deletePayment(parseInt(del.dataset.payDel, 10));
    });
    $('m-oe-save').addEventListener('click', saveEditOrder);
    $('m-order-add-garment').addEventListener('click', addGarmentToOrder);
    M.bindMeasurementList($('m-order-items'), function (id) {
      var found = null;
      if (currentOrder) currentOrder.items.forEach(function (m) { if (m.id === id) found = m; });
      return found;
    });

    // new order
    $('m-no-back-btn').addEventListener('click', function () { leaveNewOrder(false); });
    $('m-no-cancel-btn').addEventListener('click', function () { leaveNewOrder(false); });
    $('m-no-cust-search').addEventListener('input', function () {
      clearTimeout(custTimer);
      custTimer = setTimeout(searchCustomers, 250);
    });
    $('m-no-cust-results').addEventListener('click', function (ev) {
      var row = ev.target.closest('.m-customer-row');
      if (row) selectCustomer({ id: parseInt(row.dataset.id, 10),
                                name: row.dataset.name, mobile: row.dataset.mobile });
    });
    $('m-no-cust-selected').addEventListener('click', function (ev) {
      if (ev.target.closest('#m-no-change-cust')) { draft.customer = null; renderCustomerPick(); }
    });
    $('m-no-newcust-btn').addEventListener('click', function () {
      M.afterCustomerSave = selectCustomer;
      M.openCustomerModal(null);
    });

    $('m-no-add-garment').addEventListener('click', function () {
      var type = $('m-no-garment-pick').value;
      if (!type) { M.showErr('m-no-error', 'Choose a garment to add'); return; }
      M.showErr('m-no-error', '');
      addGarment(type);
    });

    var garments = $('m-no-garments');
    garments.addEventListener('input', function (ev) {
      var block = ev.target.closest('.m-gblock');
      if (!block) return;
      if (ev.target.classList.contains('m-rate')) {
        draft.items.forEach(function (it) { if (String(it.uid) === block.dataset.uid) it.rateTouched = true; });
      }
      updateBlock(block);
      renderSummary();
    });
    garments.addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-act="remove-garment"]');
      if (!btn) return;
      var block = btn.closest('.m-gblock');
      draft.items = draft.items.filter(function (it) { return String(it.uid) !== block.dataset.uid; });
      block.remove();
      renderSummary();
    });

    ['m-no-cloth', 'm-no-advance'].forEach(function (id) {
      $(id).addEventListener('input', renderSummary);
    });

    // Switching General <-> Suits swaps in that type's saved rates, but never
    // over a rate somebody typed by hand.
    var radios = document.querySelectorAll('input[name="m-no-type"]');
    for (var r = 0; r < radios.length; r++) {
      radios[r].addEventListener('change', function () {
        if (!draft) return;
        var blocks = $('m-no-garments').querySelectorAll('.m-gblock');
        for (var i = 0; i < blocks.length; i++) {
          var block = blocks[i];
          var item = draft.items.filter(function (it) { return String(it.uid) === block.dataset.uid; })[0];
          if (item && !item.rateTouched) {
            block.querySelector('.m-rate').value = savedRate(block.dataset.type);
            updateBlock(block);
          }
        }
        renderSummary();
      });
    }

    $('m-no-save').addEventListener('click', saveOrder);
  }

  init();
})();
