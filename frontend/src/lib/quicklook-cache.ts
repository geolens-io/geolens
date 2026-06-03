/**
 * SP-07: session-scoped negative cache for quicklook fetch() 404s.
 *
 * Datasets whose quicklook file is missing on disk return 404 from
 * GET /api/datasets/<id>/quicklook even with a valid JWT (the backend sets
 * has_quicklook=true when quicklook_256_uri is assigned at ingest, but does
 * NOT verify that the file exists on disk / in object storage).
 *
 * The useQuicklook hook routes every quicklook request through apiFetchBlob()
 * (which attaches the Bearer JWT from useAuthStore). When apiFetchBlob()
 * receives a 404, it calls markQuicklookMissing(datasetId) so subsequent
 * renders within the same tab session skip the fetch entirely and fall back
 * to the placeholder immediately.
 *
 * Non-404 errors (e.g. 500, network) are NOT negative-cached — they are
 * transient and should be retried on the next render cycle.
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
