import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { getTileTokensBatch } from '@/api/tiles';
import type { TileToken, VectorTileToken } from '@/api/tiles';
import type { SharedLayerResponse } from '@/types/api';

/** Fetch tile tokens in a single batch using API key auth. */
async function fetchTokensWithApiKey(
  datasetIds: string[],
  apiKey: string,
): Promise<Map<string, TileToken>> {
  const response = await getTileTokensBatch(datasetIds, apiKey);
  const map = new Map<string, TileToken>();
  for (const [datasetId, entry] of Object.entries(response.tokens)) {
    if ('kind' in entry) {
      map.set(datasetId, entry);
    }
  }
  return map;
}

/** Fetch tile tokens in a single batch (anonymous / JWT auth). */
async function fetchTokensBatch(
  datasetIds: string[],
): Promise<Map<string, TileToken>> {
  const response = await getTileTokensBatch(datasetIds);
  const map = new Map<string, TileToken>();
  for (const [datasetId, entry] of Object.entries(response.tokens)) {
    if ('kind' in entry) {
      map.set(datasetId, entry);
    }
  }
  return map;
}

/**
 * Manages tile token fetching and auto-refresh for the viewer map.
 * Returns the current token map and whether a fetch error occurred.
 */
export function useViewerTokens({
  layers,
  apiKey,
  embedToken,
}: {
  layers: SharedLayerResponse[];
  apiKey?: string;
  embedToken?: string;
}) {
  const { t } = useTranslation('common');
  const [tokenMap, setTokenMap] = useState<Map<string, TileToken>>(new Map());
  const [tokenError, setTokenError] = useState(false);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const layerDatasetIds = useMemo(
    () => [...new Set(layers.map((l) => l.dataset_id).filter(Boolean))],
    [layers],
  );

  useEffect(() => {
    if (embedToken || layerDatasetIds.length === 0) return;

    let cancelled = false;
    let retryAttempt = 0;

    async function fetchTokens() {
      try {
        const newMap = apiKey
          ? await fetchTokensWithApiKey(layerDatasetIds, apiKey)
          : await fetchTokensBatch(layerDatasetIds);

        if (cancelled) return;
        setTokenMap(newMap);
        setTokenError(false);
        retryAttempt = 0;

        // Refresh at 80% of the minimum vector-token TTL. Raster tokens
        // have no expires_in (the tile_url is stable), so if there are no
        // vector tokens in the map, skip the refresh cycle entirely.
        const vectorTtls = [...newMap.values()]
          .filter((t): t is VectorTileToken => t.kind === 'vector')
          .map((t) => t.expires_in);
        if (vectorTtls.length > 0) {
          const minTtl = Math.min(...vectorTtls);
          const refreshMs = Math.max(minTtl * 800, 30_000);
          if (refreshTimerRef.current) {
            clearTimeout(refreshTimerRef.current);
          }
          refreshTimerRef.current = setTimeout(() => {
            if (!cancelled) fetchTokens();
          }, refreshMs);
        }
      } catch (err) {
        if (import.meta.env.DEV) console.warn('ViewerMap: failed to fetch tile tokens', err);
        setTokenError(true);
        // Exponential backoff retry: 5s, 10s, 20s, 40s, capped at 60s
        retryAttempt++;
        const backoffMs = Math.min(5_000 * Math.pow(2, retryAttempt - 1), 60_000);
        refreshTimerRef.current = setTimeout(() => {
          if (!cancelled) fetchTokens();
        }, backoffMs);
      }
    }

    fetchTokens();

    return () => {
      cancelled = true;
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };
  }, [embedToken, apiKey, layerDatasetIds]);

  // Surface tile token fetch failures as a user-visible toast
  useEffect(() => {
    if (tokenError) {
      toast.error(t('viewer.tokenError', { defaultValue: 'Failed to load map layer tokens — some layers may not display.' }), {
        id: 'viewer-token-error',
      });
    }
  }, [tokenError, t]);

  return { tokenMap, tokenError };
}
