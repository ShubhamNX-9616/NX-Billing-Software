/* ============================================================
   api.js — Centralised fetch wrappers for all Flask API calls
   All functions return parsed JSON or throw an Error.
   ============================================================ */

/**
 * Internal helper: fetch a URL and return parsed JSON.
 * Throws an Error (with server's error message if available)
 * on any non-2xx response.
 */
async function _apiFetch(url, options = {}) {
  const res = await fetch(url, options);
  let data;
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  if (!res.ok) {
    const msg = data.error || `HTTP ${res.status}: ${res.statusText}`;
    const err = new Error(msg);
    err.status = res.status;
    err.data   = data;
    throw err;
  }
  return data;
}

// ----------------------------------------------------------------
// Customers
// ----------------------------------------------------------------

/**
 * Search for an existing customer by mobile number.
 * Returns { found: true, customer: {...} } or { found: false }.
 */
async function searchCustomerByMobile(mobile) {
  const norm = (typeof normalizeMobile === 'function') ? normalizeMobile(mobile) : mobile;
  return _apiFetch(`/api/customers/search?mobile=${encodeURIComponent(norm || mobile)}`);
}

/**
 * Get all customers, with optional text search on name/mobile.
 * Returns array of customer objects.
 */
async function getAllCustomers(search = '') {
  const params = search ? `?search=${encodeURIComponent(search)}` : '';
  return _apiFetch(`/api/customers${params}`);
}

/**
 * Get a single customer by id.
 * Returns customer object or throws 404.
 */
async function getCustomer(id) {
  return _apiFetch(`/api/customers/${id}`);
}

/**
 * Get all bills for a specific customer (summary list).
 * Returns array of bill summary objects.
 */
async function getCustomerBills(id) {
  return _apiFetch(`/api/customers/${id}/bills`);
}

// ----------------------------------------------------------------
// Companies
// ----------------------------------------------------------------

/**
 * Get all companies for a given cloth type.
 * clothType: 'Shirting' | 'Suiting' | 'Readymade'
 * Returns array of company objects.
 */
async function getCompaniesByClothType(clothType) {
  return _apiFetch(`/api/companies?clothType=${encodeURIComponent(clothType)}`);
}

/**
 * Add a new company under a given cloth type.
 * Returns the created company object (201) or throws on duplicate (409).
 */
async function addCompany(clothType, name) {
  return _apiFetch('/api/companies', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ cloth_type: clothType, company_name: name }),
  });
}

// ----------------------------------------------------------------
// Bills
// ----------------------------------------------------------------

/**
 * Get bills with optional search filters.
 *
 * If any of billNumber / mobile / name are supplied, uses /api/bills/search.
 * If only a plain `search` string is given, uses /api/bills?search=.
 * If nothing is supplied, returns all bills from /api/bills.
 *
 * Options object (all optional):
 *   { search, billNumber, mobile, name }
 */
async function getBills({ search = '', billNumber = '', mobile = '', name = '' } = {}) {
  if (billNumber || mobile || name) {
    const params = new URLSearchParams();
    if (billNumber) params.set('billNumber', billNumber);
    if (mobile)     params.set('mobile', mobile);
    if (name)       params.set('name', name);
    return _apiFetch(`/api/bills/search?${params.toString()}`);
  }
  const params = search ? `?search=${encodeURIComponent(search)}` : '';
  return _apiFetch(`/api/bills${params}`);
}

/**
 * Get full details of a single bill (includes items[] and payments[]).
 */
async function getBill(id) {
  return _apiFetch(`/api/bills/${id}`);
}

/**
 * Create a new bill.
 * billData shape:
 * {
 *   customer_name, customer_mobile, bill_date, payment_mode_type,
 *   items: [{ cloth_type, company_name, quality_number, quantity,
 *             unit_label, mrp, discount_percent }],
 *   payments: [{ payment_method, amount }]
 * }
 * Returns the created bill summary object.
 */
async function saveBill(billData) {
  return _apiFetch('/api/bills', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(billData),
  });
}
