/* ============================================================
   bill-modals.js — Add Company, Cloth Type, Salesperson modals
   Depends on: bill-state.js, bill-items.js
   ============================================================ */

// ---- Salespersons ----
async function loadSalespersons() {
  const select = document.getElementById('salesperson-name');
  if (!select) return;
  try {
    const res = await fetch('/api/salespersons');
    salespersons = await res.json();
  } catch {
    salespersons = [{ name: 'Self' }, { name: 'Geetesh' }];
  }
  renderSalespersonOptions('Self');
}

function renderSalespersonOptions(selectedName = '') {
  const select = document.getElementById('salesperson-name');
  if (!select) return;
  const options = salespersons.map(sp =>
    `<option value="${sp.name}"${sp.name === selectedName ? ' selected' : ''}>${sp.name}</option>`
  ).join('');
  select.innerHTML = `<option value="">-- Select --</option>${options}`;
  if (selectedName) select.value = selectedName;
}

// ---- Add Company modal ----
function openAddCompanyModal(rowId) {
  const clothType = document.getElementById(`cloth-${rowId}`).value;
  addCompanyCtx   = { rowId, clothType };
  document.getElementById('add-company-title').textContent = `Add Company — ${clothType}`;
  document.getElementById('add-company-name').value        = '';
  document.getElementById('add-company-error').textContent = '';
  document.getElementById('add-company-modal').classList.remove('hidden');
  document.getElementById('add-company-name').focus();
}

function closeAddCompanyModal() {
  document.getElementById('add-company-modal').classList.add('hidden');
  addCompanyCtx = null;
}

async function saveNewCompany() {
  if (!addCompanyCtx) return;
  const { rowId, clothType } = addCompanyCtx;
  const nameVal = document.getElementById('add-company-name').value.trim();
  const errEl   = document.getElementById('add-company-error');
  const saveBtn = document.getElementById('btn-add-company-save');

  errEl.textContent = '';
  if (!nameVal) { errEl.textContent = 'Company name is required.'; return; }

  saveBtn.disabled    = true;
  saveBtn.textContent = 'Saving…';

  try {
    const res  = await fetch('/api/companies', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ cloth_type: clothType, company_name: nameVal }),
    });
    const data = await res.json();

    if (res.status === 409) { errEl.textContent = 'Company already exists under this cloth type.'; return; }
    if (!res.ok)            { errEl.textContent = data.error || 'Failed to save company.'; return; }

    invalidateCompanyCache(clothType);
    const list    = await fetchCompanies(clothType);
    const compSel = document.getElementById(`company-${rowId}`);
    rebuildCompanySelect(compSel, list, nameVal);
    closeAddCompanyModal();
  } catch (err) {
    errEl.textContent = 'Network error: ' + err.message;
  } finally {
    saveBtn.disabled    = false;
    saveBtn.textContent = 'Save Company';
  }
}

document.getElementById('add-company-modal').addEventListener('click', function (e) {
  if (e.target === this) closeAddCompanyModal();
});
document.getElementById('add-company-name').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') saveNewCompany();
});

// ---- Add Cloth Type modal ----
function openAddClothTypeModal(rowId) {
  addClothTypeCtx = { rowId };
  document.getElementById('add-cloth-type-name').value        = '';
  document.getElementById('add-cloth-type-error').textContent = '';
  document.getElementById('add-cloth-type-modal').classList.remove('hidden');
  document.getElementById('add-cloth-type-name').focus();
}

function closeAddClothTypeModal() {
  document.getElementById('add-cloth-type-modal').classList.add('hidden');
  addClothTypeCtx = null;
}

function refreshAllClothSelects() {
  activeItemIds.forEach(id => {
    const sel = document.getElementById(`cloth-${id}`);
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML    = buildClothOptions(cur);
    sel.dataset.prev = cur;
  });
}

async function saveNewClothType() {
  if (!addClothTypeCtx) return;
  const { rowId } = addClothTypeCtx;
  const nameVal = document.getElementById('add-cloth-type-name').value.trim();
  const errEl   = document.getElementById('add-cloth-type-error');
  const saveBtn = document.getElementById('btn-add-cloth-type-save');

  errEl.textContent = '';
  if (!nameVal) { errEl.textContent = 'Cloth type name is required.'; return; }

  saveBtn.disabled    = true;
  saveBtn.textContent = 'Saving…';

  try {
    const res  = await fetch('/api/cloth-types', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ type_name: nameVal }),
    });
    const data = await res.json();

    if (res.status === 409) { errEl.textContent = 'Cloth type already exists.'; return; }
    if (!res.ok)            { errEl.textContent = data.error || 'Failed to save cloth type.'; return; }

    clothTypes.push({ id: data.id, type_name: data.type_name, has_company: data.has_company });
    refreshAllClothSelects();

    const sel = document.getElementById(`cloth-${rowId}`);
    if (sel) {
      sel.value        = data.type_name;
      sel.dataset.prev = data.type_name;
    }
    closeAddClothTypeModal();
    await onClothChangeRestoring(rowId, data.type_name, '');
  } catch (err) {
    errEl.textContent = 'Network error: ' + err.message;
  } finally {
    saveBtn.disabled    = false;
    saveBtn.textContent = 'Save';
  }
}

document.getElementById('add-cloth-type-modal').addEventListener('click', function (e) {
  if (e.target === this) closeAddClothTypeModal();
});
document.getElementById('add-cloth-type-name').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') saveNewClothType();
});

// ---- Add Salesperson modal ----
function openAddSalespersonModal() {
  document.getElementById('add-salesperson-name').value = '';
  document.getElementById('add-salesperson-error').textContent = '';
  document.getElementById('add-salesperson-modal').classList.remove('hidden');
  document.getElementById('add-salesperson-name').focus();
}

function closeAddSalespersonModal() {
  document.getElementById('add-salesperson-modal').classList.add('hidden');
}

async function saveNewSalesperson() {
  const nameVal = document.getElementById('add-salesperson-name').value.trim();
  const errEl = document.getElementById('add-salesperson-error');
  const saveBtn = document.getElementById('btn-add-salesperson-save');

  errEl.textContent = '';
  if (!nameVal) {
    errEl.textContent = 'Sales person name is required.';
    return;
  }

  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving...';
  try {
    const res = await fetch('/api/salespersons', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: nameVal }),
    });
    const data = await res.json();
    if (res.status === 409) {
      errEl.textContent = 'Sales person already exists.';
      return;
    }
    if (!res.ok) {
      errEl.textContent = data.error || 'Failed to save sales person.';
      return;
    }
    salespersons.push({ id: data.id, name: data.name });
    salespersons.sort((a, b) => a.name.localeCompare(b.name));
    renderSalespersonOptions(data.name);
    closeAddSalespersonModal();
  } catch (err) {
    errEl.textContent = 'Network error: ' + err.message;
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save';
  }
}

document.getElementById('add-salesperson-modal').addEventListener('click', function (e) {
  if (e.target === this) closeAddSalespersonModal();
});
document.getElementById('add-salesperson-name').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') saveNewSalesperson();
});
