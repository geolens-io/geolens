/**
 * SP-07: session-scoped negative cache for dataset quicklooks.
 *
 * The OGC search response's `has_quicklook` flag is derived from
 * `dataset.quicklook_256_uri IS NOT NULL` — it tells us the backend assigned
 * a URI at ingest time, but it does NOT verify the file actually exists on
 * disk / in object storage. When the Celery thumbnail-generation task fails
 * silently (or was disabled), the URI is set but the file is missing, and
 * the frontend issues a doomed `GET /api/datasets/<id>/quicklook?size=256`
 * that 404s and pollutes the console.
 *
 * Until the backend grows an honest `thumbnail_status` field, this module
 * records every quicklook URL that 404s for the current tab session and
 * exposes a check so subsequent renders / reloads skip the `<img>` entirely.
 *
 * Storage: sessionStorage so the cache survives a single tab reload but
 * resets across new tabs / windows. Falls back to in-memory when
 * sessionStorage is unavailable (private mode, SSR).
 */

const STORAGE_KEY = 'geolens-quicklook-404';

let memoryCache: Set<string> | null = null;

function getStore(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

function readSet(): Set<string> {
  if (memoryCache) return memoryCache;
  const store = getStore();
  if (!store) {
    memoryCache = new Set();
    return memoryCache;
  }
  try {
    const raw = store.getItem(STORAGE_KEY);
    memoryCache = raw ? new Set<string>(JSON.parse(raw) as string[]) : new Set();
  } catch {
    memoryCache = new Set();
  }
  return memoryCache;
}

function writeSet(set: Set<string>): void {
  memoryCache = set;
  const store = getStore();
  if (!store) return;
  try {
    store.setItem(STORAGE_KEY, JSON.stringify([...set]));
  } catch {
    // sessionStorage quota / disabled — memory cache still works for the session
  }
}

/**
 * Returns true if the quicklook for `datasetId` has 404'd in the current
 * tab session. The card should skip the `<img>` element in that case.
 */
export function isQuicklookKnownMissing(datasetId: string): boolean {
  return readSet().has(datasetId);
}

/**
 * Record that the quicklook for `datasetId` failed to load. Subsequent
 * renders within the same tab session will skip the request.
 */
export function markQuicklookMissing(datasetId: string): void {
  const set = readSet();
  if (set.has(datasetId)) return;
  set.add(datasetId);
  writeSet(set);
}

/**
 * Test-only: reset both the memory cache and sessionStorage entry.
 */
export function _resetQuicklookCache(): void {
  memoryCache = null;
  const store = getStore();
  if (store) {
    try {
      store.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }
}
