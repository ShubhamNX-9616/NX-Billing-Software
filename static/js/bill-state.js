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

// ---- Unsaved-changes guard ----
function isBillDirty() {
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

// ---- Utilities ----
function fmt(amount) {
  return Number(amount || 0).toLocaleString('en-IN', {
    style: 'currency', currency: 'INR',
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

function round2(n) {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

function getRoundedTotals(amount) {
  const grossFinal = round2(amount);
  const netPayable = Math.floor(grossFinal);
  const roundOff = round2(grossFinal - netPayable);
  return { grossFinal, roundOff, netPayable };
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
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
