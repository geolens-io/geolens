// If the shell is stale (heuristically cached before it was served no-cache,
// or a tab left open across a deploy), its hashed /assets/ script/CSS 404 and the app
// renders blank/unstyled with no recovery. Reload once so the no-cache shell
// revalidates to the current build. External file, not inline — the page
// ships a strict script-src 'self' CSP. Keep the latch key +
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
      // The reload has to stay INSIDE the try. sessionStorage throws in a
      // storage-denied context (a sandboxed iframe without allow-same-origin has
      // an opaque origin, so reading the property raises SecurityError).
      // Reloading from the catch would run unlatched and loop at ~1000 req/s.
      // No latch, no reload.
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
