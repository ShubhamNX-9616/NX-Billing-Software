/* ============================================================
   inventory-scan.js — Inventory page - AI invoice photo scan and its review flow.
   Part of the Inventory page; shares globals with inventory.js (load order matters:
   see inventory.html). Code moved here unchanged from the old single inventory.js.
   ============================================================ */

// ----------------------------------------------------------------
// Invoice photo scan — AI auto-fill
// ----------------------------------------------------------------
let _scanItems = [];   // all items from scan (with user edits stored back)
let _scanIndex = 0;    // index of item currently shown (0-based)
let _scanMeta  = {};   // invoice-level data

// Save whatever the user typed in the form back into _scanItems[_scanIndex]
function _saveCurrentItemEdits() {
  if (!_scanItems.length || _scanIndex < 0) return;
  const idx = _scanIndex;
  if (idx >= _scanItems.length) return;
  _scanItems[idx] = Object.assign({}, _scanItems[idx], {
    item_name:      document.getElementById('ai-item-name').value.trim(),
    quality_number: document.getElementById('ai-quality').value.trim(),
    shade_number:   document.getElementById('ai-shade').value.trim(),
    opening_stock:  parseFloat(document.getElementById('ai-opening').value) || 0,
    unit_label:     document.getElementById('ai-unit').value,
    notes:          document.getElementById('ai-notes').value.trim(),
    mrp:            parseFloat(document.getElementById('ai-mrp').value) || 0,
    cost_price:     parseFloat(document.getElementById('ai-cp').value) || 0,
    min_stock_alert: parseFloat(document.getElementById('ai-alert').value) || 2,
  });
}

// Match a select option by comparing option text (case-insensitive, partial)
function _matchSelectByText(selectId, text) {
  if (!text) return false;
  const sel   = document.getElementById(selectId);
  const lower = text.trim().toLowerCase();
  let bestOpt = null, bestScore = 0;
  for (const opt of sel.options) {
    if (!opt.value || opt.value === '__add__') continue;
    const optText = opt.textContent.toLowerCase();
    if (optText === lower) { bestOpt = opt; break; }
    if (optText.includes(lower) || lower.includes(optText)) {
      const score = Math.min(optText.length, lower.length);
      if (score > bestScore) { bestScore = score; bestOpt = opt; }
    }
  }
  if (bestOpt) { sel.value = bestOpt.value; return true; }
  return false;
}

async function _fillInvoiceLevelFields(meta) {
  let supplierId = null;
  if (meta.supplier_name) {
    if (_matchSelectByText('ai-supplier', meta.supplier_name)) {
      supplierId = document.getElementById('ai-supplier').value || null;
      onAiSupplierChange();
    }
  }
  if (meta.invoice_number) {
    const found = _matchSelectByText('ai-invoice', meta.invoice_number);
    if (!found) {
      try {
        const res = await fetch('/api/invoices', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            invoice_number: meta.invoice_number,
            invoice_date:   meta.invoice_date || new Date().toISOString().slice(0, 10),
            supplier_id:    supplierId ? parseInt(supplierId) : null,
          }),
        });
        const inv = await res.json();
        if (res.ok) await loadInvoicesForSelect(inv.id);
      } catch (_) {}
    }
    onAiInvoiceChange();
  }
  if (meta.cloth_type) {
    if (_matchSelectByText('ai-cloth', meta.cloth_type)) {
      const clothVal = document.getElementById('ai-cloth').value;
      if (clothVal && clothVal !== '__add__') {
        await loadCompaniesForSelect(clothVal);
        if (meta.company_name) _matchSelectByText('ai-company', meta.company_name);
      }
    }
  } else if (meta.company_name) {
    _matchSelectByText('ai-company', meta.company_name);
  }
}

// Fill form fields from item object (does NOT change invoice-level selects)
function _renderItem(item) {
  document.getElementById('ai-item-name').value = item.item_name      || '';
  document.getElementById('ai-quality').value   = item.quality_number || '';
  document.getElementById('ai-shade').value     = item.shade_number   || '';
  document.getElementById('ai-notes').value     = item.notes          || '';
  document.getElementById('ai-opening').value   = item.opening_stock  != null ? item.opening_stock : '';
  document.getElementById('ai-unit').value      = item.unit_label     || 'm';
  document.getElementById('ai-mrp').value       = item.mrp            || '';
  document.getElementById('ai-cp').value        = item.cost_price     || '';
  document.getElementById('ai-alert').value     = item.min_stock_alert || 2;
  updateAiSpecialCode();
}

function _updateScanButtons() {
  const nav        = document.getElementById('scan-nav');
  const prevBtn    = document.getElementById('btn-scan-prev');
  const nextBtn    = document.getElementById('btn-scan-next');
  const counter    = document.getElementById('scan-nav-counter');
  const saveAllBtn = document.getElementById('btn-ai-save-all');
  const saveBtn    = document.getElementById('btn-ai-save');
  const total      = _scanItems.length;

  if (total === 0) {
    nav.style.display       = 'none';
    saveAllBtn.style.display = 'none';
    saveBtn.style.display    = '';
    return;
  }

  // Scan flow: bottom nav replaces the single Save Item button
  nav.style.display    = 'flex';
  saveBtn.style.display = 'none';
  counter.textContent  = `Item ${_scanIndex + 1} of ${total}`;
  prevBtn.style.display = _scanIndex > 0 ? '' : 'none';

  const isLast = _scanIndex >= total - 1;
  nextBtn.style.display    = isLast ? 'none' : '';
  saveAllBtn.style.display = isLast ? '' : 'none';
  if (isLast) saveAllBtn.textContent = `Save All ${total} Items`;
}

// Header "Scan Invoice" button — opens the file picker
function startInvoiceScan() {
  document.getElementById('scan-invoice-input').click();
}

// Next button clicked (bottom of the form)
function handleNextScanItem() {
  if (_scanIndex >= _scanItems.length - 1) return;
  _saveCurrentItemEdits();
  _scanIndex++;
  _renderItem(_scanItems[_scanIndex]);
  _updateScanButtons();
}

// Prev button clicked
function handlePrevScanItem() {
  if (_scanIndex <= 0) return;
  _saveCurrentItemEdits();
  _scanIndex--;
  _renderItem(_scanItems[_scanIndex]);
  _updateScanButtons();
}

function resetScanState() {
  _scanItems = [];
  _scanIndex = 0;
  _scanMeta  = {};
  const nav        = document.getElementById('scan-nav');
  const saveAllBtn = document.getElementById('btn-ai-save-all');
  const saveBtn    = document.getElementById('btn-ai-save');
  if (nav)        nav.style.display = 'none';
  if (saveAllBtn) saveAllBtn.style.display = 'none';
  if (saveBtn)    saveBtn.style.display    = '';
}

async function scanInvoiceImage(input) {
  if (!input.files || !input.files[0]) return;
  const btn = document.getElementById('btn-scan-invoice');
  const btnHtml = btn.innerHTML;
  btn.disabled    = true;
  btn.textContent = 'Scanning…';
  try {
    const fd = new FormData();
    fd.append('image', input.files[0]);
    const res  = await fetch('/api/inventory/scan-invoice', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) {
      alert('Scan failed: ' + (data.error || 'Unknown error') + (data.raw ? '\n\nRaw:\n' + data.raw : ''));
      return;
    }
    _scanMeta  = { supplier_name: data.supplier_name, invoice_number: data.invoice_number,
                   invoice_date: data.invoice_date, cloth_type: data.cloth_type,
                   company_name: data.company_name };
    _scanItems = (data.items && data.items.length) ? data.items : [data];
    _scanIndex = 0;
    await _fillInvoiceLevelFields(_scanMeta);
    _renderItem(_scanItems[0]);
    _updateScanButtons();
  } catch (e) {
    alert('Network error: ' + e.message);
  } finally {
    input.value   = '';
    btn.disabled  = false;
    btn.innerHTML = btnHtml;
  }
}
