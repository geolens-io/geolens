import { useState, useEffect, useCallback } from 'react';

export type HeroState = 'loading' | 'loaded' | 'error';

interface UseHeroStateOptions {
  datasetId: string | undefined;
  recordType: string | null | undefined;
  hasTileUrl: boolean;
}

export function useHeroState({ datasetId, recordType, hasTileUrl }: UseHeroStateOptions) {
  const isRasterOrVrt = recordType === 'raster_dataset' || recordType === 'vrt_dataset';
  const [heroState, setHeroState] = useState<HeroState>('loading');
  const [retryCount, setRetryCount] = useState(0);
  const [mapKey, setMapKey] = useState(0);

  // 10s timeout: if raster/VRT map never calls onMapReady, show error
  useEffect(() => {
    if (!isRasterOrVrt || heroState !== 'loading') return;
    const timer = setTimeout(() => {
      setHeroState('error');
    }, 10_000);
    return () => clearTimeout(timer);
  }, [heroState, isRasterOrVrt]);

  // Retry handler for raster/VRT hero error state
  const handleRetry = useCallback(() => {
    setRetryCount(prev => prev + 1);
    setHeroState('loading');
    setMapKey(prev => prev + 1);
  }, []);

  // Reset hero state when dataset changes
  useEffect(() => {
    setHeroState('loading');
    setRetryCount(0);
    setMapKey(0);
  }, [datasetId]);

  // Raster with no tile_url: skip to 'loaded' immediately (no tiles to wait for)
  useEffect(() => {
    if (recordType === 'raster_dataset' && !hasTileUrl) {
      setHeroState('loaded');
    }
  }, [datasetId, recordType, hasTileUrl]);

  return {
    isRasterOrVrt,
    heroState,
    retryCount,
    mapKey,
    handleRetry,
    onMapReady: useCallback(() => setHeroState('loaded'), []),
    onTileError: useCallback(() => setHeroState('error'), []),
  };
}
