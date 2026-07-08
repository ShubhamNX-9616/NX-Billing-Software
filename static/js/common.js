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

/* Loyalty tier display maps — mirror TIERS in services/loyalty.py */
const TIER_CSS   = { silver: 'tier-silver', gold: 'tier-gold', platinum: 'tier-platinum', diamond: 'tier-diamond' };
const TIER_LABEL = { silver: 'Silver', gold: 'Gold', platinum: 'Platinum', diamond: 'Diamond' };
