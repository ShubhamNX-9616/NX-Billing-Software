/* Behaviour shared by every page that extends base.html (was inline). */

// Mark active bottom nav item based on current URL
(function () {
  var path = window.location.pathname;
  var map = {
    'dashboard': path === '/',
    'new-bill':  path === '/new-bill',
    'inst-bill': path === '/new-institution-bill',
    'history':   path.startsWith('/bill'),
    'customers': path.startsWith('/customers'),
    'inventory': path.startsWith('/inventory'),
    'tailoring': path.startsWith('/tailoring') && !path.startsWith('/tailoring/suits'),
    'suits': path.startsWith('/tailoring/suits'),
  };
  document.querySelectorAll('.mob-nav-item').forEach(function (el) {
    if (map[el.dataset.page]) el.classList.add('active');
  });
})();

// Alt+N → New Bill from anywhere in the app
document.addEventListener('keydown', function (e) {
  if (e.altKey && e.key === 'n') {
    e.preventDefault();
    window.location.href = '/new-bill';
  }
});

/* ---- Dark mode toggle ---- */
var THEME_KEY = 'snx-theme';

function _systemDark() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function _applyTheme(theme) {
  if (theme === 'dark' || (theme === 'auto' && _systemDark())) {
    document.documentElement.setAttribute('data-theme', 'dark');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
  // Let JS-rendered, self-styled widgets (the dashboard chart) re-read
  // their colours from the CSS custom properties.
  document.dispatchEvent(new CustomEvent('snx:themechange'));
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  if (theme === 'dark')  { btn.innerHTML = '<svg class="ico" aria-hidden="true"><use href="#i-sun"/></svg> Light mode';  }
  else if (theme === 'light') { btn.innerHTML = '<svg class="ico" aria-hidden="true"><use href="#i-circle"/></svg> Auto (system)'; }
  else                   { btn.innerHTML = '<svg class="ico" aria-hidden="true"><use href="#i-moon"/></svg> Dark mode'; }
}

function cycleTheme() {
  var cur  = localStorage.getItem(THEME_KEY) || 'auto';
  var next = cur === 'auto' ? 'dark' : cur === 'dark' ? 'light' : 'auto';
  localStorage.setItem(THEME_KEY, next);
  _applyTheme(next);
}

/* Init label once DOM is ready */
document.addEventListener('DOMContentLoaded', function () {
  _applyTheme(localStorage.getItem(THEME_KEY) || 'auto');
});

/* Follow system preference changes when in auto mode */
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
  if ((localStorage.getItem(THEME_KEY) || 'auto') === 'auto') _applyTheme('auto');
});
