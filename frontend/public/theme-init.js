// FOUC prevention + lang sync — externalized from index.html so the page can
// ship a strict Content-Security-Policy (script-src 'self') with no inline
// <script> (SEC-020). Loaded render-blocking from <head>, so it still runs
// before first paint. Keep in sync with ThemeProvider storageKey and the i18n
// supportedLngs list.
(function () {
  try {
    var stored = localStorage.getItem('geolens-theme');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    var isDark = stored === 'dark' || (stored !== 'light' && prefersDark);
    if (isDark) document.documentElement.classList.add('dark');
    // Sync lang attribute before React hydration (must match i18n supportedLngs)
    var lang = localStorage.getItem('i18nextLng');
    if (lang && /^(en|de|fr|es)$/.test(lang)) {
      document.documentElement.lang = lang;
    }
  } catch (e) {}
})();
