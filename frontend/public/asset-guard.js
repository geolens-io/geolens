// fix(#645): if the shell is stale (heuristically cached pre-#622, or a tab
// left open across a deploy), its hashed /assets/ script/CSS 404 and the app
// renders blank/unstyled with no recovery. Reload once so the no-cache shell
// revalidates to the current build. External file, not inline — the page
// ships a strict script-src 'self' CSP (SEC-020). Keep the latch key +
// window in sync with src/lib/stale-asset-reload.ts (the same guard for
// lazy route chunks).
(function () {
  window.addEventListener(
    'error',
    function (e) {
      var el = e.target;
      if (!el || !el.tagName) return;
      var tag = el.tagName;
      if (tag !== 'SCRIPT' && tag !== 'LINK') return;
      var url = el.src || el.href || '';
      if (url.indexOf('/assets/') === -1) return;
      // fix(#1515): the reload has to stay INSIDE the try. sessionStorage is not
      // merely null in a storage-denied context, it throws — a sandboxed iframe
      // without allow-same-origin has an opaque origin and reading the property
      // raises SecurityError. Reloading from the catch ran unlatched: the shell
      // reloaded, the asset failed again, and the frame re-requested at ~1000
      // req/s on localhost. No latch, no reload.
      try {
        var last = Number(sessionStorage.getItem('geolens-asset-reload-at') || 0);
        if (Date.now() - last < 30000) return;
        sessionStorage.setItem('geolens-asset-reload-at', String(Date.now()));
        window.location.reload();
      } catch (err) {}
    },
    true
  );
})();
