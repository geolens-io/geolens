import { useQuery, useQueries } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { getTileToken } from '@/api/tiles';
import type { TileToken } from '@/api/tiles';

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
 * Fetch tile tokens for multiple datasets (e.g. BuilderMap with many layers).
 * Deduplicates IDs and returns an array of query results.
 */
export function useTileTokens(datasetIds: string[]) {
  const uniqueIds = [...new Set(datasetIds.filter(Boolean))];
  return useQueries({
    queries: uniqueIds.map((id) => ({
      queryKey: queryKeys.tileTokens.token(id),
      queryFn: () => getTileToken(id),
      refetchInterval: (query: { state: { data: TileToken | undefined } }) => {
        const d = query.state.data;
        if (!d) return false;
        if (d.kind !== 'vector') return false;
        return Math.max(d.expires_in * 800, 30_000);
      },
      staleTime: 60_000,
    })),
  });
}
