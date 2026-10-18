import { useState, useEffect, useCallback, useRef } from 'react';

type HeroState = 'loading' | 'loaded' | 'error';

interface UseHeroStateOptions {
  datasetId: string | undefined;
  recordType: string | null | undefined;
  hasTileUrl: boolean;
}

export function useHeroState({ datasetId, recordType, hasTileUrl }: UseHeroStateOptions) {
  const isRasterOrVrt = recordType === 'raster_dataset' || recordType === 'vrt_dataset';
  // Vector previews report readiness/errors too (soft-ready immediately, then
  // confirm via sourcedata) — only table datasets have no hero map to track.
  const tracksHero = isRasterOrVrt || recordType === 'vector_dataset';
  const [heroState, setHeroState] = useState<HeroState>('loading');
  const [retryCount, setRetryCount] = useState(0);
  const [mapKey, setMapKey] = useState(0);

  // 10s timeout: if the tracked hero map never calls onMapReady, show error
  useEffect(() => {
    if (!tracksHero || heroState !== 'loading') return;
    const timer = setTimeout(() => {
      setHeroState('error');
    }, 10_000);
    return () => clearTimeout(timer);
  }, [heroState, tracksHero, datasetId]);

  // Retry handler for raster/VRT hero error state
  const handleRetry = useCallback(() => {
    setRetryCount(prev => prev + 1);
    setHeroState('loading');
    setMapKey(prev => prev + 1);
  }, []);

  // A completed replacement remounts the hero as a manual retry does (fresh
  // heroState + mapKey), but it is NOT a failed-tile retry: routing it through
  // handleRetry would spend the 3-attempt manual-retry budget on a SUCCESS and
  // leave a later genuine tile failure with Retry exhausted. Reset retryCount
  // instead of incrementing: a successful replace hands the user a fresh budget.
  const handleReplaceComplete = useCallback(() => {
    setRetryCount(0);
    setHeroState('loading');
    setMapKey(prev => prev + 1);
  }, []);

  // Reset hero state when the dataset CHANGES — skip the initial mount, where
  // state is already fresh and a map that reports ready in the same commit
  // (cached lazy chunk) would be clobbered back to 'loading'.
  const mountedForRef = useRef(datasetId);
  useEffect(() => {
    if (mountedForRef.current === datasetId) return;
    mountedForRef.current = datasetId;
    setHeroState('loading');
    setRetryCount(0);
    setMapKey(0);
  }, [datasetId]);

  // Raster with no tile_url: skip to 'loaded' immediately (no tiles to wait for)
  useEffect(() => {
    if (isRasterOrVrt && !hasTileUrl) {
      setHeroState('loaded');
    }
  }, [datasetId, recordType, hasTileUrl, isRasterOrVrt]);

  return {
    isRasterOrVrt,
    tracksHero,
    heroState,
    retryCount,
    mapKey,
    handleRetry,
    handleReplaceComplete,
    onMapReady: useCallback(() => setHeroState('loaded'), []),
    onTileError: useCallback(() => setHeroState('error'), []),
  };
}
