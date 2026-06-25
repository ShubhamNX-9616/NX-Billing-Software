/* inst-performa.js — Invoice / Proforma Invoice print for institution bills */

function _fmtPerformaDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const yyyy = d.getFullYear();
  return `${dd}/${mm}/${yyyy}`;
}

// type: 'proforma' | 'invoice'
function buildPerformaWindow(bill, items, type, winRef) {
  type = type || 'proforma';
  const isProforma = type === 'proforma';
  const docTitle   = isProforma ? 'Proforma Invoice' : 'Invoice';
  const salutation = isProforma
    ? 'Pls Find the Proforma Invoice for the below mentioned quality for your perusal.'
    : 'Pls Find the Invoice for the below mentioned quality for your perusal.';

  const date = _fmtPerformaDate(bill.bill_date);

  let grandTotal = 0;
  const itemRows = items.map(item => {
    const noOfPcs  = Number(item.no_of_pcs       || 0);
    const qtyPerPc = Number(item.quantity_per_pc  || 0);
    const rate     = Number(item.rate_per_m       || 0);
    const total    = Number(item.total            || 0);
    grandTotal    += total;

    const stitching = Number(item.stitching_per_unit || 0);

    return `
      <tr>
        <td class="td-left">${item.cloth_type   || '—'}</td>
        <td class="td-left">${item.company_name || '—'}</td>
        <td class="td-left">${item.quality_number || '—'}</td>
        <td class="td-right">${qtyPerPc.toFixed(2)}</td>
        <td class="td-right">${rate.toFixed(2)}</td>
        <td class="td-right">${noOfPcs}</td>
        <td class="td-right">${stitching ? stitching.toFixed(2) : '—'}</td>
        <td class="td-right">${total.toFixed(2)}</td>
      </tr>`;
  }).join('');

  const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8" />
  <title>${docTitle} — ${bill.bill_number}</title>
  <style>
    @page { size: A4 portrait; margin: 14mm 16mm; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, sans-serif; font-size: 13px; color: #000; background: #fff; }

    .header-wrap { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px; }
    .shop-name { font-size: 28px; font-weight: 900; letter-spacing: 0.5px; text-transform: uppercase; }
    .shop-meta { font-size: 12px; margin-top: 3px; line-height: 1.55; color: #111; }
    hr.thick { border: none; border-top: 2px solid #000; margin: 5px 0 10px; }

    .company-block { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; font-size: 13px; line-height: 1.6; font-weight: 600; }
    .company-meta { text-align: right; white-space: nowrap; }

    .salutation { font-size: 13px; line-height: 1.8; margin-bottom: 10px; }
    .salutation .intro { margin-top: 10px; }

    table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 12px; }
    thead th {
      border: 1px solid #333;
      padding: 6px 7px;
      font-weight: 700;
      text-align: center;
      background: #f0f0f0;
      vertical-align: middle;
      line-height: 1.3;
    }
    tbody td { border: 1px solid #555; padding: 5px 7px; }
    .td-right { text-align: right; }
    .td-left  { text-align: left; }
    .td-center { text-align: center; }
    tr.total-row td {
      border: 1px solid #333;
      padding: 5px 6px;
      font-weight: 700;
    }

    .footer-note { font-size: 13px; margin-bottom: 6px; }
    .sign-block  { margin-top: 28px; font-size: 13px; line-height: 2; }
  </style>
</head>
<body>

  <div style="text-align:center;font-size:22px;font-weight:900;letter-spacing:2px;margin-bottom:8px;">${isProforma ? 'PERFORMA INVOICE' : 'INVOICE'}</div>
  <div class="header-wrap">
    <div>
      <div class="shop-name">SHUBHAM NX</div>
      <div class="shop-meta">
        Asha Shankar Plaza, Vidya Nagar, Krishana Bazar Chowk New Sangvi, Pune-411061<br/>
        GST No &ndash; 27AAKHM5518F1Z3<br/>
        COMPOSITION TAXABLE PERSON, NOT ELIGIBLE TO COLLECT TAX ON SUPPLIES<br/>
        Authorised Dealers for RAYMONDS, VIMAL, SIYARAMS and GRASIM.
      </div>
    </div>
  </div>

  <hr class="thick" />

  <div class="company-block">
    <div>
      ${bill.company_name}<br/>
      ${bill.company_address ? bill.company_address + '<br/>' : ''}${bill.contact_person_name || ''}
    </div>
    <div class="company-meta">
      Date: ${date}${!isProforma ? `<br/>Invoice No: ${bill.bill_number}` : ''}
    </div>
  </div>

  ${isProforma ? `
  <div class="salutation">
    Dear Sir/Ma'am,
    <div class="intro">${salutation}</div>
  </div>` : ''}

  <table>
    <thead>
      <tr>
        <th style="width:18%;">Cloth Type</th>
        <th style="width:18%;">Company</th>
        <th style="width:14%;">Quality No</th>
        <th style="width:10%;">Qty/pc (m)</th>
        <th style="width:10%;">Rate/m (₹)</th>
        <th style="width:9%;">No. of Pcs</th>
        <th style="width:10%;">Stitch/unit</th>
        <th style="width:11%;">Total (₹)</th>
      </tr>
    </thead>
    <tbody>
      ${itemRows}
    </tbody>
  </table>

  <div style="display:flex;justify-content:flex-end;margin-bottom:14px;">
    <table style="width:auto;border-collapse:collapse;font-size:13px;">
      <tr>
        <td style="padding:4px 16px 4px 8px;font-weight:700;border:1px solid #333;background:#f0f0f0;">Total</td>
        <td style="padding:4px 12px;text-align:right;font-weight:700;border:1px solid #333;background:#f0f0f0;min-width:100px;">₹${grandTotal.toFixed(2)}</td>
      </tr>
      ${!isProforma ? `
      <tr>
        <td style="padding:4px 16px 4px 8px;border:1px solid #555;">Advance Paid</td>
        <td style="padding:4px 12px;text-align:right;border:1px solid #555;">₹${Number(bill.advance_paid || 0).toFixed(2)}</td>
      </tr>
      <tr>
        <td style="padding:4px 16px 4px 8px;font-weight:700;border:1px solid #333;">Remaining</td>
        <td style="padding:4px 12px;text-align:right;font-weight:700;border:1px solid #333;">₹${Number(bill.remaining || 0).toFixed(2)}</td>
      </tr>` : ''}
    </table>
  </div>

  <div class="footer-note"><strong>Note:</strong></div>
  <div class="footer-note">All the above rates does include GST.</div>
  ${isProforma ? '<div class="footer-note">This Quotation valid for 5 Days only.</div>' : ''}
  <div class="footer-note">Cost of Embroidery would be extra at Actual.</div>
  ${isProforma ? '<div class="footer-note">70% Advance along with PO.</div>' : ''}
  ${isProforma ? `<div class="footer-note" style="margin-top:20px;">Looking forward for your kind and continued support.</div>` : ''}

  <div class="sign-block">
    ${isProforma ? `Yours faithfully<br/><br/><br/>Shubham NX` : `<div style="margin-top:60px;">Shubham NX</div>`}
  </div>

  <script>window.onload = function () { window.print(); };<\/script>
</body>
</html>`;

  const win = winRef || window.open('', '_blank');
  win.document.write(html);
  win.document.close();
}

async function openInstPerformaInvoice(billId) {
  // Open window immediately (before await) so iOS Safari doesn't block the popup
  const win = window.open('', '_blank');
  try {
    const res  = await fetch(`/api/institution-bills/${billId}`);
    if (!res.ok) throw new Error('Bill not found');
    const data = await res.json();
    buildPerformaWindow(data.bill, data.items, 'proforma', win);
  } catch (err) {
    if (win) win.close();
    alert('Failed to load bill for printing: ' + err.message);
  }
}

async function openInstInvoice(billId) {
  // Open window immediately (before await) so iOS Safari doesn't block the popup
  const win = window.open('', '_blank');
  try {
    const res  = await fetch(`/api/institution-bills/${billId}`);
    if (!res.ok) throw new Error('Bill not found');
    const data = await res.json();
    buildPerformaWindow(data.bill, data.items, 'invoice', win);
  } catch (err) {
    if (win) win.close();
    alert('Failed to load bill for printing: ' + err.message);
  }
}
