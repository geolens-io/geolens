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
 * The reveal-gate predicate ViewerMap uses: terrain is EXPECTED (worth holding
 * the veil for) only when the config is enabled AND a terrain-capable DEM
 * rendering resolves AND that rendering is saved visible — the same conditions
 * useViewerTerrain applies before draping the mesh. A pure export so a
 * regression here (which degrades to a silent 4s veil) stays unit-testable.
 */
export function isViewerTerrainExpected(
  layers: SharedLayerResponse[],
  terrainConfig?: MapTerrainConfig | null,
): boolean {
  const layer = resolveTerrainSourceLayer(layers, terrainConfig);
  return Boolean(terrainConfig?.enabled) && !!layer && layer.visible !== false;
}

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
  demLayerLiveVisible = true,
}: {
  layers: SharedLayerResponse[];
  mapRef: React.RefObject<MaplibreMap | null>;
  mapReady: boolean;
  terrainConfig?: MapTerrainConfig | null;
  tokenMap?: Map<string, TileToken>;
  /**
   * fix(#452): the bound DEM's LIVE visibility from the viewer legend's eye
   * toggle (ViewerMap resolves it from visibleLayers). The saved `visible`
   * check below covers maps saved with a hidden DEM (HT-12), but the legend
   * toggle is a client-side override the saved flag never reflects — without
   * this the mesh stayed extruded after the viewer hid the DEM live.
   */
  demLayerLiveVisible?: boolean;
}) {
  const [terrainReady, setTerrainReady] = useState(false);

  // fix(HT-12): resolve through the SAME shared resolver the builder uses
  // (deterministic duplicate semantics included) instead of a local find.
  const terrainLayer = useMemo(
    () => resolveTerrainSourceLayer(layers, terrainConfig) ?? null,
    [layers, terrainConfig],
  );

  // fix(#451): whether the shared payload carries ANY rendering of the bound
  // dataset. Distinguishes "row filtered out / metadata not loaded" (terrain
  // may still seed from the raster token — the share-token embed of a private
  // DEM dataset depends on this) from "rows exist but none is a visible
  // terrain-capable DEM" (terrain must stay off, matching legend + reveal gate).
  const boundDatasetHasRows = useMemo(
    () => layers.some((l) => l.dataset_id === terrainConfig?.source_dataset_id),
    [layers, terrainConfig?.source_dataset_id],
  );

  const terrainStateRef = useRef({ terrainConfig, terrainLayer, boundDatasetHasRows, demLayerLiveVisible });
  terrainStateRef.current = { terrainConfig, terrainLayer, boundDatasetHasRows, demLayerLiveVisible };

  const applyTerrain = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) {
      setTerrainReady(false);
      return;
    }

    const {
      terrainConfig: currentTerrainConfig,
      terrainLayer: currentTerrainLayer,
      boundDatasetHasRows: currentBoundDatasetHasRows,
      demLayerLiveVisible: currentLiveVisible,
    } = terrainStateRef.current;
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
    // fix(#451): when the payload DOES carry rows for the bound dataset but
    // none resolves as a terrain-capable DEM (legacy/corrupt binding), the mesh
    // must stay off — the reveal gate and legend already say "no terrain" in
    // that state. When it carries NO rows (filtered private dataset in a
    // share-token embed, or metadata still loading), keep seeding from the
    // raster token as before.
    // fix(#452): AND the live legend-toggle state, so hiding the DEM in the
    // viewer flattens the mesh just like the builder's eye toggle does.
    const demLayerVisible = (currentTerrainLayer
      ? currentTerrainLayer.visible !== false
      : !currentBoundDatasetHasRows) && currentLiveVisible;
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
    boundDatasetHasRows,
    demLayerLiveVisible,
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
