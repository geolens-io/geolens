import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import {
  ensureRasterDemTerrainSource,
  isTerrainCapableDemLayer,
  normalizeTerrainExaggeration,
  TERRAIN_SOURCE_ID,
} from '@/components/builder/map-sync';
import type { MapTerrainConfig, SharedLayerResponse } from '@/types/api';

/**
 * Applies persisted shared-map terrain configuration to the viewer map.
 * The built-in TerrainControl remains a local viewer toggle only; persisted
 * source/exaggeration state comes from the saved map payload.
 */
export function useViewerTerrain({
  layers,
  mapRef,
  mapReady,
  terrainConfig,
}: {
  layers: SharedLayerResponse[];
  mapRef: React.RefObject<MaplibreMap | null>;
  mapReady: boolean;
  terrainConfig?: MapTerrainConfig | null;
}) {
  const [terrainReady, setTerrainReady] = useState(false);

  const terrainLayer = useMemo(
    () => terrainConfig?.source_dataset_id
      ? layers.find(
        (layer) => layer.dataset_id === terrainConfig.source_dataset_id && isTerrainCapableDemLayer(layer),
      ) ?? null
      : null,
    [layers, terrainConfig?.source_dataset_id],
  );

  const terrainStateRef = useRef({ terrainConfig, terrainLayer });
  terrainStateRef.current = { terrainConfig, terrainLayer };

  const applyTerrain = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) {
      setTerrainReady(false);
      return;
    }

    const { terrainConfig: currentTerrainConfig, terrainLayer: currentTerrainLayer } = terrainStateRef.current;
    if (!currentTerrainConfig?.enabled || !currentTerrainLayer?.tile_url) {
      map.setTerrain(null);
      setTerrainReady(false);
      return;
    }

    ensureRasterDemTerrainSource(map, currentTerrainLayer.tile_url);
    map.setTerrain({
      source: TERRAIN_SOURCE_ID,
      exaggeration: normalizeTerrainExaggeration(currentTerrainConfig.exaggeration),
    });
    setTerrainReady(true);
  }, [mapRef]);

  useEffect(() => {
    if (!mapReady) {
      setTerrainReady(false);
      return;
    }
    applyTerrain();
  }, [
    applyTerrain,
    mapReady,
    terrainConfig?.enabled,
    terrainConfig?.source_dataset_id,
    terrainConfig?.exaggeration,
    terrainLayer?.tile_url,
  ]);

  const reseedTerrainOnStyleLoad = useCallback(() => {
    applyTerrain();
  }, [applyTerrain]);

  return { terrainReady, reseedTerrainOnStyleLoad };
}
