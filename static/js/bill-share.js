/* ============================================================
   bill-share.js — WhatsApp message and share-link helpers
   Depends on: bill-state.js (fmt)
   ============================================================ */

function formatDate(isoStr) {
  if (!isoStr) return '';
  const [y, m, d] = isoStr.split('-');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${parseInt(d, 10)} ${months[parseInt(m, 10) - 1]} ${y}`;
}

function formatCurrency(amount) {
  return fmt(amount);
}

function buildWhatsAppMessage(bill) {
  const shopName    = 'SHUBHAM NX';
  const shopAddress = 'Krishna Chowk, New Sangvi, Pune - 411061';
  const shopPhone   = '+91 9284630254';

  const dateStr = bill.bill_date
    ? formatDate(bill.bill_date)
    : new Date().toLocaleDateString('en-IN');

  const total     = formatCurrency(bill.final_total);
  const advance   = bill.advance_paid > 0 ? formatCurrency(bill.advance_paid) : null;
  const remaining = bill.remaining > 0    ? formatCurrency(bill.remaining)    : null;
  const shareLink = window.location.origin + '/bill/share/' + bill.bill_number;

  const lines = [];
  lines.push('Dear ' + bill.customer_name + ',');
  lines.push('');
  lines.push('Thank you for shopping at *' + shopName + '*! 🙏');
  lines.push('');
  lines.push('*Bill Details:*');
  lines.push('Bill No : ' + bill.bill_number);
  lines.push('Date    : ' + dateStr);
  lines.push('Amount  : ' + total);
  if (advance)   lines.push('Advance : ' + advance);
  if (remaining) lines.push('Balance : ' + remaining + ' (pending)');
  lines.push('');
  lines.push('📄 View your bill here:');
  lines.push(shareLink);
  lines.push('');
  lines.push('📍 ' + shopAddress);
  lines.push('📞 ' + shopPhone);
  lines.push('');
  lines.push('⭐ Loved your purchase? Please leave us a review:');
  lines.push('https://maps.app.goo.gl/YjTCZZNLWwbjWZDH8');
  lines.push('');
  lines.push('We look forward to serving you again!');

  return lines.join('\n');
}

function buildWhatsAppURL(mobile, message) {
  let m = mobile.replace(/\D/g, '');
  if (m.length === 10)                          m = '91' + m;
  else if (m.length === 11 && m.startsWith('0')) m = '91' + m.slice(1);
  return 'https://wa.me/' + m + '?text=' + encodeURIComponent(message);
}

function buildShareLink(billNumber) {
  const base = window.SHARE_BASE_URL || window.location.origin;
  return base + '/bill/share/' + billNumber;
}

function showPostSaveActions(bill) {
  const waBtn = document.getElementById('whatsapp-btn');
  if (waBtn) waBtn.href = buildWhatsAppURL(bill.customer_mobile, buildWhatsAppMessage(bill));

  const shareBtn = document.getElementById('share-link-btn');
  if (shareBtn) {
    shareBtn.onclick = function () {
      copyToClipboard(buildShareLink(bill.bill_number));
      const msg = document.getElementById('link-copied-msg');
      if (msg) {
        msg.style.display = 'inline-flex';
        setTimeout(() => { msg.style.display = 'none'; }, 3000);
      }
    };
  }

  const section = document.getElementById('post-save-actions');
  if (section) section.style.display = 'flex';
}

function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).catch(() => { fallbackCopy(text); });
  } else {
    fallbackCopy(text);
  }
}

function fallbackCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0;';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try { document.execCommand('copy'); } catch (e) { console.warn('Copy failed:', e); }
  document.body.removeChild(ta);
}
