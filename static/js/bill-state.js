/* ============================================================
   bill-state.js — Shared state, constants, and utilities
   Loaded first; all other bill-*.js files depend on this.
   ============================================================ */

// ---- Edit mode (set by edit_bill.html before this script loads) ----
const BILL_ID   = window.BILL_ID || null;
const EDIT_MODE = !!BILL_ID;

// ---- Global state ----
let rowCounter       = 0;
let savedBillId      = null;
let currentMode      = 'Cash';
let addCompanyCtx    = null;
let addClothTypeCtx  = null;
let salespersons     = [];
let comboLastChanged = null;
let clothTypes       = [];        // [{ id, type_name, has_company }, ...]
let activeItemIds    = [];        // ordered list of live item IDs
const itemDataStore  = {};        // { id: { lineTotal, discPerUnit, rateAfterDisc, discAmt, finalAmt, inventoryItemId } }
let lastIsMobile     = window.innerWidth <= 768;
let advancePaidUserModified = false;
let billSaved = false;  // set true on successful save to suppress beforeunload

// The new-bill form stays editable after a save, so anything typed afterwards
// is a pending change that still has to be pushed with a PUT. Until it is,
// the page is dirty again — see markPostSaveDirty() in bill-form.js.
let postSaveDirty = false;

// Staff may create bills but not update them (PUT /api/bills/<id> is
// admin-only), so the post-save re-edit flow is only offered to admins.
// Set by the page template; defaults to allowed for the admin-only edit page.
const CAN_UPDATE_BILLS = window.CAN_UPDATE_BILLS !== false;

// ---- Unsaved-changes guard ----
function isBillDirty() {
  if (postSaveDirty) return true;   // edited after saving, never sent
  if (billSaved) return false;
  const mobile = (document.getElementById('customer-mobile')?.value || '').trim();
  const name   = (document.getElementById('customer-name')?.value   || '').trim();
  if (mobile.length > 0 || name.length > 0) return true;
  return activeItemIds.some(id => {
    const qty = (document.getElementById(`qty-${id}`)?.value || '').trim();
    const mrp = (document.getElementById(`mrp-${id}`)?.value || '').trim();
    return qty !== '' || mrp !== '';
  });
}

window.addEventListener('beforeunload', e => {
  if (isBillDirty()) {
    e.preventDefault();
    e.returnValue = '';
  }
});

// QR scanner state
let html5QrScanner  = null;
let qrScanLock      = false;   // prevents duplicate scans of the same code

const companyCache = {};          // { clothType: [company, ...] }
const clothChangeGen = {};        // { rowId: latestGenerationNumber } — used to cancel stale onClothChangeRestoring calls

// ---- Utilities ----
function fmt(amount) {
  return Number(amount || 0).toLocaleString('en-IN', {
    style: 'currency', currency: 'INR',
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

// Round-half-up to 2dp, matching the server's r2() (utils.py) bit-for-bit.
// Multiplying by 100 first (the old `Math.round((n+EPSILON)*100)/100` approach)
// can itself introduce a fresh float error that flips a value already just
// under a .xx5 boundary to appear exactly on it — e.g. 715.5*1.15 is really
// 822.8249999999999, but *100 rounds that up to exactly 82282.5, which then
// rounds to 822.83 instead of the correct 822.82 (bill #527). Working from
// the number's own decimal string — the same shortest round-trip
// representation Python's str(float) produces — avoids that second error.
function round2(n) {
  if (typeof n !== 'number' || !isFinite(n)) return n;
  const neg = n < 0;
  const s = Math.abs(n).toString();
  if (s.includes('e') || s.includes('E')) {
    return Math.round(n * 100) / 100;   // currency amounts never reach this magnitude
  }
  const dot = s.indexOf('.');
  const intPart  = dot === -1 ? s : s.slice(0, dot);
  const fracPart = dot === -1 ? '' : s.slice(dot + 1);
  const digits = (fracPart + '000').slice(0, 3);   // pad so a 3rd decimal digit always exists
  let cents = parseInt(intPart, 10) * 100 + parseInt(digits.slice(0, 2), 10);
  if (digits.charCodeAt(2) - 48 >= 5) cents += 1;  // round half up on the 3rd decimal digit
  const result = cents / 100;
  return neg ? -result : result;
}

function todayISO() {
  return istToday();  // IST calendar day, independent of operator timezone
}

function normalizeMobile(raw) {
  let digits = (raw || '').replace(/\D/g, '');
  if (digits.startsWith('91') && digits.length === 12) digits = digits.slice(2);
  if (digits.startsWith('0')  && digits.length === 11) digits = digits.slice(1);
  return digits;
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function isMobile() {
  return window.innerWidth <= 768;
}
