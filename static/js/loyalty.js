/* loyalty.js — Loyalty program admin page (settings, cycle, pending gifts) */
/* TIER_CSS / TIER_LABEL / escapeHtml come from common.js */

document.addEventListener('DOMContentLoaded', () => {
  loadLoyaltySettings();
  loadPendingGifts();
});

async function loadLoyaltySettings() {
  const badge = document.getElementById('lp-status-badge');
  const btn   = document.getElementById('lp-toggle-btn');
  try {
    const res  = await fetch('/api/loyalty/settings');
    if (!res.ok) throw new Error('Failed to load settings.');
    const data = await res.json();
    renderLoyaltyStatus(data.enabled);
    renderCycleInfo(data);
  } catch (err) {
    badge.textContent = 'Status unknown';
    btn.style.display  = 'none';
  }
}

function renderCycleInfo(data) {
  const infoEl   = document.getElementById('lp-cycle-info');
  const dateEl   = document.getElementById('lp-activation-date');
  const notStart = document.getElementById('lp-not-started-banner');

  if (data.activation_date) dateEl.value = data.activation_date;

  if (data.current_cycle) {
    notStart.style.display = 'none';
    infoEl.innerHTML = `Cycle #${data.current_cycle.cycle_number}: ` +
      `<strong>${data.current_cycle.start_date}</strong> to ` +
      `<strong>${data.current_cycle.end_date}</strong>`;
  } else {
    notStart.style.display = data.activation_date ? 'block' : 'none';
    infoEl.textContent = data.activation_date
      ? `Program will start on ${data.activation_date}.`
      : 'No activation date set yet.';
  }
}

async function saveActivationDate() {
  const input   = document.getElementById('lp-activation-date');
  const btn     = document.getElementById('lp-save-activation-btn');
  const errEl   = document.getElementById('lp-activation-error');
  errEl.style.display = 'none';

  if (!input.value) {
    errEl.textContent   = 'Please choose a date.';
    errEl.style.display = 'block';
    return;
  }

  btn.disabled = true;
  try {
    const res  = await fetch('/api/loyalty/settings/activation-date', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ activation_date: input.value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to update activation date.');
    renderCycleInfo(data);
  } catch (err) {
    errEl.textContent   = err.message;
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
  }
}

function renderLoyaltyStatus(enabled) {
  const badge  = document.getElementById('lp-status-badge');
  const btn    = document.getElementById('lp-toggle-btn');
  const banner = document.getElementById('lp-paused-banner');

  badge.textContent = enabled ? 'Active' : 'Paused';
  badge.className   = 'badge ' + (enabled ? 'badge-success' : 'badge-warning');

  btn.textContent = enabled ? '⏸ Pause Program' : '▶ Resume Program';
  btn.disabled    = false;

  banner.style.display = enabled ? 'none' : 'block';
}

async function toggleLoyaltyProgram() {
  const badge = document.getElementById('lp-status-badge');
  const currentlyEnabled = badge.textContent === 'Active';

  if (currentlyEnabled && !confirm('Pause the loyalty program? No new gifts will be unlocked until you resume it.')) {
    return;
  }

  const btn = document.getElementById('lp-toggle-btn');
  btn.disabled = true;
  try {
    const res  = await fetch('/api/loyalty/settings/toggle', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to update setting.');
    renderLoyaltyStatus(data.enabled);
  } catch (err) {
    alert(err.message);
    btn.disabled = false;
  }
}

async function loadPendingGifts() {
  try {
    const res = await fetch('/api/loyalty/pending-gifts');
    if (!res.ok) throw new Error('Failed to load pending gifts.');
    const gifts = await res.json();
    document.getElementById('lp-loading').style.display = 'none';
    renderPendingGifts(gifts);
  } catch (err) {
    document.getElementById('lp-loading').style.display = 'none';
    const errEl = document.getElementById('lp-error');
    errEl.textContent   = err.message;
    errEl.style.display = 'block';
  }
}

function renderPendingGifts(gifts) {
  const countEl = document.getElementById('lp-count');
  const emptyEl = document.getElementById('lp-empty');
  const wrapEl  = document.getElementById('lp-table-wrap');
  const tbody   = document.getElementById('lp-body');

  countEl.textContent = gifts.length ? `${gifts.length} pending` : '';

  if (!gifts.length) {
    emptyEl.style.display = 'block';
    wrapEl.style.display  = 'none';
    return;
  }

  emptyEl.style.display = 'none';
  wrapEl.style.display  = 'block';

  tbody.innerHTML = gifts.map(g => `
    <tr id="lp-row-${g.id}">
      <td><a href="/customers/${g.customer_id}" style="color:var(--primary);font-weight:600;">${escapeHtml(g.customer_name)}</a></td>
      <td style="color:var(--text-muted);">${escapeHtml(g.customer_mobile)}</td>
      <td><span class="badge ${TIER_CSS[g.tier] || 'badge-neutral'}">${TIER_LABEL[g.tier] || g.tier}</span></td>
      <td>${(g.created_at || '').slice(0, 10)}</td>
      <td style="text-align:center;">
        <button type="button" class="btn btn-primary btn-sm" onclick="markGiftGiven(${g.id})">
          &#10003; Mark as Given
        </button>
      </td>
    </tr>
  `).join('');
}

async function markGiftGiven(giftId) {
  const row = document.getElementById(`lp-row-${giftId}`);
  const btn = row ? row.querySelector('button') : null;
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

  try {
    const res  = await fetch(`/api/loyalty/gifts/${giftId}/mark-given`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to update gift.');

    if (row) {
      row.style.transition = 'opacity 0.3s';
      row.style.opacity    = '0';
      setTimeout(() => {
        row.remove();
        const remaining = document.querySelectorAll('#lp-body tr').length;
        document.getElementById('lp-count').textContent = remaining ? `${remaining} pending` : '';
        if (!remaining) {
          document.getElementById('lp-empty').style.display = 'block';
          document.getElementById('lp-table-wrap').style.display = 'none';
        }
      }, 300);
    }
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = '✓ Mark as Given'; }
    alert(err.message);
  }
}
