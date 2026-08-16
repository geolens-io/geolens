// fix(#645): stale SPA shells 404 on old hashed assets after a deploy.
// #622's no-cache header stops new shells from going stale but cannot heal
// pre-fix heuristic caches or tabs left open across a deploy. When a lazy
// route chunk fails to load, reload once — the reload revalidates the
// no-cache shell and picks up the current build. Time-latched via
// sessionStorage so a genuinely broken server can't cause a reload loop — and,
// fix(#1515), skipped outright when the latch cannot be read or written, since
// an unlatched reload is the loop the latch exists to prevent.
// Keep the latch key + window in sync with public/asset-guard.js (the same
// guard for the initial <script>/<link> loads, which must live in the shell).

const LATCH_KEY = 'geolens-asset-reload-at';
const LATCH_WINDOW_MS = 30_000;

export function reloadOnceForStaleAssets(): boolean {
  try {
    const last = Number(sessionStorage.getItem(LATCH_KEY) || 0);
    if (Date.now() - last < LATCH_WINDOW_MS) return false;
    sessionStorage.setItem(LATCH_KEY, String(Date.now()));
  } catch {
    // fix(#1515): fail closed. Storage is not merely unavailable in a sandboxed
    // frame with an opaque origin — reading the property throws SecurityError —
    // and the previous comment here claimed the window.location round-trip
    // throttled retries when there was no latch. It does not: measured against
    // an `immutable` shell, the unlatched path reloaded ~12,000 times in 12s on
    // localhost (~60/s over the internet). No latch, no reload.
    return false;
  }
  window.location.reload();
  return true;
}

export function installStaleAssetReload(): void {
  window.addEventListener('vite:preloadError', (event) => {
    if (reloadOnceForStaleAssets()) {
      // Suppress the throw from the failed dynamic import; the reload
      // supersedes it.
      event.preventDefault();
    }
  });
}
