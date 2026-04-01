import { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import { Map as MapGL, NavigationControl } from '@vis.gl/react-maplibre';
import { useBasemaps, useMapDefaults, useTileConfig } from '@/hooks/use-settings';
import { findBasemapById, toMaplibreStyle } from '@/lib/basemap-utils';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { useTileTokens } from '@/hooks/use-tile-token';
import { getEnvConfig } from '@/lib/env';
import { useAuthStore } from '@/stores/auth-store';
import { useTranslation } from 'react-i18next';
import { FeaturePopup } from '@/components/map/FeaturePopup';
import { syncLayersToMap, reorderDataLayers, reorderBasemapLabels, getSourceId, getLayerId } from './map-sync';
import type { MapLibreEvent, MapMouseEvent } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';
import type { TileToken } from '@/api/tiles';
import 'maplibre-gl/dist/maplibre-gl.css';

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
}

export function BuilderMap({
  layers,
  basemapStyle,
  initialViewState,
  onMapRef,
  showBasemapLabels = true,
}: BuilderMapProps) {
  const { t } = useTranslation('builder');
  const mapRef = useRef<MaplibreMap | null>(null);
  const managedSourcesRef = useRef<Set<string>>(new Set());
  const [mapReady, setMapReady] = useState(false);
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
  const datasetIds = useMemo(
    () => layers.map((l) => l.dataset_id).filter(Boolean),
    [layers],
  );
  const tokenQueries = useTileTokens(datasetIds);

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
  }, [datasetIds.join(','), tokenQueries.map((q) => q.data ? (q.data.kind === 'vector' ? q.data.sig : q.data.tile_url) : '').join(',')]);

  // Keep a ref to the latest sync inputs so style.load handler can access them
  const syncInputsRef = useRef({ layers, tokenMap, tileConfig, showBasemapLabels });
  syncInputsRef.current = { layers, tokenMap, tileConfig, showBasemapLabels };

  // Track basemap URL to detect style changes
  const prevBasemapUrlRef = useRef<string | null>(null);

  const handleLoad = useCallback(
    (e: MapLibreEvent) => {
      const map = e.target;
      mapRef.current = map;
      setMapReady(true);

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

      // Suppress expected raster tile errors (no-data tiles outside extent)
      map.on('error', (e: { error: { message?: string; status?: number } }) => {
        const msg = e.error?.message ?? '';
        // Only suppress errors from our managed tile sources
        if (msg.includes('source-') || e.error?.status === 404) {
          return; // Expected no-data tile, suppress
        }
        // Non-tile errors: let MapLibre default handling proceed
        if (import.meta.env.DEV) console.warn('[BuilderMap] Map error:', e.error);
      });

      onMapRef?.(map);
    },
    [onMapRef],
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
      syncLayersToMap(map, l, t, tileBaseUrl, managedSourcesRef);
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

  // Click handler: show popup with feature attributes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const handleClick = (e: MapMouseEvent) => {
      const queryLayers = layers
        .filter((l) => l.visible && l.layer_type !== 'raster_geolens')
        .map((l) => getLayerId(l.id))
        .filter((id) => map.getLayer(id));

      if (queryLayers.length === 0) {
        setPopupInfo(null);
        return;
      }

      const hits = map.queryRenderedFeatures(e.point, { layers: queryLayers });
      if (hits.length > 0) {
        setPopupInfo({
          longitude: e.lngLat.lng,
          latitude: e.lngLat.lat,
          features: hits.map((feature) => {
            const layerId = feature.layer.id.replace(/^layer-/, '');
            const matchedLayer = layers.find((l) => l.id === layerId);
            return {
              properties: (feature.properties ?? {}) as Record<string, unknown>,
              layerName: matchedLayer?.display_name || matchedLayer?.dataset_name || t('common:viewer.featureFallback'),
              columnInfo: matchedLayer?.dataset_column_info ?? null,
            };
          }),
        });
      } else {
        setPopupInfo(null);
      }
    };

    map.on('click', handleClick);
    return () => {
      map.off('click', handleClick);
    };
  }, [layers, mapReady]);

  // Mousemove: pointer cursor on interactive features (RAF-throttled)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    let rafId = 0;
    const handleMouseMove = (e: MapMouseEvent) => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        if (!map.isStyleLoaded()) return;
        const queryLayers = layers
          .filter((l) => l.visible && l.layer_type !== 'raster_geolens')
          .map((l) => getLayerId(l.id))
          .filter((id) => map.getLayer(id));

        if (queryLayers.length === 0) {
          map.getCanvas().style.cursor = '';
          return;
        }

        const features = map.queryRenderedFeatures(e.point, { layers: queryLayers });
        map.getCanvas().style.cursor = features.length > 0 ? 'pointer' : '';
      });
    };

    map.on('mousemove', handleMouseMove);
    return () => {
      cancelAnimationFrame(rafId);
      map.off('mousemove', handleMouseMove);
      if (map.getCanvas()) map.getCanvas().style.cursor = '';
    };
  }, [layers, mapReady]);

  // Clear popup when layer visibility changes
  useEffect(() => {
    setPopupInfo(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- derived string key intentional
  }, [layers.map((l) => l.visible).join(',')]);

  // Sync layers to map (initial + when layers/tokens change)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url || undefined;
    syncLayersToMap(map, layers, tokenMap, tileBaseUrl, managedSourcesRef);
    reorderBasemapLabels(map, showBasemapLabels);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers, mapReady, tileConfig?.cdn_base_url, tokenMap]);

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

  // Layer ordering — runs on reorder to sync MapLibre z-order with UI list.
  // syncLayersToMap handles ordering on initial add and basemap switch;
  // this effect catches user-triggered reorders (move up/down, drag).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    reorderDataLayers(map, layers);
    reorderBasemapLabels(map, showBasemapLabels);
  }, [layers, mapReady, showBasemapLabels]);


  // Track whether we've restored a saved view (skip auto-fit on initial load)
  const hasSavedView = !!(initialViewState?.center_lng != null && initialViewState?.center_lat != null);
  const initialFitDoneRef = useRef(false);
  const prevLayerCountRef = useRef(layers.length);

  // Auto-fit to visible layers (skip on initial load if saved view exists)
  const layerVisibilityKey = layers.map((l) => `${l.id}:${l.visible}`).join(',');
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

  return (
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
      <NavigationControl position="top-right" />
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
  );
}
