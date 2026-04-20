import { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import { toast } from 'sonner';
import { Map as MapGL, NavigationControl, ScaleControl } from '@vis.gl/react-maplibre';
import { useBasemaps, useMapDefaults, useTileConfig } from '@/hooks/use-settings';
import { findBasemapById, toMaplibreStyle } from '@/lib/basemap-utils';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { useTileTokens } from '@/hooks/use-tile-token';
import { getEnvConfig } from '@/lib/env';
import { useAuthStore } from '@/stores/auth-store';
import { useWebGLRecovery } from '@/hooks/use-webgl-recovery';
import { useTranslation } from 'react-i18next';
import { FeaturePopup } from '@/components/map/FeaturePopup';
import { MapCoordReadout } from '@/components/map/MapCoordReadout';
import { syncLayersToMap, toSyncInput, reorderBasemapLabels, getSourceId, getLayerId } from './map-sync';
import type { MapLibreEvent, MapMouseEvent } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';
import type { TileToken } from '@/api/tiles';
import 'maplibre-gl/dist/maplibre-gl.css';

/**
 * Map builder canvas — the editable composition surface used by `MapBuilderPage`.
 *
 * Renders multiple authenticated tile layers stacked over a basemap, with
 * imperative tile signing and live re-styling as the user edits paint, filters,
 * and layer order in the sidebar. Mousemove is throttled with
 * `requestAnimationFrame` to keep interaction responsive on layer-heavy maps.
 *
 * Pairs with the read-only `ViewerMap` for shared maps; both components share
 * the `layer-adapters` registry and `map-sync` helpers so styling renders
 * identically in editing and viewing modes.
 */
export interface SelectedFeature {
  properties: Record<string, unknown>;
  layerName: string;
  columnInfo: { name: string; type: string }[] | null;
}

interface BuilderMapProps {
  layers: MapLayerResponse[];
  basemapStyle: string;
  initialViewState?: {
    center_lng?: number | null;
    center_lat?: number | null;
    zoom?: number | null;
    bearing?: number;
    pitch?: number;
  };
  onMapRef?: (map: MaplibreMap | null) => void;
  showBasemapLabels?: boolean;
  /** Called when the user clicks a map feature. `null` when clicking empty space. */
  onFeatureSelect?: (feature: SelectedFeature | null) => void;
}

export function BuilderMap({
  layers,
  basemapStyle,
  initialViewState,
  onMapRef,
  showBasemapLabels = true,
  onFeatureSelect,
}: BuilderMapProps) {
  const { t } = useTranslation('builder');
  const mapRef = useRef<MaplibreMap | null>(null);
  const managedSourcesRef = useRef<Set<string>>(new Set());
  const errorHandlerRef = useRef<((e: { error: { message?: string; status?: number } }) => void) | null>(null);
  const lastOrderKeyRef = useRef('');
  const [mapReady, setMapReady] = useState(false);
  // `tilesIdle` drives the `data-tiles-loaded` DOM attribute on the outer
  // container. Mirrors the ViewerMap hook from 6a5f0181 so the Playwright
  // demo-smoke spec can poll a deterministic signal regardless of whether
  // /maps/:id resolved to BuilderMap (authenticated editor) or ViewerMap
  // (anonymous viewer) via MapViewerGate.
  const [tilesIdle, setTilesIdle] = useState(false);
  const [popupInfo, setPopupInfo] = useState<{
    longitude: number;
    latitude: number;
    features: { properties: Record<string, unknown>; layerName: string; columnInfo: { name: string; type: string }[] | null }[];
  } | null>(null);

  const { data: basemaps } = useBasemaps();
  const { data: mapDefaults } = useMapDefaults();
  const { data: tileConfig } = useTileConfig();
  const basemapEntry = findBasemapById(basemaps ?? [], basemapStyle);
  const fallbackUrl = 'https://tiles.openfreemap.org/styles/positron';
  const styleValue = useMemo(
    () => toMaplibreStyle(basemapEntry?.url ?? fallbackUrl, basemapEntry?.attribution),
    [basemapEntry?.url, basemapEntry?.attribution],
  );

  // Fetch tile tokens for all layers
  // Stable dataset ID list — only changes when layers are added/removed, not on paint edits
  const datasetIdKey = useMemo(() => layers.map((l) => l.dataset_id).join(','), [layers]);
  const datasetIds = useMemo(
    () => layers.map((l) => l.dataset_id).filter(Boolean),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on structural identity
    [datasetIdKey],
  );
  const tokenQueries = useTileTokens(datasetIds);

  // Stable string key for token changes — avoids per-render .map().join() in dep arrays
  const tokenSig = useMemo(
    () => tokenQueries.map((q) => q.data ? (q.data.kind === 'vector' ? q.data.sig : q.data.tile_url) : '').join(','),
    [tokenQueries],
  );

  // Build a lookup map from dataset_id -> TileToken, memoized by sig values
  const tokenMap = useMemo(() => {
    const map = new Map<string, TileToken>();
    const uniqueIds = [...new Set(datasetIds)];
    for (let i = 0; i < uniqueIds.length; i++) {
      const data = tokenQueries[i]?.data;
      if (data) {
        map.set(uniqueIds[i], data);
      }
    }
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetIds.join(','), tokenSig]);

  // Keep a ref to the latest sync inputs so style.load handler can access them
  const syncInputsRef = useRef({ layers, tokenMap, tileConfig, showBasemapLabels });
  syncInputsRef.current = { layers, tokenMap, tileConfig, showBasemapLabels };

  const layersRef = useRef(layers);
  layersRef.current = layers;

  // Cached queryable layer IDs — updated when layers change, read by click/mousemove handlers
  const queryLayerIdsRef = useRef<string[]>([]);

  // Track basemap URL to detect style changes
  const prevBasemapUrlRef = useRef<string | null>(null);

  const handleLoad = useCallback(
    (e: MapLibreEvent) => {
      const map = e.target;
      mapRef.current = map;
      setMapReady(true);

      // `idle` fires when no tiles are loading, no transitions are in
      // progress, and no animations are running. Flip the outer container's
      // data-tiles-loaded attribute on first idle so the demo-smoke spec can
      // replace its 2 s arbitrary wait with a deterministic signal. Matches
      // the ViewerMap hook from 6a5f0181.
      map.once('idle', () => setTilesIdle(true));

      // Absolutify URLs and attach auth header for raster tile requests
      map.setTransformRequest((url: string) => {
        const absUrl = url.startsWith('http') ? url : `${window.location.origin}${url}`;
        if (absUrl.includes('/raster-tiles/')) {
          const token = useAuthStore.getState().token;
          if (token) {
            return { url: absUrl, headers: { Authorization: `Bearer ${token}` } };
          }
        }
        return { url: absUrl };
      });

      // Filter expected tile errors (no-data tiles outside extent) and
      // surface anything else as a deduped toast so the editor knows a
      // real error has occurred (RES-3). Previously silenced in production.
      errorHandlerRef.current = (e: { error: { message?: string; status?: number } }) => {
        const msg = e.error?.message ?? '';
        const status = e.error?.status;
        if (msg.includes('source-') || status === 404) {
          return; // Expected no-data tile, suppress
        }
        if (import.meta.env.DEV) console.warn('[BuilderMap] Map error:', e.error);
        if (status === 401 || status === 403) {
          toast.error(t('builderMap.authError', { defaultValue: 'Session expired — reload the page to restore tile access.' }), {
            id: 'builder-map-auth-error',
          });
          return;
        }
        toast.error(t('builderMap.mapError', { defaultValue: 'Map tile error — some layers may not render correctly.' }), {
          id: 'builder-map-error',
        });
      };
      map.on('error', errorHandlerRef.current);

      onMapRef?.(map);
    },
    [onMapRef, t],
  );

  // Re-add data layers after basemap switch using style.load event
  useEffect(() => {
    const map = mapRef.current;
    const currentUrl = basemapEntry?.url ?? fallbackUrl;
    if (!map || prevBasemapUrlRef.current === null || prevBasemapUrlRef.current === currentUrl) {
      prevBasemapUrlRef.current = currentUrl;
      return;
    }
    prevBasemapUrlRef.current = currentUrl;

    const onStyleLoad = () => {
      const { layers: l, tokenMap: t, tileConfig: tc, showBasemapLabels: sbl } = syncInputsRef.current;
      managedSourcesRef.current = new Set();
      const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tc?.cdn_base_url || undefined;
      syncLayersToMap(map, l.map(toSyncInput), t, tileBaseUrl, managedSourcesRef, lastOrderKeyRef);
      reorderBasemapLabels(map, sbl);
    };

    map.once('style.load', onStyleLoad);
    // Inline style objects (raster basemaps) load synchronously before our
    // listener is registered. If the style is already loaded, run immediately.
    if (map.isStyleLoaded()) {
      map.off('style.load', onStyleLoad);
      onStyleLoad();
    }
    return () => {
      map.off('style.load', onStyleLoad);
    };
  }, [basemapEntry?.url]);

  // Update cached queryable layer IDs when layers change
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    queryLayerIdsRef.current = layers
      .filter((l) => l.visible && l.layer_type !== 'raster_geolens')
      .map((l) => getLayerId(l.id))
      .filter((id) => map.getLayer(id));
  }, [layers, mapReady]);

  // Click + mousemove handlers: popup and pointer cursor
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const handleClick = (e: MapMouseEvent) => {
      const queryLayers = queryLayerIdsRef.current;

      if (queryLayers.length === 0) {
        setPopupInfo(null);
        return;
      }

      const hits = map.queryRenderedFeatures(e.point, { layers: queryLayers });
      if (hits.length > 0) {
        const mappedFeatures = hits.map((feature) => {
          const layerId = feature.layer.id.replace(/^layer-/, '');
          const matchedLayer = layersRef.current.find((l) => l.id === layerId);
          return {
            properties: (feature.properties ?? {}) as Record<string, unknown>,
            layerName: matchedLayer?.display_name || matchedLayer?.dataset_name || t('common:viewer.featureFallback'),
            columnInfo: matchedLayer?.dataset_column_info ?? null,
          };
        });
        setPopupInfo({
          longitude: e.lngLat.lng,
          latitude: e.lngLat.lat,
          features: mappedFeatures,
        });
        onFeatureSelect?.(mappedFeatures[0]);
      } else {
        setPopupInfo(null);
        onFeatureSelect?.(null);
      }
    };

    let rafId = 0;
    const handleMouseMove = (e: MapMouseEvent) => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        if (!map.isStyleLoaded()) return;
        const queryLayers = queryLayerIdsRef.current;

        if (queryLayers.length === 0) {
          map.getCanvas().style.cursor = '';
          return;
        }

        const features = map.queryRenderedFeatures(e.point, { layers: queryLayers });
        map.getCanvas().style.cursor = features.length > 0 ? 'pointer' : '';
      });
    };

    map.on('click', handleClick);
    map.on('mousemove', handleMouseMove);
    return () => {
      map.off('click', handleClick);
      cancelAnimationFrame(rafId);
      map.off('mousemove', handleMouseMove);
      if (map.getCanvas()) map.getCanvas().style.cursor = '';
    };
  }, [mapReady, t]);

  // Stable string key for visibility changes — avoids per-render allocations
  const visibilityKey = useMemo(() => layers.map((l) => l.visible).join(','), [layers]);

  // Clear popup when layer visibility changes
  useEffect(() => {
    setPopupInfo(null);
  }, [visibilityKey]);

  // Structural key: only changes when layers are added/removed/reordered/toggled —
  // NOT on paint/filter edits (those are handled incrementally by use-layer-map-sync).
  const structuralKey = useMemo(
    () => layers.map((l) => `${l.id}:${l.visible}:${l.dataset_id}`).join(','),
    [layers],
  );

  // Sync layers to map — runs on structural changes (add/remove/visibility) and token refresh.
  // Paint/filter/opacity edits are handled imperatively by use-layer-map-sync.ts.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url || undefined;
    syncLayersToMap(map, layers.map(toSyncInput), tokenMap, tileBaseUrl, managedSourcesRef, lastOrderKeyRef);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structuralKey, mapReady, tileConfig?.cdn_base_url, tokenMap]);

  // Reorder basemap labels — only when showBasemapLabels actually changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    reorderBasemapLabels(map, showBasemapLabels);
  }, [showBasemapLabels, mapReady]);

  // Update tile URLs in-place when tokens refresh (vector only)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url;

    for (const layer of layers) {
      const token = tokenMap.get(layer.dataset_id) ?? null;
      // Raster tile URLs use nginx auth-check subrequest — nothing to refresh
      if (token?.kind === 'raster') continue;
      const sourceId = getSourceId(layer.id);
      const source = map.getSource(sourceId);
      if (source && 'setTiles' in source) {
        const newUrl = buildSignedTileUrl(layer.dataset_table_name, token, tileBaseUrl);
        (source as maplibregl.VectorTileSource).setTiles([newUrl]);
      }
    }
  }, [tokenMap, layers, mapReady, tileConfig?.cdn_base_url]);

  // Track whether we've restored a saved view (skip auto-fit on initial load)
  const hasSavedView = !!(initialViewState?.center_lng != null && initialViewState?.center_lat != null);
  const initialFitDoneRef = useRef(false);
  const prevLayerCountRef = useRef(layers.length);

  // Auto-fit to visible layers (skip on initial load if saved view exists)
  const layerVisibilityKey = useMemo(() => layers.map((l) => `${l.id}:${l.visible}`).join(','), [layers]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const layerCountChanged = layers.length !== prevLayerCountRef.current;
    prevLayerCountRef.current = layers.length;

    // First auto-fit trigger: skip if we have a saved view to restore
    if (!initialFitDoneRef.current) {
      initialFitDoneRef.current = true;
      if (hasSavedView) return; // MapGL already positioned via initialViewState
    }

    // Only fit when layer count actually changed (add/remove/toggle)
    if (!layerCountChanged) return;

    const visibleLayers = layers.filter((l) => l.visible && l.dataset_extent_bbox);
    if (visibleLayers.length === 0) return;

    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;

    for (const l of visibleLayers) {
      const bbox = l.dataset_extent_bbox!;
      if (bbox[0] < minX) minX = bbox[0];
      if (bbox[1] < minY) minY = bbox[1];
      if (bbox[2] > maxX) maxX = bbox[2];
      if (bbox[3] > maxY) maxY = bbox[3];
    }

    map.fitBounds(
      [
        [minX, minY],
        [maxX, maxY],
      ],
      { padding: 40, maxZoom: 18, duration: 0 },
    );

    // Clamp zoom to 2+ so tiles render (ST_AsMVT fails at z0/z1 for complex geometries)
    if (map.getZoom() < 2) {
      map.setZoom(2);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- hasSavedView/layers read from refs, not reactive deps
  }, [layers.length, layerVisibilityKey, mapReady]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (mapRef.current && errorHandlerRef.current) {
        mapRef.current.off('error', errorHandlerRef.current);
      }
      onMapRef?.(null);
    };
  }, [onMapRef]);

  const defaultView = {
    longitude: initialViewState?.center_lng ?? mapDefaults?.center_lng ?? 0,
    latitude: initialViewState?.center_lat ?? mapDefaults?.center_lat ?? 20,
    zoom: Math.max(initialViewState?.zoom ?? mapDefaults?.zoom ?? 2, 2),
    bearing: initialViewState?.bearing ?? 0,
    pitch: initialViewState?.pitch ?? 0,
  };

  const { contextLost, reload } = useWebGLRecovery(mapRef, mapReady);

  return (
    <div
      className="relative h-full w-full"
      data-tiles-loaded={tilesIdle ? 'true' : 'false'}
    >
      <MapGL
        initialViewState={defaultView}
        mapStyle={styleValue as string}
        styleDiffing={false}
        // Required for thumbnail capture via canvas.toBlob()
        canvasContextAttributes={{ preserveDrawingBuffer: true }}
        style={{ width: '100%', height: '100%' }}
        minZoom={1}
        onLoad={handleLoad}
        aria-label="Map builder"
      >
        <NavigationControl position="bottom-right" />
        <ScaleControl position="bottom-left" maxWidth={100} unit="metric" />
        {popupInfo && (
          <FeaturePopup
            key={`${popupInfo.longitude}-${popupInfo.latitude}`}
            longitude={popupInfo.longitude}
            latitude={popupInfo.latitude}
            features={popupInfo.features}
            onClose={() => setPopupInfo(null)}
          />
        )}
      </MapGL>
      <MapCoordReadout map={mapRef.current} />
      {!mapReady && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/50">
          <div className="text-sm text-muted-foreground animate-pulse">{t('builderMap.loading', { defaultValue: 'Loading map…' })}</div>
        </div>
      )}
      {contextLost && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80">
          <div className="text-center space-y-2">
            <p className="text-sm text-muted-foreground">{t('errors.mapMessage')}</p>
            <button type="button" onClick={reload} className="text-sm underline text-primary hover:text-primary/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring rounded px-1">{t('common.reload')}</button>
          </div>
        </div>
      )}
    </div>
  );
}
