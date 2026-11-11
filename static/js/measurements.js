/* Measurements trial — page logic. Talks only to /api/measurements/*. */
(function () {
  'use strict';

  var meta = null;            // { statuses, garments, today }
  var current = null;         // customer currently open in the detail view
  var editingMeasurement = null;   // measurement being edited, or null when creating
  var editingCustomerId = null;    // customer being edited, or null when creating
  var searchTimer = null;

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
  function closeModal(id) { $(id).classList.add('hidden'); }

  function fmtDate(d) {
    if (!d) return '';
    var p = d.split('-');
    return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : d;
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
    $('m-view-detail').classList.add('hidden');
    $('m-view-list').classList.remove('hidden');
    loadCustomers();
    loadCounts();
  }

  function openCustomer(id) {
    return api('GET', '/api/measurements/customers/' + id).then(renderCustomer)
      .catch(function (e) { say(e.message, true); });
  }

  function renderCustomer(c) {
    current = c;
    $('m-view-list').classList.add('hidden');
    $('m-view-detail').classList.remove('hidden');
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
      '<div class="m-mcard-values">' + (chips || '<span class="m-empty">No values entered</span>') + '</div>' +
      (m.notes ? '<div class="m-mcard-dates" style="margin-top:8px;">Notes: ' + esc(m.notes) + '</div>' : '') +
      (m.image_url ? '<div style="margin-top:8px;"><img src="' + esc(m.image_url) +
        '" alt="Fabric photo" style="max-height:80px;border-radius:6px;"></div>' : '') +
      '<div class="m-mcard-foot">' +
        '<label class="m-status-wrap">Status ' +
          '<select class="input m-status-select" data-id="' + m.id + '">' + statusOpts + '</select></label>' +
        '<div class="m-card-actions">' +
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
    req.then(function (c) {
      closeModal('m-customer-modal');
      renderCustomer(c);
      say(editingCustomerId ? 'Customer updated' : 'Customer added');
      loadCounts();
    }).catch(function (e) {
      if (e.data && e.data.customer) {
        // Mobile already saved — jump to that customer instead of a dead end.
        closeModal('m-customer-modal');
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
  function renderFields(type, values) {
    var def = garmentDef(type);
    $('m-garment-title').textContent = def ? '— ' + def.label : '';
    $('m-fields').innerHTML = def ? def.fields.map(function (f) {
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

  function openMeasurementModal(measurement, garmentType) {
    editingMeasurement = measurement || null;
    var type = measurement ? measurement.garment_type : garmentType;
    var values = measurement ? measurement.values : {};
    var def = garmentDef(type);
    $('m-measurement-modal-title').textContent =
      (measurement ? 'Edit ' : 'New ') + (def ? def.label : '') + ' Measurement';
    $('m-measurement-modal').dataset.garment = type;
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
    var btn = $('m-f-save');
    btn.disabled = true;
    var req = editingMeasurement
      ? api('PUT', '/api/measurements/' + editingMeasurement.id, body)
      : api('POST', '/api/measurements/customers/' + current.id + '/measurements', body);

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
      return openCustomer(current.id);
    }).catch(function (e) {
      showErr('m-f-error', e.message);
      // The measurement itself may have saved even if the photo failed.
      if (current) openCustomer(current.id);
    }).then(function () { btn.disabled = false; });
  }

  function findMeasurement(id) {
    for (var i = 0; i < current.measurements.length; i++) {
      if (current.measurements[i].id === id) return current.measurements[i];
    }
    return null;
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
      loadCustomers();
      loadCounts();
    }).catch(function (e) { say(e.message, true); });

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

    $('m-measurement-list').addEventListener('click', function (ev) {
      var btn = ev.target.closest('button[data-act]');
      if (!btn) return;
      var id = parseInt(btn.dataset.id, 10);
      if (btn.dataset.act === 'edit') {
        var m = findMeasurement(id);
        if (m) openMeasurementModal(m);
      } else if (btn.dataset.act === 'delete') {
        if (!window.confirm('Delete this measurement? This cannot be undone.')) return;
        api('DELETE', '/api/measurements/' + id).then(function () {
          say('Measurement deleted');
          loadCounts();
          return openCustomer(current.id);
        }).catch(function (e) { say(e.message, true); });
      }
    });

    $('m-measurement-list').addEventListener('change', function (ev) {
      var sel = ev.target.closest('.m-status-select');
      if (!sel) return;
      api('PATCH', '/api/measurements/' + sel.dataset.id + '/status', { status: sel.value })
        .then(function () { say('Status updated'); })
        .catch(function (e) { say(e.message, true); openCustomer(current.id); });
    });
  }

  init();
})();
