import { useEffect, useRef, useState } from 'react';
import { getTileTokenWithApiKey, getTileTokensBatch } from '@/api/tiles';
import type { TileToken, VectorTileToken } from '@/api/tiles';

/**
 * Encapsulates tile-token fetching with TTL-based refresh and exponential
 * backoff retry. When `embedToken` is set or `layerDatasetIds` is empty,
 * token fetching is skipped entirely.
 */
export function useTileTokens(
  layerDatasetIds: string[],
  options?: { apiKey?: string; embedToken?: string },
) {
  const apiKey = options?.apiKey;
  const embedToken = options?.embedToken;

  const tokenMapRef = useRef<Map<string, TileToken>>(new Map());
  const [tokenVersion, setTokenVersion] = useState(0);
  const [tokenError, setTokenError] = useState(false);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tokenRetryRef = useRef(5000);

  useEffect(() => {
    if (embedToken || layerDatasetIds.length === 0) return;

    let cancelled = false;

    async function fetchTokens() {
      try {
        let newMap: Map<string, TileToken>;

        if (apiKey) {
          const results = await Promise.all(
            layerDatasetIds.map((id) => getTileTokenWithApiKey(id, apiKey!)),
          );
          newMap = new Map<string, TileToken>();
          for (let i = 0; i < layerDatasetIds.length; i++) {
            newMap.set(layerDatasetIds[i], results[i]);
          }
        } else {
          const response = await getTileTokensBatch(layerDatasetIds);
          newMap = new Map<string, TileToken>();
          for (const [datasetId, entry] of Object.entries(response.tokens)) {
            if ('kind' in entry) {
              newMap.set(datasetId, entry);
            }
          }
        }

        if (cancelled) return;
        tokenMapRef.current = newMap;
        tokenRetryRef.current = 5000;
        setTokenVersion((v) => v + 1);

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
        console.error('[ViewerMap] Failed to fetch tile tokens:', err);
        setTokenError(true);
        refreshTimerRef.current = setTimeout(() => {
          if (!cancelled) fetchTokens();
        }, tokenRetryRef.current);
        tokenRetryRef.current = Math.min(tokenRetryRef.current * 2, 60_000);
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

  return { tokenMapRef, tokenVersion, tokenError };
}
