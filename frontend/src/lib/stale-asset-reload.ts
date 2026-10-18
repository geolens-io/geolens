// Stale SPA shells 404 on old hashed assets after a deploy. The no-cache shell
// header cannot heal heuristic caches or tabs left open across a deploy. When
// a lazy route chunk fails to load, reload once so the revalidated shell picks
// up the current build. Time-latched via sessionStorage so a broken server
// can't cause a reload loop, and skipped when the latch can't be read or
// written. The latch key and window match public/asset-guard.js, the same
// guard for the initial <script>/<link> loads.

const LATCH_KEY = 'geolens-asset-reload-at';
const LATCH_WINDOW_MS = 30_000;

export function reloadOnceForStaleAssets(): boolean {
  try {
    const last = Number(sessionStorage.getItem(LATCH_KEY) || 0);
    if (Date.now() - last < LATCH_WINDOW_MS) return false;
    sessionStorage.setItem(LATCH_KEY, String(Date.now()));
  } catch {
    // Fail closed: in a sandboxed opaque-origin frame reading the property
    // throws SecurityError, and nothing else throttles retries; unlatched
    // against an `immutable` shell it reloaded ~12,000 times in 12s on
    // localhost. No latch, no reload.
    return false;
  }
  window.location.reload();
  return true;
}

export function installStaleAssetReload(): void {
  window.addEventListener('vite:preloadError', (event) => {
    if (reloadOnceForStaleAssets()) {
      // The reload supersedes the failed dynamic import's throw.
      event.preventDefault();
    }
  });
}
