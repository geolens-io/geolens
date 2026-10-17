import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { getTileTokensBatch } from '@/api/tiles';
import type { TileToken, TileTokenBatchResponse } from '@/api/tiles';
import { queryKeys } from '@/lib/query-keys';
import type { SharedLayerResponse } from '@/types/api';

// While the mint endpoint is down, keep retrying at this cadence.
// TanStack's bounded `retry` covers the fast attempts; this covers a longer
// outage. Without it the
// interval below would return false (no data → no TTL to derive) and a viewer
// that failed its first mint would never recover on its own.
const TOKEN_RETRY_INTERVAL_MS = 60_000;

/**
 * Refresh at 80% of the minimum vector-token TTL, floored at 30 s. Raster
 * tokens have no `expires_in` (their tile_url is stable), so a map with no
 * vector tokens skips the refresh cycle entirely.
 */
function refreshIntervalMs(data: TileTokenBatchResponse | undefined): number | false {
  let minTtl = Infinity;
  for (const entry of Object.values(data?.tokens ?? {})) {
    if ('kind' in entry && entry.kind === 'vector') {
      minTtl = Math.min(minTtl, entry.expires_in);
    }
  }
  if (!Number.isFinite(minTtl)) return false;
  return Math.max(minTtl * 800, 30_000);
}

/**
 * Manages tile token fetching and auto-refresh for the viewer map.
 * Returns the current token map and whether a fetch error occurred.
 *
 * It uses the same TanStack path as the builder. A hand-rolled `useState` +
 * `setTimeout` loop would be the OPPOSITE refresh policy: Chrome throttles a
 * hidden tab's timers but still fires them, so a refresh landing while hidden
 * would push a fresh token URL at a paused map (MapLibre drops the
 * `setTiles` reload while the source's TileManager is paused).
 * `refetchIntervalInBackground: false` means a hidden tab gets ZERO refreshes,
 * and the visible-edge re-mint (`useVisibleTileTokenRefresh` in ViewerMap)
 * owns the tab-return case. TanStack owns the timer and cancellation, and
 * ViewerMap's `useInvalidateTileTokens()` (WebGL context restore) reaches the
 * viewer's tokens.
 */
export function useViewerTokens({
  layers,
  embedToken,
}: {
  layers: SharedLayerResponse[];
  embedToken?: string;
}) {
  const { t } = useTranslation('common');

  const layerDatasetIds = useMemo(
    () => [...new Set(layers.map((l) => l.dataset_id).filter(Boolean))],
    [layers],
  );
  // Sorted so a layer reorder reuses the cached batch instead of re-minting.
  const sortedIds = useMemo(() => [...layerDatasetIds].sort().join(','), [layerDatasetIds]);

  // Embed mode does not skip token fetching — the batch
  // endpoint accepts X-Embed-Token, so embeds get the same raster/DEM tile
  // descriptors (bounds, resolution-derived maxzoom) as normal viewers instead
  // of building the terrain source from empty defaults.
  const query = useQuery({
    queryKey: queryKeys.tileTokens.viewerBatch(sortedIds, embedToken ?? ''),
    queryFn: () => getTileTokensBatch(layerDatasetIds, embedToken),
    enabled: layerDatasetIds.length > 0,
    staleTime: 60_000,
    // Bounded backoff for a transient hiccup (parity with useTileTokens).
    retry: 3,
    refetchInterval: (q) =>
      q.state.status === 'error' ? TOKEN_RETRY_INTERVAL_MS : refreshIntervalMs(q.state.data),
    // Explicit because it is the whole policy — a hidden tab must not
    // refresh, since MapLibre drops the resulting setTiles reload while the
    // source's TileManager is paused.
    refetchIntervalInBackground: false,
  });

  // Identity is stable while TanStack's structural sharing keeps `data` stable
  // (an unchanged sig across a refresh), so ViewerMap's token→setTiles effect
  // only re-runs when a token actually rotated.
  const tokenMap = useMemo(() => {
    const map = new Map<string, TileToken>();
    for (const [datasetId, entry] of Object.entries(query.data?.tokens ?? {})) {
      if ('kind' in entry) map.set(datasetId, entry);
    }
    return map;
  }, [query.data]);

  const tokenError = query.isError;

  // On-demand re-mint for the tile 401/403 recovery path. Stable
  // identity so map error handlers can depend on it without re-registering.
  const refetchRef = useRef(query.refetch);
  refetchRef.current = query.refetch;
  const refreshTokens = useCallback(() => {
    void refetchRef.current();
  }, []);

  // Surface tile token fetch failures as a user-visible toast
  useEffect(() => {
    if (tokenError) {
      toast.error(t('viewer.tokenError', { defaultValue: 'Failed to load map layer tokens — some layers may not display.' }), {
        id: 'viewer-token-error',
      });
    }
  }, [tokenError, t]);

  return { tokenMap, tokenError, refreshTokens };
}
