import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import {
  ensureRasterDemTerrainSource,
  isTerrainCapableDemLayer,
  normalizeTerrainExaggeration,
  TERRAIN_SOURCE_ID,
} from '@/components/builder/map-sync';
import type { MapTerrainConfig, SharedLayerResponse } from '@/types/api';
import type { TileToken } from '@/api/tiles';

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
  tokenMap,
}: {
  layers: SharedLayerResponse[];
  mapRef: React.RefObject<MaplibreMap | null>;
  mapReady: boolean;
  terrainConfig?: MapTerrainConfig | null;
  tokenMap?: Map<string, TileToken>;
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
    const terrainDatasetId = currentTerrainConfig?.source_dataset_id;
    const terrainToken = terrainDatasetId ? tokenMap?.get(terrainDatasetId) : null;
    const terrainTileUrl = terrainToken?.kind === 'raster'
      ? terrainToken.tile_url
      : currentTerrainLayer?.tile_url;
    if (!currentTerrainConfig?.enabled || !terrainDatasetId || !terrainTileUrl) {
      map.setTerrain(null);
      setTerrainReady(false);
      return;
    }

    ensureRasterDemTerrainSource(map, terrainTileUrl, terrainToken?.kind === 'raster'
      ? {
        tileSize: terrainToken.tile_size,
        minzoom: terrainToken.minzoom,
        maxzoom: terrainToken.maxzoom,
        bounds: terrainToken.bounds,
      }
      : {});
    map.setTerrain({
      source: TERRAIN_SOURCE_ID,
      exaggeration: normalizeTerrainExaggeration(currentTerrainConfig.exaggeration),
    });
    setTerrainReady(true);
  }, [mapRef, tokenMap]);

  useEffect(() => {
    if (!mapReady) {
      setTerrainReady(false);
      return;
    }
    const map = mapRef.current;
    applyTerrain();
    if (map && !map.isStyleLoaded()) {
      map.once('idle', applyTerrain);
      return () => {
        map.off('idle', applyTerrain);
      };
    }
  }, [
    applyTerrain,
    mapRef,
    mapReady,
    terrainConfig?.enabled,
    terrainConfig?.source_dataset_id,
    terrainConfig?.exaggeration,
    terrainLayer?.tile_url,
    tokenMap,
  ]);

  const reseedTerrainOnStyleLoad = useCallback(() => {
    const map = mapRef.current;
    if (!map) {
      applyTerrain();
      return;
    }
    map.once('idle', applyTerrain);
  }, [applyTerrain, mapRef]);

  return { terrainReady, reseedTerrainOnStyleLoad };
}
