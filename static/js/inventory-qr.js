/* ============================================================
   inventory-qr.js — Inventory page - QR codes: the current-stock QR sheet and the single-item QR view.
   Part of the Inventory page; shares globals with inventory.js (load order matters:
   see inventory.html). Code moved here unchanged from the old single inventory.js.
   ============================================================ */

// ----------------------------------------------------------------
// CS QR modal — group-based (cloth type + company per group)
// ----------------------------------------------------------------
function addCsGroup(preCloth, preCompany) {
  const gid = ++csGroupCounter;
  csRowCounters[gid] = 0;

  const container = document.getElementById('cs-groups');
  const div = document.createElement('div');
  div.id = `cs-group-${gid}`;
  div.className = 'cs-group';
  div.style.cssText = 'border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:14px;';

  const removeBtn = gid > 1
    ? `<button type="button" class="btn btn-sm" style="color:var(--danger);margin-left:auto;" onclick="removeCsGroup(${gid})">Remove Group</button>`
    : '';

  div.innerHTML = `
    <div style="display:flex;gap:10px;align-items:flex-end;margin-bottom:12px;flex-wrap:wrap;">
      <div style="flex:1;min-width:140px;">
        <label style="font-size:12px;font-weight:600;">Cloth Type <span class="text-danger">*</span></label>
        <select id="cs-cloth-${gid}" class="input select" style="margin-top:4px;" onchange="onCsGroupClothChange(${gid})">
          <option value="">— Select —</option>
        </select>
      </div>
      <div style="flex:1;min-width:140px;">
        <label style="font-size:12px;font-weight:600;">Company</label>
        <select id="cs-company-${gid}" class="input select" style="margin-top:4px;" onchange="onCsCompanyChange(${gid})">
          <option value="">— Select cloth type first —</option>
        </select>
        <div id="cs-company-add-row-${gid}" style="display:none;margin-top:6px;">
          <div style="display:flex;gap:6px;align-items:center;">
            <input type="text" id="cs-company-new-${gid}" class="input" placeholder="New company name" style="flex:1;" />
            <button type="button" class="btn btn-sm btn-primary" onclick="saveCsNewCompany(${gid})">Add</button>
            <button type="button" class="btn btn-sm btn-secondary" onclick="cancelCsCompanyAdd(${gid})" title="Cancel" aria-label="Cancel"><svg class="ico" aria-hidden="true"><use href="#i-x"/></svg></button>
          </div>
        </div>
      </div>
      <div style="min-width:70px;">
        <label style="font-size:12px;font-weight:600;">Unit</label>
        <select id="cs-unit-${gid}" class="input select" style="margin-top:4px;width:75px;">
          <option value="m">m</option>
          <option value="pcs">pcs</option>
        </select>
      </div>
      ${removeBtn}
    </div>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;min-width:520px;">
        <thead>
          <tr style="border-bottom:2px solid var(--border);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.4px;">
            <th style="padding:4px 6px;text-align:left;min-width:110px;">Item Name</th>
            <th style="padding:4px 6px;text-align:left;min-width:80px;">Shade No.</th>
            <th style="padding:4px 6px;text-align:left;min-width:80px;">Quality No.</th>
            <th style="padding:4px 6px;text-align:right;min-width:75px;">MRP (&#8377;)</th>
            <th style="padding:4px 6px;text-align:right;min-width:65px;">Stock</th>
            <th style="padding:4px 6px;text-align:left;min-width:90px;">Notes</th>
            <th style="width:28px;"></th>
          </tr>
        </thead>
        <tbody id="cs-tbody-${gid}"></tbody>
      </table>
    </div>
    <button type="button" class="btn btn-secondary btn-sm" onclick="addCsRow(${gid})" style="margin-top:8px;">&#43; Add Row</button>
  `;

  container.appendChild(div);
  populateClothTypeSelect(`cs-cloth-${gid}`, preCloth || '');
  if (preCloth && preCompany) populateCompanySelect(`cs-company-${gid}`, preCloth, preCompany);
  addCsRow(gid);
}

function removeCsGroup(gid) {
  const el = document.getElementById(`cs-group-${gid}`);
  if (el) el.remove();
}

function addCsRow(gid) {
  const rowId = ++csRowCounters[gid];
  const tbody = document.getElementById(`cs-tbody-${gid}`);
  if (!tbody) return;

  const s  = 'width:100%;padding:4px 6px;border:1px solid var(--border);border-radius:4px;background:var(--surface);color:var(--text);font-size:13px;box-sizing:border-box;';
  const sr = s + 'text-align:right;';

  const tr = document.createElement('tr');
  tr.id = `cs-row-${gid}-${rowId}`;
  tr.style.borderBottom = '1px solid var(--border)';
  tr.innerHTML = `
    <td style="padding:3px 4px;"><input type="text"   style="${s}"  placeholder="Item name" /></td>
    <td style="padding:3px 4px;"><input type="text"   style="${s}"  placeholder="Shade no." /></td>
    <td style="padding:3px 4px;"><input type="text"   style="${s}"  placeholder="Quality no." /></td>
    <td style="padding:3px 4px;"><input type="number" style="${sr}" placeholder="0.00" min="0" step="0.01" /></td>
    <td style="padding:3px 4px;"><input type="number" style="${sr}" placeholder="0"    min="0" step="0.01" /></td>
    <td style="padding:3px 4px;"><input type="text"   style="${s}"  placeholder="Optional" /></td>
    <td style="padding:3px 4px;text-align:center;">
      <button type="button" style="background:none;border:none;cursor:pointer;color:var(--danger);display:inline-flex;align-items:center;" onclick="removeCsRow(${gid},${rowId})" aria-label="Remove row"><svg class="ico" aria-hidden="true"><use href="#i-x"/></svg></button>
    </td>
  `;
  tbody.appendChild(tr);
  tr.querySelector('input').focus();
}

function removeCsRow(gid, rowId) {
  const el = document.getElementById(`cs-row-${gid}-${rowId}`);
  if (el) el.remove();
}

async function onCsGroupClothChange(gid) {
  const clothType = document.getElementById(`cs-cloth-${gid}`).value;
  const unitSel   = document.getElementById(`cs-unit-${gid}`);
  if (clothType === 'Shirting' || clothType === 'Suiting') {
    unitSel.value = 'm';
  } else if (clothType && clothType !== '__add__') {
    unitSel.value = 'pcs';
  }
  cancelCsCompanyAdd(gid);
  if (!clothType || clothType === '__add__') {
    document.getElementById(`cs-company-${gid}`).innerHTML = '<option value="">— Select cloth type first —</option>';
    return;
  }
  await populateCompanySelect(`cs-company-${gid}`, clothType, '');
}

function onCsCompanyChange(gid) {
  const sel    = document.getElementById(`cs-company-${gid}`);
  const addRow = document.getElementById(`cs-company-add-row-${gid}`);
  if (sel.value === '__add__') {
    addRow.style.display = '';
    document.getElementById(`cs-company-new-${gid}`).focus();
  } else {
    addRow.style.display = 'none';
  }
}

async function saveCsNewCompany(gid) {
  const cloth = document.getElementById(`cs-cloth-${gid}`).value;
  const input = document.getElementById(`cs-company-new-${gid}`);
  const name  = input.value.trim();
  if (!cloth || cloth === '__add__') { alert('Select a cloth type first.'); return; }
  if (!name) { input.focus(); return; }
  try {
    const res  = await fetch('/api/companies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cloth_type: cloth, company_name: name }),
    });
    const data = await res.json();
    if (!res.ok) { alert(data.error || 'Failed to add company.'); return; }
    input.value = '';
    document.getElementById(`cs-company-add-row-${gid}`).style.display = 'none';
    await populateCompanySelect(`cs-company-${gid}`, cloth, data.company_name);
  } catch (e) { alert('Network error: ' + e.message); }
}

function cancelCsCompanyAdd(gid) {
  const input  = document.getElementById(`cs-company-new-${gid}`);
  const addRow = document.getElementById(`cs-company-add-row-${gid}`);
  if (input)  input.value = '';
  if (addRow) addRow.style.display = 'none';
  const sel = document.getElementById(`cs-company-${gid}`);
  if (sel && sel.value === '__add__') sel.value = '';
}

// ----------------------------------------------------------------
// QR View Modal (Inventory QR)
// ----------------------------------------------------------------
function openQrViewModal(id) {
  const item = allItems.find(i => i.id === id);
  if (!item) return;
  const url = `/api/inventory/${id}/qr`;
  const bustUrl = `${url}?t=${Date.now()}`;
  document.getElementById('qr-view-title').textContent =
    `Label — ${item.item_code || '#' + id}`;
  document.getElementById('qr-view-img').src = bustUrl;
  document.getElementById('qr-download-link').href = bustUrl;
  document.getElementById('qr-download-link').download = `label-${item.item_code || id}.png`;
  document.getElementById('qr-view-modal').classList.remove('hidden');
}

function closeQrViewModal() {
  document.getElementById('qr-view-modal').classList.add('hidden');
}

document.getElementById('qr-view-modal').addEventListener('click', function(e) {
  if (e.target === this) closeQrViewModal();
});

// ----------------------------------------------------------------
// Current Stock QR Modal
// ----------------------------------------------------------------
function openCurrentStockQrModal() {
  csGroupCounter = 0;
  csRowCounters  = {};
  document.getElementById('cs-groups').innerHTML = '';
  document.getElementById('cs-error').textContent = '';
  document.getElementById('cs-qr-results').style.display = 'none';
  document.getElementById('cs-qr-results-grid').innerHTML = '';
  document.getElementById('cs-qr-modal').classList.remove('hidden');
  addCsGroup();
}

function closeCsQrModal() {
  document.getElementById('cs-qr-modal').classList.add('hidden');
}

async function generateCsQr() {
  const errEl = document.getElementById('cs-error');
  const btn   = document.getElementById('btn-cs-generate');
  errEl.textContent = '';
  document.getElementById('cs-qr-results').style.display = 'none';
  document.getElementById('cs-qr-results-grid').innerHTML = '';

  const items = [];
  for (const groupEl of document.querySelectorAll('.cs-group')) {
    const gid       = groupEl.id.replace('cs-group-', '');
    const clothType = document.getElementById(`cs-cloth-${gid}`).value;
    const company   = document.getElementById(`cs-company-${gid}`).value;
    const unit      = document.getElementById(`cs-unit-${gid}`).value;

    if (!clothType || clothType === '__add__') { errEl.textContent = 'Select a cloth type for every group.'; return; }

    for (const tr of document.querySelectorAll(`#cs-tbody-${gid} tr`)) {
      const inp = tr.querySelectorAll('input');
      const item_name      = inp[0].value.trim();
      const shade_number   = inp[1].value.trim();
      const quality_number = inp[2].value.trim();
      const mrp            = parseFloat(inp[3].value) || 0;
      const opening_stock  = parseFloat(inp[4].value) || 0;
      const notes          = inp[5].value.trim();
      if (!item_name && !shade_number && !quality_number && !mrp) continue;
      items.push({
        cloth_type:     clothType,
        company_name:   (company && company !== '__add__') ? company : '',
        quality_number, mrp, opening_stock, unit_label: unit,
        item_name, shade_number, notes,
      });
    }
  }

  if (!items.length) { errEl.textContent = 'Add at least one item row with some data.'; return; }

  btn.disabled = true;
  const resultsGrid = document.getElementById('cs-qr-results-grid');
  let successCount = 0;

  try {
    for (const item of items) {
      try {
        const res = await fetch('/api/inventory/current-stock-qr', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(item),
        });
        if (!res.ok) {
          const label = item.item_name || item.quality_number || item.cloth_type;
          errEl.textContent = `Failed to generate QR for "${label}".`;
          continue;
        }
        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        const label = [item.cloth_type, item.company_name, item.item_name, item.quality_number].filter(Boolean).join(' / ');
        const fname = label.replace(/\s*\/\s*/g, '-').replace(/\s+/g, '_');

        const card = document.createElement('div');
        card.style.cssText = 'text-align:center;border:1px solid var(--border);border-radius:8px;padding:12px;';
        card.innerHTML = `
          <img src="${url}" alt="QR" style="width:160px;height:160px;border-radius:4px;" />
          <div style="font-size:11px;color:var(--text-muted);margin-top:6px;word-break:break-word;">${esc(label)}</div>
          <a href="${url}" download="${esc(fname)}.png" class="btn btn-sm btn-primary" style="margin-top:6px;display:inline-block;">&#8595; Download</a>
        `;
        resultsGrid.appendChild(card);
        successCount++;
      } catch (itemErr) {
        errEl.textContent = 'Error: ' + itemErr.message;
      }
    }

    if (successCount > 0) {
      document.getElementById('cs-qr-results').style.display = '';
      await loadInventory();
    }
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('cs-qr-modal').addEventListener('click', function(e) {
  if (e.target === this) closeCsQrModal();
});

