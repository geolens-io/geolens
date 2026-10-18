/**
 * Session-scoped negative cache for quicklook fetch() 404s.
 *
 * A dataset whose quicklook file is missing on disk returns 404 even with a
 * valid JWT: the backend sets has_quicklook=true when quicklook_256_uri is
 * assigned at ingest but does not verify the file exists. When apiFetchBlob()
 * receives a 404 it calls markQuicklookMissing(datasetId), so later renders in
 * the tab skip the fetch and show the placeholder.
 *
 * Non-404 errors (500, network) are transient and NOT negative-cached.
 *
 * Storage: sessionStorage, so the cache survives a tab reload but not new tabs;
 * falls back to memory when sessionStorage is unavailable (private mode, SSR).
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

// A redrawn quicklook has a new version, so a miss recorded for the old image
// must not hide it.
function cacheKey(datasetId: string, version: string | null): string {
  return version ? `${datasetId}@${version}` : datasetId;
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
 * True if the quicklook for `datasetId` has 404'd in this tab session; the card
 * then skips the `<img>`.
 */
export function isQuicklookKnownMissing(
  datasetId: string,
  version: string | null = null,
): boolean {
  return readSet().has(cacheKey(datasetId, version));
}

/**
 * Record that the quicklook for `datasetId` failed to load, so this tab session
 * skips the request.
 */
export function markQuicklookMissing(
  datasetId: string,
  version: string | null = null,
): void {
  const set = readSet();
  const key = cacheKey(datasetId, version);
  if (set.has(key)) return;
  set.add(key);
  writeSet(set);
}

/** Test-only: reset both the memory cache and sessionStorage entry. */
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
