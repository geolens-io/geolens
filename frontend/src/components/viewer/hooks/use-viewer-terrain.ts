import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import {
  ensureRasterDemTerrainSource,
  normalizeTerrainExaggeration,
  TERRAIN_SOURCE_ID,
} from '@/components/builder/map-sync';
import { resolveTerrainSourceLayer } from '@/components/builder/map-stack';
import { maybeWarnSmallDemCoverage, resetSmallDemWarning } from '@/components/builder/terrain-coverage';
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

  // fix(HT-12): resolve through the SAME shared resolver the builder uses
  // (deterministic duplicate semantics included) instead of a local find.
  const terrainLayer = useMemo(
    () => resolveTerrainSourceLayer(layers, terrainConfig) ?? null,
    [layers, terrainConfig],
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
    // fix(HT-12): honor the bound DEM layer's saved visibility the same way the
    // builder does (BuilderMap applyTerrainConfig: effectiveTerrainEnabled =
    // enabled && demLayerVisible). Previously the viewer (and embeds, which
    // reuse this hook) rendered terrain from a hidden DEM row, so a saved map
    // could show no terrain in the builder and active terrain in the viewer.
    const demLayerVisible = currentTerrainLayer?.visible !== false;
    if (!currentTerrainConfig?.enabled || !terrainDatasetId || !terrainTileUrl || !demLayerVisible) {
      map.setTerrain(null);
      setTerrainReady(false);
      // #186 (b): terrain off → clear the small-DEM warning dedupe.
      resetSmallDemWarning(map);
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

    // #186 (b): warn once per enable when the DEM covers only a small slice of
    // the viewport. demBounds come from the raster token (the only bounds source
    // available here; SharedLayerResponse carries no bounds). When the terrain is
    // driven by a non-raster token (no bounds), the guard simply no-ops.
    const demBounds = terrainToken?.kind === 'raster' ? terrainToken.bounds : null;
    resetSmallDemWarning(map, terrainDatasetId);
    // fix(#430 V-06): suppress the builder-oriented small-DEM advice toast for viewers —
    // "zoom in" / "drape over Copernicus GLO-30" isn't actionable read-only.
    maybeWarnSmallDemCoverage({
      map,
      demBounds,
      dedupeKey: terrainDatasetId,
      audience: 'viewer',
    });
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
    terrainLayer?.visible,
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
