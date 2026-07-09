/* common.js — shared helpers loaded on every page (via base.html) */

/**
 * Escape a value for safe interpolation into innerHTML template strings.
 * Use on any API/user-entered text (customer names, mobiles, etc.).
 */
function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* Some browsers/WebViews (seen on budget Android tablets) don't properly cap
   the year segment of <input type="date"> at 4 digits while typing, letting
   values like "20266-07-08" slip through. Truncate on every keystroke/change
   so no date field anywhere in the app can end up with a malformed year. */
document.addEventListener('input', clampDateInputYear, true);
document.addEventListener('change', clampDateInputYear, true);

function clampDateInputYear(e) {
  const el = e.target;
  if (!(el.tagName === 'INPUT' && el.type === 'date' && el.value)) return;
  const m = el.value.match(/^(\d+)-(\d{2})-(\d{2})$/);
  if (m && m[1].length > 4) {
    el.value = `${m[1].slice(0, 4)}-${m[2]}-${m[3]}`;
  }
}

/* Loyalty tier display maps — mirror TIERS in services/loyalty.py */
const TIER_CSS   = { silver: 'tier-silver', gold: 'tier-gold', platinum: 'tier-platinum', diamond: 'tier-diamond' };
const TIER_LABEL = { silver: 'Silver', gold: 'Gold', platinum: 'Platinum', diamond: 'Diamond' };
