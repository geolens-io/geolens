import { useCallback, useMemo } from 'react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { getTileToken, getTileTokensBatch } from '@/api/tiles';
import type { TileToken, TileTokenError } from '@/api/tiles';

/** Narrow a batch entry to a successful TileToken. */
function isToken(v: TileToken | TileTokenError | undefined): v is TileToken {
  return !!v && 'kind' in v;
}

/**
 * A stable callback that drops every cached tile token
 * (single + batch), forcing a re-mint. Map hosts pass it to useWebGLRecovery so
 * a GPU context restore re-fetches tokens that may have expired during the outage.
 */
export function useInvalidateTileTokens() {
  const qc = useQueryClient();
  return useCallback(() => {
    qc.invalidateQueries({
      predicate: (q) =>
        Array.isArray(q.queryKey) &&
        (q.queryKey[0] === 'tile-token' || q.queryKey[0] === 'tile-tokens-batch'),
    });
  }, [qc]);
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
    // Explicit because it is the whole hidden-tab policy: a hidden tab must not
    // refresh, since MapLibre drops the resulting setTiles reload while the
    // TileManager is paused (the default would make the tab-return 403 burst certain).
    refetchIntervalInBackground: false,
  });
}

/**
 * Fetch tile tokens for multiple datasets in one batched POST /tiles/tokens/
 * (instead of N requests, RBAC checks and HMAC signatures per mount). Errors
 * for individual datasets are reported per entry rather than failing the whole
 * query. The return is a tuple-like array matching `useQueries`' shape for
 * `BuilderMap` and `ViewerMap`.
 */
export function useTileTokens(datasetIds: string[]) {
  const uniqueIds = useMemo(
    () => [...new Set(datasetIds.filter(Boolean))],
    [datasetIds],
  );

  // The sorted unique set keeps the key stable across layer reorder.
  const sortedKey = useMemo(() => [...uniqueIds].sort().join(','), [uniqueIds]);

  // Refetch on the shortest expires_in among vector tokens; the batch shares a
  // similar lifetime, so refreshing together avoids per-dataset churn.
  const batchQuery = useQuery({
    queryKey: queryKeys.tileTokens.batch(sortedKey),
    queryFn: () => getTileTokensBatch(uniqueIds),
    enabled: uniqueIds.length > 0,
    staleTime: 60_000,
    // Tokens from the previous id set stay usable while the new set loads, so
    // removing a layer does not blank the map. They are replaced within one
    // round trip, well inside their refresh window.
    placeholderData: keepPreviousData,
    // Bounded backoff: 3 attempts with exponential delay.
    retry: 3,
    refetchInterval: (query) => {
      const data = query.state.data?.tokens;
      if (!data) return false;
      let minVectorExpiry = Infinity;
      for (const entry of Object.values(data)) {
        if (isToken(entry) && entry.kind === 'vector') {
          minVectorExpiry = Math.min(minVectorExpiry, entry.expires_in);
        }
      }
      if (!isFinite(minVectorExpiry)) return false;
      return Math.max(minVectorExpiry * 800, 30_000);
    },
    // Hidden-tab policy: see useTileToken above.
    refetchIntervalInBackground: false,
  });

  // Adapt to the { data, isLoading, isError } shape callers index by uniqueIds position.
  return useMemo(() => {
    return uniqueIds.map((id) => {
      const entry = batchQuery.data?.tokens?.[id];
      const isTokenEntry = isToken(entry);
      // A requested dataset absent from a settled batch is an error, not a
      // silently blank layer.
      const missingAfterLoad =
        batchQuery.isSuccess && !batchQuery.isPlaceholderData && entry === undefined;
      return {
        data: isTokenEntry ? (entry as TileToken) : undefined,
        isLoading: batchQuery.isLoading || (batchQuery.isPlaceholderData && entry === undefined),
        isError: batchQuery.isError || (!isTokenEntry && !!entry) || missingAfterLoad,
        error:
          batchQuery.error ??
          (!isTokenEntry && entry
            ? new Error((entry as TileTokenError).error)
            : missingAfterLoad
              ? new Error(`No tile token returned for dataset ${id}`)
              : null),
      };
    });
  }, [uniqueIds, batchQuery.data, batchQuery.isLoading, batchQuery.isError, batchQuery.isSuccess, batchQuery.isPlaceholderData, batchQuery.error]);
}
