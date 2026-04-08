import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { getTileToken, getTileTokensBatch } from '@/api/tiles';
import type { TileToken, TileTokenError } from '@/api/tiles';

/** Narrow a batch entry to a successful TileToken. */
function _isToken(v: TileToken | TileTokenError | undefined): v is TileToken {
  return !!v && 'kind' in v;
}

/**
 * Fetch and auto-refresh a signed tile token for a single dataset.
 * Disabled when datasetId is undefined.
 */
export function useTileToken(datasetId: string | undefined) {
  return useQuery<TileToken>({
    queryKey: queryKeys.tileTokens.token(datasetId),
    queryFn: () => getTileToken(datasetId!),
    enabled: !!datasetId,
    refetchInterval: (query) => {
      const d = query.state.data;
      if (!d) return false;
      if (d.kind !== 'vector') return false;
      return Math.max(d.expires_in * 800, 30_000);
    },
    staleTime: 60_000,
  });
}

/**
 * Fetch tile tokens for multiple datasets in a single batched request
 * (PERF-N5). Previously this spawned N parallel useQuery calls — a 20-layer
 * map meant 20 HTTP requests + 20 RBAC checks + 20 HMAC signatures on every
 * mount. The new implementation issues one POST /tiles/tokens/ with all
 * dataset IDs; errors for individual datasets are reported per-entry rather
 * than failing the whole query.
 *
 * The return shape is a tuple-like array matching the old useQueries shape
 * so callers (`BuilderMap`, `ViewerMap`) don't need to change.
 */
export function useTileTokens(datasetIds: string[]) {
  const uniqueIds = useMemo(
    () => [...new Set(datasetIds.filter(Boolean))],
    [datasetIds],
  );

  // Cache key includes the sorted unique set so queries are stable across
  // layer reorder but invalidated when the set changes.
  const sortedKey = useMemo(() => [...uniqueIds].sort().join(','), [uniqueIds]);

  // Choose the shortest expires_in among returned vector tokens to drive
  // refetch — every token in the batch has similar lifetime, so refreshing
  // them together is fine and avoids per-dataset refresh churn.
  const batchQuery = useQuery({
    queryKey: queryKeys.tileTokens.batch(sortedKey),
    queryFn: () => getTileTokensBatch(uniqueIds),
    enabled: uniqueIds.length > 0,
    staleTime: 60_000,
    refetchInterval: (query) => {
      const data = query.state.data?.tokens;
      if (!data) return false;
      let minVectorExpiry = Infinity;
      for (const entry of Object.values(data)) {
        if (_isToken(entry) && entry.kind === 'vector') {
          minVectorExpiry = Math.min(minVectorExpiry, entry.expires_in);
        }
      }
      if (!isFinite(minVectorExpiry)) return false;
      return Math.max(minVectorExpiry * 800, 30_000);
    },
  });

  // Adapt the batch result into the { data, isLoading, isError } shape that
  // callers iterate over (they index by the position of uniqueIds).
  return useMemo(() => {
    return uniqueIds.map((id) => {
      const entry = batchQuery.data?.tokens?.[id];
      const isTokenEntry = _isToken(entry);
      return {
        data: isTokenEntry ? (entry as TileToken) : undefined,
        isLoading: batchQuery.isLoading,
        isError: !isTokenEntry && !!entry,
        error:
          !isTokenEntry && entry ? new Error((entry as TileTokenError).error) : null,
      };
    });
  }, [uniqueIds, batchQuery.data, batchQuery.isLoading]);
}
