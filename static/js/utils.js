/* ============================================================
   utils.js — Shared utility functions
   ============================================================ */

/**
 * Format a number as Indian Rupees.
 * e.g. 1234.5 → "₹1,234.50"
 */
function formatCurrency(amount) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(amount) || 0);
}

/**
 * Normalize a raw mobile string:
 *   - Remove spaces, dashes, dots
 *   - Strip leading +91 or 91 (when total becomes 12 digits)
 *   - Strip leading 0 (when total becomes 11 digits)
 * Returns a 10-digit string, or null if the result is not 10 digits.
 */
function normalizeMobile(input) {
  if (!input) return null;
  let digits = String(input).replace(/[\s\-\.]/g, '').replace(/\D/g, '');
  if (digits.startsWith('91') && digits.length === 12) digits = digits.slice(2);
  if (digits.startsWith('0')  && digits.length === 11) digits = digits.slice(1);
  return digits.length === 10 ? digits : null;
}

/**
 * Returns true if the input normalises to a valid 10-digit Indian mobile.
 */
function validateMobile(input) {
  const norm = normalizeMobile(input);
  return norm !== null && /^[6-9]\d{9}$/.test(norm);
}

/**
 * Standard debounce — returns a function that delays invoking fn
 * until after `delay` ms have elapsed since the last call.
 */
function debounce(fn, delay) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

/**
 * Convert YYYY-MM-DD → DD/MM/YYYY.
 * Returns '—' for empty/invalid input.
 */
function formatDate(dateStr) {
  if (!dateStr) return '—';
  const parts = String(dateStr).split('-');
  if (parts.length !== 3) return dateStr;
  const [y, m, d] = parts;
  return `${d}/${m}/${y}`;
}

/**
 * Show a temporary floating alert that auto-dismisses after 3 seconds.
 * type: 'success' | 'danger' | 'warning'
 */
function showAlert(message, type = 'success') {
  // Remove any existing auto-alert
  const existing = document.getElementById('__auto-alert__');
  if (existing) existing.remove();

  const div = document.createElement('div');
  div.id = '__auto-alert__';
  div.className = `alert alert-${type}`;
  div.style.cssText = `
    position: fixed;
    top: 16px;
    right: 16px;
    z-index: 9999;
    min-width: 260px;
    max-width: 400px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.15);
    animation: fadeInDown .2s ease;
  `;
  div.textContent = message;

  // Add fadeInDown keyframes once
  if (!document.getElementById('__alert-style__')) {
    const style = document.createElement('style');
    style.id = '__alert-style__';
    style.textContent = `
      @keyframes fadeInDown {
        from { opacity: 0; transform: translateY(-12px); }
        to   { opacity: 1; transform: translateY(0); }
      }
    `;
    document.head.appendChild(style);
  }

  document.body.appendChild(div);
  setTimeout(() => { div.style.opacity = '0'; div.style.transition = 'opacity .4s'; }, 2600);
  setTimeout(() => div.remove(), 3000);
}

/**
 * Show / hide a full-page loading overlay.
 * Creates the overlay on first call.
 */
function showSpinner() {
  let overlay = document.getElementById('__global-spinner__');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = '__global-spinner__';
    overlay.style.cssText = `
      position: fixed; inset: 0;
      background: rgba(255,255,255,0.65);
      display: flex; align-items: center; justify-content: center;
      z-index: 9998;
    `;
    overlay.innerHTML = '<div class="spinner spinner-lg"></div>';
    document.body.appendChild(overlay);
  }
  overlay.style.display = 'flex';
}

function hideSpinner() {
  const overlay = document.getElementById('__global-spinner__');
  if (overlay) overlay.style.display = 'none';
}

/**
 * Round a number to exactly 2 decimal places using
 * the "round half away from zero" approach.
 */
function roundTo2(num) {
  return Math.round((Number(num) + Number.EPSILON) * 100) / 100;
}
