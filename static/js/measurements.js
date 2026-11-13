/* Measurements trial — page logic. Talks only to /api/measurements/*. */
(function () {
  'use strict';

  var meta = null;            // { statuses, garments, today }
  var current = null;         // customer currently open in the detail view
  var editingMeasurement = null;   // measurement being edited, or null when creating
  var addingToOrder = null;        // {id, type} when a new garment is being added to an order
  var editingCustomerId = null;    // customer being edited, or null when creating
  var searchTimer = null;
  var tab = 'dashboard';      // which list-view tab is active
  var dash = null;            // last dashboard payload
  var selectedDay = null;     // ISO date (or 'overdue') open in the day-detail panel
  var view = 'list';          // list | detail | order | neworder
  var MApp = window.MApp = { afterCustomerSave: null };   // shared with measurements-orders.js
  var STATUS_BADGE = {
    'Measured': 'badge-neutral', 'In Stitching': 'badge-info',
    'Trial Ready': 'badge-warning', 'Delivered': 'badge-success'
  };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return escapeHtml(s == null ? '' : String(s)); }

  function api(method, url, body) {
    var opts = { method: method, headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var err = new Error(data.error || 'Something went wrong');
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  function say(text, isError) {
    var el = $('m-msg');
    el.textContent = text;
    el.classList.toggle('is-error', !!isError);
    el.classList.remove('hidden');
    clearTimeout(say._t);
    say._t = setTimeout(function () { el.classList.add('hidden'); }, 4000);
  }

  function showErr(id, text) {
    var el = $(id);
    el.textContent = text || '';
    el.classList.toggle('hidden', !text);
  }

  function openModal(id) { $(id).classList.remove('hidden'); }
  function closeModal(id) {
    $(id).classList.add('hidden');
    // Dismissing the customer modal abandons whatever was waiting for its result.
    if (id === 'm-customer-modal') setTimeout(function () { MApp.afterCustomerSave = null; }, 0);
  }

  function fmtDate(d) {
    if (!d) return '';
    var p = d.split('-');
    return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : d;
  }

  function fmtMoney(n) {
    return '\u20B9' + Number(n || 0).toLocaleString('en-IN', {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }

  // One of four screens is visible at a time.
  function showView(name) {
    view = name;
    var ids = { list: 'm-view-list', detail: 'm-view-detail',
                order: 'm-view-order', neworder: 'm-view-neworder' };
    Object.keys(ids).forEach(function (k) {
      $(ids[k]).classList.toggle('hidden', k !== name);
    });
  }

  function garmentDef(type) {
    for (var i = 0; i < meta.garments.length; i++) {
      if (meta.garments[i].type === type) return meta.garments[i];
    }
    return null;
  }

  // -------------------------------------------------------------------------
  // Counts + customer list
  // -------------------------------------------------------------------------
  function loadCounts() {
    api('GET', '/api/measurements/status').then(function (d) {
      $('m-counts').textContent = ' · ' + d.customers + ' customers, ' +
        d.measurements + ' measurements saved';
    }).catch(function () {});
  }

  function loadCustomers() {
    var q = $('m-search').value.trim();
    api('GET', '/api/measurements/customers?q=' + encodeURIComponent(q)).then(function (rows) {
      var box = $('m-customer-list');
      if (!rows.length) {
        box.innerHTML = '<div class="m-empty">' + (q
          ? 'No customer found. Use “+ New Customer” to add one.'
          : 'No customers yet. Use “+ New Customer” to add the first one.') + '</div>';
        return;
      }
      box.innerHTML = rows.map(function (c) {
        return '<button type="button" class="m-customer-row" data-id="' + c.id + '">' +
          '<span><span class="m-cr-name">' + esc(c.name) + '</span><br>' +
          '<span class="m-cr-mobile">' + esc(c.mobile) + '</span></span>' +
          '<span class="badge badge-neutral">' + c.measurement_count + ' saved</span>' +
          '</button>';
      }).join('');
    }).catch(function (e) { say(e.message, true); });
  }

  // -------------------------------------------------------------------------
  // Customer detail
  // -------------------------------------------------------------------------
  function showList() {
    current = null;
    showView('list');
    switchTab(tab);
    loadCounts();
  }

  function switchTab(name) {
    tab = name;
    var tabs = document.querySelectorAll('.m-tab');
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].classList.toggle('active', tabs[i].dataset.tab === name);
    }
    $('m-tab-dashboard').classList.toggle('hidden', name !== 'dashboard');
    $('m-tab-orders').classList.toggle('hidden', name !== 'orders');
    $('m-tab-customers').classList.toggle('hidden', name !== 'customers');
    if (name === 'dashboard') loadDashboard();
    else if (name === 'orders') { if (MApp.loadOrders) MApp.loadOrders(); }
    else loadCustomers();
  }

  // -------------------------------------------------------------------------
  // Dashboard
  // -------------------------------------------------------------------------
  function loadDashboard() {
    api('GET', '/api/measurements/dashboard').then(function (d) {
      dash = d;
      renderDashboard();
    }).catch(function (e) { say(e.message, true); });
  }

  var OVERDUE_KEY = 'overdue';

  // Same naming as Tailoring: Today / Tomorrow / weekday, then the date.
  function dayTitle(iso, todayIso) {
    var p = iso.split('-');
    var dt = new Date(+p[0], +p[1] - 1, +p[2]);
    var t = todayIso.split('-');
    var tomorrow = new Date(+t[0], +t[1] - 1, +t[2] + 1);
    var name = iso === todayIso ? 'Today'
      : dt.getTime() === tomorrow.getTime() ? 'Tomorrow'
      : dt.toLocaleDateString('en-IN', { weekday: 'short' });
    return name + ' \u00b7 ' + fmtDate(iso);
  }

  function briefRow(b) {
    var sub = [b.garment_label + (b.pieces > 1 ? ' x' + b.pieces : '')];
    if (b.trial_date) sub.push('Trial ' + fmtDate(b.trial_date));
    if (b.delivery_date) sub.push('Delivery ' + fmtDate(b.delivery_date));
    var ready = b.status === 'Trial Ready'
      ? '<span class="m-ready"><svg class="ico" aria-hidden="true"><use href="#i-check-circle"/></svg> Ready</span>'
      : '';
    var notes = [];
    if (ready) notes.push(ready);
    if (b.days_late) notes.push('<span class="m-late">' + b.days_late + ' day' + (b.days_late > 1 ? 's' : '') + ' late</span>');
    if (b.days_waiting) notes.push('<span class="m-late">waiting ' + b.days_waiting + ' day' + (b.days_waiting > 1 ? 's' : '') + '</span>');
    if (b.order_label) sub.unshift(b.order_label);
    var bal = '';
    if (b.order_id) {
      bal = b.balance > 0
        ? '<span class="m-brief-bal due">Balance ' + esc(fmtMoney(b.balance)) + '</span>'
        : '<span class="m-brief-bal">Paid</span>';
    }
    return '<button type="button" class="m-brief" data-customer="' + b.customer_id + '"' +
      (b.order_id ? ' data-order="' + b.order_id + '"' : '') + '>' +
      '<span class="m-brief-main">' +
      '<span class="m-brief-name">' + esc(b.customer_name) + '</span>' +
      '<span class="m-brief-cust"> &nbsp;' + esc(b.mobile) + '</span>' +
      '<span class="m-brief-sub">' + esc(sub.join(' \u00b7 ')) + '</span></span>' +
      '<span class="m-brief-meta">' +
      '<span class="badge ' + (STATUS_BADGE[b.status] || 'badge-neutral') + '">' + esc(b.status) + '</span>' +
      (notes.length ? '<span class="m-brief-line">' + notes.join(' · ') + '</span>' : '') +
      bal +
      '</span></button>';
  }

  // Every section is always shown (with a message when empty), like Tailoring.
  function section(title, list, opts) {
    opts = opts || {};
    return '<div class="card m-section">' +
      '<div class="m-section-head">' + esc(title) +
      '<span class="m-count' + (opts.danger && list.length ? ' danger' : '') + '">' +
      list.length + '</span></div>' +
      (list.length ? list.map(briefRow).join('') : '<div class="m-empty">' + esc(opts.empty) + '</div>') +
      '</div>';
  }

  function dayCard(day, key, title, extraCls) {
    var overdue = key === OVERDUE_KEY;
    var lines = Object.keys(day.garments).map(function (g) {
      return esc(g) + ' <span class="m-day-qty">' + day.garments[g] + '</span>';
    }).join('<br>');
    var count = day.orders
      ? '<div class="m-day-count' + (overdue || day.orders >= 4 ? ' busy' : '') + '">' +
        day.orders + ' order' + (day.orders > 1 ? 's' : '') + '</div>'
      : '<div class="m-day-count free">Free</div>';
    var trials = day.trials
      ? '<div class="m-day-trials">' + day.trials + (overdue ? ' missed trial' : ' trial') +
        (day.trials > 1 ? 's' : '') + '</div>' : '';
    return '<button type="button" class="m-day' + (extraCls ? ' ' + extraCls : '') +
      (key === selectedDay ? ' selected' : '') + '" data-day="' + key + '">' +
      '<div class="m-day-name">' + esc(title) + '</div>' + count +
      '<div class="m-day-garments">' + lines + '</div>' + trials + '</button>';
  }

  function renderDashboard() {
    var d = dash;
    // Status chips
    var chips = '<div class="m-stat"><div class="m-stat-n">' + d.total +
      '</div><div class="m-stat-l">Total saved</div></div>';
    meta.statuses.forEach(function (s) {
      chips += '<div class="m-stat"><div class="m-stat-n">' + (d.counts[s] || 0) +
        '</div><div class="m-stat-l">' + esc(s) + '</div></div>';
    });
    $('m-stats').innerHTML = chips;

    // Day strip: an Overdue card first (only when something is overdue), then 15 days
    var strip = '';
    if (d.overdue_day && d.overdue_day.orders) {
      strip += dayCard(d.overdue_day, OVERDUE_KEY, 'Overdue', 'overdue');
    }
    d.days.forEach(function (day) {
      strip += dayCard(day, day.date, dayTitle(day.date, d.today), day.date === d.today ? 'today' : '');
    });
    $('m-day-strip').innerHTML = strip;
    renderDayDetail();

    $('m-dash-sections').innerHTML =
      section('Overdue \u2014 stitching pending', d.overdue, { danger: true, empty: 'Nothing overdue.' }) +
      section('Ready & waiting pickup \u2014 call the customer', d.ready_waiting,
        { empty: 'No trial-ready garments waiting for pickup.' }) +
      section('Deliveries today', d.deliveries_today, { empty: 'No deliveries due today.' }) +
      section('Deliveries tomorrow', d.deliveries_tomorrow, { empty: 'No deliveries due tomorrow.' }) +
      section('Trials today', d.trials_today, { empty: 'No trials due today.' }) +
      section('Trials tomorrow', d.trials_tomorrow, { empty: 'No trials due tomorrow.' });
  }

  function renderDayDetail() {
    var box = $('m-day-detail');
    var overdue = selectedDay === OVERDUE_KEY;
    var day = null;
    if (selectedDay && dash) {
      if (overdue) day = dash.overdue_day.orders ? dash.overdue_day : null;
      else dash.days.forEach(function (x) { if (x.date === selectedDay) day = x; });
    }
    if (!day) { box.classList.add('hidden'); box.innerHTML = ''; return; }
    box.innerHTML = '<div class="m-day-detail-title">' +
      (overdue ? 'Overdue deliveries \u2014 stitching pending' : 'Deliveries on ' + fmtDate(day.date)) +
      '</div>' +
      (day.order_list.length ? day.order_list.map(briefRow).join('')
        : '<div class="m-empty">' + (overdue ? 'Nothing overdue.' : 'No deliveries planned \u2014 good day to promise.') + '</div>');
    box.classList.remove('hidden');
  }

  function openCustomer(id) {
    return api('GET', '/api/measurements/customers/' + id).then(renderCustomer)
      .catch(function (e) { say(e.message, true); });
  }

  function renderCustomer(c) {
    current = c;
    selectedDay = null;     // come back to a clean dashboard, not a stale open day
    showView('detail');
    $('m-d-name').textContent = c.name;
    $('m-d-mobile').textContent = c.mobile;
    $('m-d-address').textContent = c.address || '';

    var list = $('m-measurement-list');
    if (!c.measurements.length) {
      list.innerHTML = '<div class="m-empty">No measurements saved for this customer yet.</div>';
      return;
    }
    list.innerHTML = c.measurements.map(measurementCard).join('');
  }

  function measurementCard(m) {
    var def = garmentDef(m.garment_type);
    var chips = '';
    if (def) {
      chips = def.fields.map(function (f) {
        var v = m.values[f.key];
        if (!v) return '';
        return '<span class="m-chip"><span>' + esc(f.label) + '</span> <b>' + esc(v) +
          (f.kind === 'inch' ? '"' : '') + '</b></span>';
      }).join('');
    }
    var dates = ['Order ' + fmtDate(m.order_date)];
    if (m.trial_date) dates.push('Trial ' + fmtDate(m.trial_date));
    if (m.delivery_date) dates.push('Delivery ' + fmtDate(m.delivery_date));

    var statusOpts = meta.statuses.map(function (s) {
      return '<option value="' + esc(s) + '"' + (s === m.status ? ' selected' : '') + '>' +
        esc(s) + '</option>';
    }).join('');

    return '<div class="m-mcard" data-id="' + m.id + '">' +
      '<div class="m-mcard-head"><div>' +
        '<div class="m-mcard-title">' + esc(m.garment_label) + ' <span ' +
        'style="font-weight:400;font-size:12px;color:var(--text-muted);">#' + m.id + '</span></div>' +
        '<div class="m-mcard-dates">' + esc(dates.join(' · ')) + '</div>' +
      '</div></div>' +
      (m.order_id ? '<div class="m-mcard-bill">Billed ' + fmtMoney(m.amount) +
        ' <span>(' + m.qty + ' x ' + fmtMoney(m.rate) + ')</span></div>' : '') +
      '<div class="m-mcard-values">' + (chips || '<span class="m-empty">No values entered</span>') + '</div>' +
      (m.notes ? '<div class="m-mcard-dates" style="margin-top:8px;">Notes: ' + esc(m.notes) + '</div>' : '') +
      (m.image_url ? '<div style="margin-top:8px;"><img src="' + esc(m.image_url) +
        '" alt="Fabric photo" style="max-height:80px;border-radius:6px;"></div>' : '') +
      '<div class="m-mcard-foot">' +
        '<label class="m-status-wrap">Status ' +
          '<select class="input m-status-select" data-id="' + m.id + '">' + statusOpts + '</select></label>' +
        '<div class="m-card-actions">' +
          (m.order_id && view !== 'order'
            ? '<button type="button" class="btn btn-secondary btn-sm" data-act="open-order" data-id="' +
              m.id + '" data-order="' + m.order_id + '">Open order</button>' : '') +
          '<a class="btn btn-secondary btn-sm" href="/measurements/' + m.id + '/print" target="_blank" rel="noopener">' +
            '<svg class="ico" aria-hidden="true"><use href="#i-printer"/></svg> Print</a>' +
          '<button type="button" class="btn btn-secondary btn-sm" data-act="edit" data-id="' + m.id + '">' +
            '<svg class="ico" aria-hidden="true"><use href="#i-pencil"/></svg> Edit</button>' +
          '<button type="button" class="btn btn-danger-outline btn-sm" data-act="delete" data-id="' + m.id + '">' +
            '<svg class="ico" aria-hidden="true"><use href="#i-trash"/></svg> Delete</button>' +
        '</div>' +
      '</div></div>';
  }

  // -------------------------------------------------------------------------
  // Customer modal
  // -------------------------------------------------------------------------
  function openCustomerModal(customer) {
    editingCustomerId = customer ? customer.id : null;
    $('m-customer-modal-title').textContent = customer ? 'Edit Customer' : 'New Customer';
    $('m-c-name').value = customer ? customer.name : '';
    $('m-c-mobile').value = customer ? customer.mobile : '';
    $('m-c-address').value = customer ? customer.address : '';
    showErr('m-c-error', '');
    openModal('m-customer-modal');
    $('m-c-name').focus();
  }

  function saveCustomer() {
    var body = {
      name: $('m-c-name').value.trim(),
      mobile: $('m-c-mobile').value.trim(),
      address: $('m-c-address').value.trim()
    };
    var req = editingCustomerId
      ? api('PUT', '/api/measurements/customers/' + editingCustomerId, body)
      : api('POST', '/api/measurements/customers', body);
    var hook = MApp.afterCustomerSave;
    req.then(function (c) {
      var wasEdit = !!editingCustomerId;
      MApp.afterCustomerSave = null;
      closeModal('m-customer-modal');
      loadCounts();
      if (hook) { hook(c); say(wasEdit ? 'Customer updated' : 'Customer added'); return; }
      renderCustomer(c);
      say(wasEdit ? 'Customer updated' : 'Customer added');
    }).catch(function (e) {
      if (e.data && e.data.customer) {
        // Mobile already saved — jump to that customer instead of a dead end.
        MApp.afterCustomerSave = null;
        closeModal('m-customer-modal');
        if (hook) { hook(e.data.customer); say('This mobile is already saved — using the existing customer'); return; }
        openCustomer(e.data.customer.id);
        say('This mobile is already saved — opened the existing customer');
        return;
      }
      showErr('m-c-error', e.message);
    });
  }

  function deleteCustomer() {
    if (!current) return;
    var n = current.measurements.length;
    var warn = 'Delete ' + current.name + (n ? ' and their ' + n + ' saved measurement(s)' : '') +
      '? This cannot be undone.';
    if (!window.confirm(warn)) return;
    api('DELETE', '/api/measurements/customers/' + current.id).then(function () {
      say('Customer deleted');
      showList();
    }).catch(function (e) { say(e.message, true); });
  }

  // -------------------------------------------------------------------------
  // Measurement modal
  // -------------------------------------------------------------------------
  function fieldsHtml(def, values) {
    return def ? def.fields.map(function (f) {
      var v = values[f.key] || '';
      var label = esc(f.label) + (f.kind === 'inch' ? ' (in)' : '');
      var control;
      if (f.kind === 'select') {
        control = '<select class="input" data-key="' + f.key + '"><option value="">—</option>' +
          f.options.map(function (o) {
            return '<option value="' + esc(o) + '"' + (o === v ? ' selected' : '') + '>' + esc(o) + '</option>';
          }).join('') + '</select>';
      } else {
        control = '<input type="text" class="input" data-key="' + f.key + '" value="' + esc(v) +
          '" inputmode="' + (f.kind === 'count' ? 'numeric' : 'decimal') + '" maxlength="40" />';
      }
      return '<div><label class="m-label">' + label + '</label>' + control + '</div>';
    }).join('') : '';
  }

  function renderFields(type, values) {
    var def = garmentDef(type);
    $('m-garment-title').textContent = def ? '— ' + def.label : '';
    $('m-fields').innerHTML = fieldsHtml(def, values);
  }

  // orderCtx ({id, type, label}) is passed when a new garment is added to an order.
  function openMeasurementModal(measurement, garmentType, orderCtx) {
    editingMeasurement = measurement || null;
    addingToOrder = !measurement && orderCtx ? orderCtx : null;
    var type = measurement ? measurement.garment_type : garmentType;
    var values = measurement ? measurement.values : {};
    var def = garmentDef(type);
    $('m-measurement-modal-title').textContent = addingToOrder
      ? 'Add ' + (def ? def.label : '') + ' to ' + addingToOrder.label
      : (measurement ? 'Edit ' : 'New ') + (def ? def.label : '') + ' Measurement';
    $('m-measurement-modal').dataset.garment = type;
    var billed = !!(measurement && measurement.order_id) || !!addingToOrder;
    $('m-f-dates').classList.toggle('hidden', billed);     // an order's dates live on the order
    $('m-f-rate-wrap').classList.toggle('hidden', !billed);
    var rate = measurement ? measurement.rate
      : (addingToOrder ? ((meta.rates || {})[addingToOrder.type] || {})[type] : '');
    $('m-f-rate').value = billed ? (rate || '') : '';
    $('m-f-order').value = measurement ? measurement.order_date || '' : meta.today;
    $('m-f-trial').value = measurement ? measurement.trial_date || '' : '';
    $('m-f-delivery').value = measurement ? measurement.delivery_date || '' : '';
    $('m-f-notes').value = measurement ? measurement.notes : '';
    $('m-f-photo').value = '';
    $('m-photo-remove').checked = false;
    var hasPhoto = !!(measurement && measurement.image_url);
    $('m-photo-current').classList.toggle('hidden', !hasPhoto);
    if (hasPhoto) $('m-photo-img').src = measurement.image_url;
    renderFields(type, values);
    showErr('m-f-error', '');
    openModal('m-measurement-modal');
  }

  function collectValues() {
    var values = {};
    var inputs = $('m-fields').querySelectorAll('[data-key]');
    for (var i = 0; i < inputs.length; i++) {
      values[inputs[i].dataset.key] = inputs[i].value.trim();
    }
    return values;
  }

  function saveMeasurement() {
    var type = $('m-measurement-modal').dataset.garment;
    var body = {
      garment_type: type,
      values: collectValues(),
      notes: $('m-f-notes').value.trim(),
      order_date: $('m-f-order').value,
      trial_date: $('m-f-trial').value,
      delivery_date: $('m-f-delivery').value
    };
    if (editingMeasurement && editingMeasurement.order_id) body.rate = $('m-f-rate').value.trim();
    // A rate left blank means 0 for this garment, not "use the saved default".
    if (addingToOrder) body.rate = $('m-f-rate').value.trim() || '0';
    var btn = $('m-f-save');
    btn.disabled = true;
    var req;
    if (editingMeasurement) {
      req = api('PUT', '/api/measurements/' + editingMeasurement.id, body);
    } else if (addingToOrder) {
      req = api('POST', '/api/measurements/orders/' + addingToOrder.id + '/items', body)
        .then(function (order) { return order.items[order.items.length - 1]; });
    } else {
      req = api('POST', '/api/measurements/customers/' + current.id + '/measurements', body);
    }

    req.then(function (saved) {
      var file = $('m-f-photo').files[0];
      if (file) {
        var fd = new FormData();
        fd.append('photo', file);
        return fetch('/api/measurements/' + saved.id + '/photo', { method: 'POST', body: fd })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (d) { throw new Error(d.error || 'Photo upload failed'); });
          });
      }
      if (editingMeasurement && $('m-photo-remove').checked) {
        return api('DELETE', '/api/measurements/' + saved.id + '/photo');
      }
    }).then(function () {
      closeModal('m-measurement-modal');
      say(editingMeasurement ? 'Measurement updated' : 'Measurement saved');
      loadCounts();
      return refreshAfterChange();
    }).catch(function (e) {
      showErr('m-f-error', e.message);
      // The measurement itself may have saved even if the photo failed.
      refreshAfterChange();
    }).then(function () { btn.disabled = false; });
  }

  // Re-read whichever screen the measurement belongs to.
  function refreshAfterChange() {
    if (view === 'order' && MApp.reloadOrder) return MApp.reloadOrder();
    if (current) return openCustomer(current.id);
  }

  function findMeasurement(id) {
    for (var i = 0; i < current.measurements.length; i++) {
      if (current.measurements[i].id === id) return current.measurements[i];
    }
    return null;
  }

  // Edit / delete / status / open-order buttons on a list of measurement cards.
  function bindMeasurementList(container, lookup) {
    container.addEventListener('click', function (ev) {
      var btn = ev.target.closest('button[data-act]');
      if (!btn) return;
      var id = parseInt(btn.dataset.id, 10);
      if (btn.dataset.act === 'edit') {
        var m = lookup(id);
        if (m) openMeasurementModal(m);
      } else if (btn.dataset.act === 'open-order') {
        if (MApp.openOrder) MApp.openOrder(parseInt(btn.dataset.order, 10));
      } else if (btn.dataset.act === 'delete') {
        if (!window.confirm('Delete this measurement? This cannot be undone.')) return;
        api('DELETE', '/api/measurements/' + id).then(function () {
          say('Measurement deleted');
          loadCounts();
          return refreshAfterChange();
        }).catch(function (e) { say(e.message, true); });
      }
    });
    container.addEventListener('change', function (ev) {
      var sel = ev.target.closest('.m-status-select');
      if (!sel) return;
      if (view === 'order' && MApp.beforeStatusChange && !MApp.beforeStatusChange(sel.value)) {
        refreshAfterChange();     // put the dropdown back
        return;
      }
      api('PATCH', '/api/measurements/' + sel.dataset.id + '/status', { status: sel.value })
        .then(function () {
          say('Status updated');
          if (view === 'order') return refreshAfterChange();   // order status may have changed
        })
        .catch(function (e) { say(e.message, true); refreshAfterChange(); });
    });
  }

  // -------------------------------------------------------------------------
  // Wiring
  // -------------------------------------------------------------------------
  function init() {
    api('GET', '/api/measurements/meta').then(function (m) {
      meta = m;
      $('m-garment-pick').innerHTML = '<option value="">— Select garment —</option>' +
        m.garments.map(function (g) {
          return '<option value="' + g.type + '">' + esc(g.label) + '</option>';
        }).join('');
      switchTab('dashboard');
      loadCounts();
    }).catch(function (e) { say(e.message, true); });

    var tabButtons = document.querySelectorAll('.m-tab');
    for (var t = 0; t < tabButtons.length; t++) {
      tabButtons[t].addEventListener('click', function () { switchTab(this.dataset.tab); });
    }
    $('m-day-strip').addEventListener('click', function (ev) {
      var btn = ev.target.closest('.m-day');
      if (!btn) return;
      selectedDay = selectedDay === btn.dataset.day ? null : btn.dataset.day;
      renderDashboard();
    });
    // Any "brief" row (dashboard sections or day detail) opens that customer.
    $('m-tab-dashboard').addEventListener('click', function (ev) {
      var row = ev.target.closest('.m-brief');
      if (!row) return;
      if (row.dataset.order && MApp.openOrder) MApp.openOrder(parseInt(row.dataset.order, 10));
      else openCustomer(parseInt(row.dataset.customer, 10));
    });

    $('m-search').addEventListener('input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(loadCustomers, 250);
    });
    $('m-customer-list').addEventListener('click', function (ev) {
      var row = ev.target.closest('.m-customer-row');
      if (row) openCustomer(parseInt(row.dataset.id, 10));
    });
    $('m-back-btn').addEventListener('click', showList);
    $('m-new-customer-btn').addEventListener('click', function () { openCustomerModal(null); });
    $('m-edit-customer-btn').addEventListener('click', function () { openCustomerModal(current); });
    $('m-delete-customer-btn').addEventListener('click', deleteCustomer);
    $('m-c-save').addEventListener('click', saveCustomer);
    $('m-f-save').addEventListener('click', saveMeasurement);

    $('m-add-measurement-btn').addEventListener('click', function () {
      var type = $('m-garment-pick').value;
      if (!type) { say('Choose a garment first', true); return; }
      openMeasurementModal(null, type);
    });

    document.addEventListener('click', function (ev) {
      var closer = ev.target.closest('[data-close]');
      if (closer) closeModal(closer.dataset.close);
    });

    bindMeasurementList($('m-measurement-list'), findMeasurement);
  }

  MApp.$ = $; MApp.esc = esc; MApp.api = api; MApp.say = say; MApp.showErr = showErr;
  MApp.openModal = openModal; MApp.closeModal = closeModal;
  MApp.fmtDate = fmtDate; MApp.fmtMoney = fmtMoney;
  MApp.getMeta = function () { return meta; };
  MApp.garmentDef = garmentDef; MApp.fieldsHtml = fieldsHtml;
  MApp.showView = showView; MApp.getView = function () { return view; };
  MApp.showList = showList; MApp.switchTab = switchTab;
  MApp.openCustomer = openCustomer; MApp.openCustomerModal = openCustomerModal;
  MApp.getCurrent = function () { return current; };
  MApp.openMeasurementModal = openMeasurementModal;
  MApp.measurementCard = measurementCard; MApp.bindMeasurementList = bindMeasurementList;
  MApp.loadCounts = loadCounts; MApp.STATUS_BADGE = STATUS_BADGE;

  init();
})();
