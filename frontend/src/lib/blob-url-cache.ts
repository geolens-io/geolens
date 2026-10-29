import type { QueryClient } from '@tanstack/react-query';

/**
 * Blob-URL revocation tied to the React Query cache lifecycle.
 *
 * Hooks like useMapThumbnail and useQuicklook cache a
 * `URL.createObjectURL(blob)` string in React Query. Revoking it in a
 * component `useEffect` cleanup is wrong: the string outlives the component in
 * the cache, so the next consumer reads a revoked URL (`net::ERR_FILE_NOT_FOUND`).
 * Instead it is revoked once, when React Query drops or replaces the value:
 *   - `removed`  → the entry was evicted (gcTime) or cleared → revoke its blob.
 *   - `updated`  → a refetch produced a NEW blob URL → revoke the previous one.
 *
 * The subscription is registered once per QueryClient (idempotent).
 */

const registered = new WeakSet<QueryClient>();

// Query-key roots whose cached value is a blob: object URL we own.
const BLOB_QUERY_KEYS = new Set(['map-thumbnail', 'quicklook', 'asset-image']);

function isBlobUrl(value: unknown): value is string {
  return typeof value === 'string' && value.startsWith('blob:');
}

export function registerBlobUrlRevocation(queryClient: QueryClient): void {
  if (registered.has(queryClient)) return;
  registered.add(queryClient);

  // Last blob URL per query hash, so a replacing refetch revokes only the stale one.
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
