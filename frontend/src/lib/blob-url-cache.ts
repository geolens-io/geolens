import type { QueryClient } from '@tanstack/react-query';

/**
 * Blob-URL revocation tied to the React Query cache lifecycle.
 *
 * Several hooks (useMapThumbnail, useQuicklook) fetch an authenticated image
 * via apiFetchBlob and expose it as a `URL.createObjectURL(blob)` string that
 * is cached in React Query under a stable query key. Revoking that blob URL in
 * a component `useEffect` cleanup is WRONG: the blob URL string outlives the
 * component in the query cache, so the next consumer (list↔grid toggle,
 * back-navigation within gcTime, StrictMode remount, a second card sharing the
 * key) reads the already-revoked string and the browser logs
 * `net::ERR_FILE_NOT_FOUND`.
 *
 * Instead we revoke exactly once, when React Query itself drops or replaces the
 * cached value:
 *   - `removed`  → the entry was evicted (gcTime) or cleared → revoke its blob.
 *   - `updated`  → a refetch produced a NEW blob URL → revoke the previous one.
 *
 * The subscription is registered once per QueryClient (idempotent).
 */

const registered = new WeakSet<QueryClient>();

// Query-key roots whose cached value is a blob: object URL we own.
const BLOB_QUERY_KEYS = new Set(['map-thumbnail', 'quicklook']);

function isBlobUrl(value: unknown): value is string {
  return typeof value === 'string' && value.startsWith('blob:');
}

export function registerBlobUrlRevocation(queryClient: QueryClient): void {
  if (registered.has(queryClient)) return;
  registered.add(queryClient);

  // Track the last blob URL we saw per query hash so a refetch that replaces
  // the value can revoke the stale one without touching the live one.
  const lastSeen = new Map<string, string>();

  queryClient.getQueryCache().subscribe((event) => {
    const query = event.query;
    const root = query.queryKey?.[0];
    if (typeof root !== 'string' || !BLOB_QUERY_KEYS.has(root)) return;

    const hash = query.queryHash;
    const data = query.state.data;

    if (event.type === 'removed') {
      const url = isBlobUrl(data) ? data : lastSeen.get(hash);
      if (url) URL.revokeObjectURL(url);
      lastSeen.delete(hash);
      return;
    }

    if (isBlobUrl(data)) {
      const prev = lastSeen.get(hash);
      if (prev && prev !== data) URL.revokeObjectURL(prev);
      lastSeen.set(hash, data);
    }
  });
}
