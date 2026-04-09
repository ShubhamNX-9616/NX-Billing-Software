/* dashboard.js — Dashboard page logic with analytics */

// ---- State ----
let salesChart = null;
let currentPeriod = 'monthly';

// ---- Formatters ----
function fmtCurrency(amount) {
  return Number(amount || 0).toLocaleString('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtAmount(amount) {
  return '\u20B9' + Number(amount || 0).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function paymentBadge(mode) {
  const map = { Cash: 'badge-success', Card: 'badge-info', UPI: 'badge-warning', Combination: 'badge-neutral' };
  return `<span class="badge ${map[mode] || 'badge-neutral'}">${mode}</span>`;
}

function pct(part, total) {
  if (!total) return '0%';
  return (part / total * 100).toFixed(1) + '%';
}

// ---- Section 1: Summary Cards ----
function renderSummary(data) {
  document.getElementById('val-total-bills').textContent      = data.total_bills ?? '—';
  document.getElementById('val-total-customers').textContent  = data.total_customers ?? '—';
  document.getElementById('val-today-sales').textContent      = fmtCurrency(data.today_sales);
  document.getElementById('val-today-bills-count').textContent =
    data.today_bills ? `${data.today_bills} bill${data.today_bills !== 1 ? 's' : ''} today` : '';
  document.getElementById('val-month-sales').textContent      = fmtCurrency(data.this_month_sales);
}

// ---- Section 2 & 3: Period Tabs + Chart ----
const PERIOD_TITLES = {
  daily:   'Daily Sales \u2014 Last 30 Days',
  monthly: 'Monthly Sales \u2014 Last 12 Months',
  yearly:  'Yearly Sales \u2014 Last 5 Years',
};

function setActiveTab(period) {
  ['daily', 'monthly', 'yearly'].forEach(p => {
    const btn = document.getElementById(`tab-${p}`);
    if (p === period) {
      btn.classList.add('btn-primary');
      btn.classList.remove('btn-secondary');
    } else {
      btn.classList.remove('btn-primary');
      btn.classList.add('btn-secondary');
    }
  });
  document.getElementById('chart-title').textContent = PERIOD_TITLES[period];
}

function buildChart(labels, cashData, cardData, upiData, comboData) {
  const ctx = document.getElementById('sales-chart').getContext('2d');
  if (salesChart) salesChart.destroy();
  salesChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Cash',        data: cashData,  backgroundColor: '#10b981', stack: 'sales' },
        { label: 'Card',        data: cardData,  backgroundColor: '#3b82f6', stack: 'sales' },
        { label: 'UPI',         data: upiData,   backgroundColor: '#8b5cf6', stack: 'sales' },
        { label: 'Combination', data: comboData, backgroundColor: '#f59e0b', stack: 'sales' },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            label(item) {
              return ` ${item.dataset.label}: ${fmtAmount(item.raw)}`;
            },
            footer(items) {
              const total = items.reduce((s, i) => s + (i.raw || 0), 0);
              return `Total: ${fmtAmount(total)}`;
            },
          },
        },
      },
      scales: {
        x: { stacked: true },
        y: {
          stacked: true,
          ticks: {
            callback(value) {
              if (value >= 100000) return '\u20B9' + (value / 100000).toFixed(1) + 'L';
              if (value >= 1000)   return '\u20B9' + (value / 1000).toFixed(0) + 'K';
              return '\u20B9' + value;
            },
          },
        },
      },
    },
  });
}

function updateChart(labels, cashData, cardData, upiData, comboData) {
  if (!salesChart) {
    buildChart(labels, cashData, cardData, upiData, comboData);
    return;
  }
  salesChart.data.labels              = labels;
  salesChart.data.datasets[0].data    = cashData;
  salesChart.data.datasets[1].data    = cardData;
  salesChart.data.datasets[2].data    = upiData;
  salesChart.data.datasets[3].data    = comboData;
  salesChart.update();
}

// ---- Section 4: Payment Method Cards ----
function renderPaymentCards(data) {
  const totalSales = data.reduce((s, d) => s + d.total_sales, 0);
  const totalCash  = data.reduce((s, d) => s + d.cash, 0);
  const totalCard  = data.reduce((s, d) => s + d.card, 0);
  const totalUpi   = data.reduce((s, d) => s + d.upi, 0);
  const totalCombo = data.reduce((s, d) => s + d.combination, 0);

  document.getElementById('pcard-cash-amount').textContent  = fmtCurrency(totalCash);
  document.getElementById('pcard-card-amount').textContent  = fmtCurrency(totalCard);
  document.getElementById('pcard-upi-amount').textContent   = fmtCurrency(totalUpi);
  document.getElementById('pcard-combo-amount').textContent = fmtCurrency(totalCombo);

  document.getElementById('pcard-cash-pct').textContent  = `${pct(totalCash,  totalSales)} of period sales`;
  document.getElementById('pcard-card-pct').textContent  = `${pct(totalCard,  totalSales)} of period sales`;
  document.getElementById('pcard-upi-pct').textContent   = `${pct(totalUpi,   totalSales)} of period sales`;
  document.getElementById('pcard-combo-pct').textContent = `${pct(totalCombo, totalSales)} of period sales`;
}

// ---- Section 5: Recent Bills ----
function renderRecentBills(bills) {
  const loading = document.getElementById('recent-bills-loading');
  const empty   = document.getElementById('recent-bills-empty');
  const wrap    = document.getElementById('recent-bills-table-wrap');
  const tbody   = document.getElementById('recent-bills-body');

  loading.style.display = 'none';

  if (!bills.length) {
    empty.style.display = 'block';
    return;
  }

  wrap.style.display = 'block';
  tbody.innerHTML = bills.slice(0, 10).map(b => `
    <tr onclick="location.href='/bills/${b.id}'" style="cursor:pointer;">
      <td><span class="fw-600">${b.bill_number}</span></td>
      <td>${b.customer_name_snapshot || '—'}</td>
      <td class="col-date">${b.bill_date || '—'}</td>
      <td class="text-right fw-600">${fmtCurrency(b.final_total)}</td>
      <td class="col-payment">${paymentBadge(b.payment_mode_type)}</td>
      <td>
        <a href="/bills/${b.id}" class="btn btn-secondary btn-sm" onclick="event.stopPropagation()">View</a>
      </td>
    </tr>
  `).join('');
}

// ---- Load analytics period ----
async function loadPeriodData(period) {
  const loading = document.getElementById('chart-loading');
  const wrap    = document.getElementById('chart-wrap');

  loading.style.display = 'flex';
  wrap.style.display    = 'none';

  try {
    const res = await fetch(`/api/analytics?period=${period}`);
    if (!res.ok) throw new Error('API error');
    let data = await res.json();

    // On mobile: trim visible buckets to avoid crowded axis
    const isMobile = window.innerWidth <= 768;
    if (isMobile && period === 'daily')   data = data.slice(-7);
    if (isMobile && period === 'monthly') data = data.slice(-6);

    const labels    = data.map(d => d.label);
    const cashData  = data.map(d => d.cash);
    const cardData  = data.map(d => d.card);
    const upiData   = data.map(d => d.upi);
    const comboData = data.map(d => d.combination);

    updateChart(labels, cashData, cardData, upiData, comboData);
    renderPaymentCards(data);
  } catch (err) {
    console.error('Analytics load error:', err);
  } finally {
    loading.style.display = 'none';
    wrap.style.display    = 'block';
  }
}

// ---- Period tab switch ----
async function switchPeriod(period) {
  currentPeriod = period;
  setActiveTab(period);
  await loadPeriodData(period);
}

// ---- Main load ----
async function loadDashboard() {
  // Summary + bills in parallel
  try {
    const [summaryRes, billsRes] = await Promise.all([
      fetch('/api/analytics/summary'),
      fetch('/api/bills'),
    ]);

    if (summaryRes.ok) renderSummary(await summaryRes.json());

    if (billsRes.ok) {
      renderRecentBills(await billsRes.json());
    } else {
      document.getElementById('recent-bills-loading').innerHTML =
        '<span class="text-danger">Failed to load bills.</span>';
    }
  } catch (err) {
    console.error(err);
    document.getElementById('recent-bills-loading').innerHTML =
      `<span class="text-danger">Failed to load data: ${err.message}</span>`;
  }

  // Load default period chart
  setActiveTab('monthly');
  await loadPeriodData('monthly');
}

document.addEventListener('DOMContentLoaded', loadDashboard);
