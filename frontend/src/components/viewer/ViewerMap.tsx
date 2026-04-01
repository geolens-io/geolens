import { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Map as MapGL, NavigationControl } from '@vis.gl/react-maplibre';
import { useTheme } from '@/components/theme-provider';
import { useBasemaps, useTileConfig } from '@/hooks/use-settings';
import {
  getThemeBasemap,
  findBasemapById,
  toMaplibreStyle,
  resolveBasemapId,
  LIGHT_PRESET_ID,
  DARK_PRESET_ID,
} from '@/lib/basemap-utils';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { useWebGLRecovery } from '@/hooks/use-webgl-recovery';
import { getTileTokenWithApiKey } from '@/api/tiles';
import type { TileToken } from '@/api/tiles';
import { getEnvConfig } from '@/lib/env';
import { FeaturePopup } from '@/components/map/FeaturePopup';
import type { MapLibreEvent, MapMouseEvent, StyleSpecification } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { SharedLayerResponse } from '@/types/api';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import { getLayerType, resolveAdapterType, reorderBasemapLabels } from '@/components/builder/map-sync';
import { buildLabelLayerSpec, syncLabelLayer } from '@/components/builder/label-layer-utils';
import 'maplibre-gl/dist/maplibre-gl.css';

interface ViewerMapProps {
  layers: SharedLayerResponse[];
  basemapStyle: string;
  initialViewState: {
    center_lng: number;
    center_lat: number;
    zoom: number;
    bearing: number;
    pitch: number;
  };
  visibleLayers: Set<number>;
  onMapReady?: (map: MaplibreMap) => void;
  apiKey?: string;
  embedToken?: string;
  showBasemapLabels?: boolean;
}

function getSourceId(sortOrder: number) {
  return `viewer-source-${sortOrder}`;
}

function getLayerId(sortOrder: number) {
  return `viewer-layer-${sortOrder}`;
}

function getLabelLayerId(sortOrder: number) {
  return `viewer-layer-${sortOrder}-label`;
}

function toAdapterInput(
  layer: SharedLayerResponse,
  visibleLayers: Set<number>,
  tileUrl: string,
): AdapterLayerInput {
  return {
    id: String(layer.sort_order),
    dataset_table_name: layer.table_name,
    dataset_geometry_type: layer.geometry_type,
    opacity: layer.opacity ?? 1,
    visible: visibleLayers.has(layer.sort_order),
    paint: (layer.paint as Record<string, unknown>) ?? {},
    layout: (layer.layout as Record<string, unknown>) ?? {},
    filter: layer.filter ?? null,
    label_config: layer.label_config,
    sourceId: getSourceId(layer.sort_order),
    layerId: getLayerId(layer.sort_order),
    sourceLayer: `data.${layer.table_name}`,
    tileUrl,
  };
}

export function ViewerMap({
  layers,
  basemapStyle,
  initialViewState,
  visibleLayers,
  onMapReady,
  apiKey,
  embedToken,
  showBasemapLabels = true,
}: ViewerMapProps) {
  const { t } = useTranslation('common');
  const mapRef = useRef<MaplibreMap | null>(null);
  const managedSourcesRef = useRef<Set<string>>(new Set());
  const prevOrderKeyRef = useRef('');
  const [mapReady, setMapReady] = useState(false);
  const [popupInfo, setPopupInfo] = useState<{
    longitude: number;
    latitude: number;
    features: { properties: Record<string, unknown>; layerName: string; columnInfo: { name: string; type: string }[] | null }[];
  } | null>(null);

  // Tile tokens fetched via API key auth
  const [tokenMap, setTokenMap] = useState<Map<string, TileToken>>(new Map());
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { resolvedTheme } = useTheme();
  const { data: basemaps } = useBasemaps();
  const { data: tileConfig } = useTileConfig();
  const resolvedId = resolveBasemapId(basemapStyle);
  // For default basemaps (positron/dark-matter), auto-switch with theme.
  // For explicitly chosen non-default basemaps, respect the saved choice.
  const isDefaultBasemap = resolvedId === LIGHT_PRESET_ID || resolvedId === DARK_PRESET_ID;
  const effectiveBasemap = isDefaultBasemap
    ? getThemeBasemap(basemaps ?? [], resolvedTheme)
    : findBasemapById(basemaps ?? [], basemapStyle);
  const fallbackUrl = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';
  const styleValue = toMaplibreStyle(effectiveBasemap?.url ?? fallbackUrl);

  // Fetch tile tokens for all layers using API key auth
  const layerDatasetIds = useMemo(
    () => [...new Set(layers.map((l) => l.dataset_id).filter(Boolean))],
    [layers],
  );
  useEffect(() => {
    if (embedToken || !apiKey || layerDatasetIds.length === 0) return;

    let cancelled = false;

    async function fetchTokens() {
      const uniqueIds = layerDatasetIds;
      if (uniqueIds.length === 0) return;

      try {
        const results = await Promise.all(
          uniqueIds.map((id) => getTileTokenWithApiKey(id, apiKey!)),
        );

        if (cancelled) return;

        const newMap = new Map<string, TileToken>();
        for (let i = 0; i < uniqueIds.length; i++) {
          newMap.set(uniqueIds[i], results[i]);
        }
        setTokenMap(newMap);

        // Set up refresh at 80% of minimum TTL
        const minTtl = Math.min(...results.map((r) => r.expires_in));
        const refreshMs = Math.max(minTtl * 800, 30_000);

        if (refreshTimerRef.current) {
          clearTimeout(refreshTimerRef.current);
        }
        refreshTimerRef.current = setTimeout(() => {
          if (!cancelled) fetchTokens();
        }, refreshMs);
      } catch (err) {
        if (import.meta.env.DEV) console.warn('ViewerMap: failed to fetch tile tokens', err);
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

  const handleLoad = useCallback(
    (e: MapLibreEvent) => {
      const map = e.target;
      mapRef.current = map;

      // Absolutify URLs and attach embed token header when present
      map.setTransformRequest((url: string) => {
        const absUrl = url.startsWith('http') ? url : `${window.location.origin}${url}`;
        const headers: Record<string, string> = {};
        if (embedToken) {
          headers['X-Embed-Token'] = embedToken;
        }
        return { url: absUrl, headers };
      });

      setMapReady(true);
      onMapReady?.(map);
    },
    [onMapReady, embedToken],
  );

  // Stable list of interactive (non-heatmap, visible) layer IDs for query operations
  const interactiveLayers = useMemo(
    () =>
      layers
        .filter((l) => visibleLayers.has(l.sort_order))
        .filter((l) => (l.style_config as Record<string, unknown> | undefined)?.render_mode !== 'heatmap')
        .map((l) => getLayerId(l.sort_order)),
    [layers, visibleLayers],
  );
  // Ref so event handlers always see current value without re-registration
  const interactiveLayersRef = useRef(interactiveLayers);
  interactiveLayersRef.current = interactiveLayers;
  const layersRef = useRef(layers);
  layersRef.current = layers;

  // Click handler: show popup with feature attributes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const handleClick = (e: MapMouseEvent) => {
      const queryIds = interactiveLayersRef.current.filter((id) => map.getLayer(id));

      if (queryIds.length === 0) {
        setPopupInfo(null);
        return;
      }

      const hits = map.queryRenderedFeatures(e.point, { layers: queryIds });
      if (hits.length > 0) {
        setPopupInfo({
          longitude: e.lngLat.lng,
          latitude: e.lngLat.lat,
          features: hits.map((feature) => {
            const sortOrder = parseInt(feature.layer.id.replace(/^viewer-layer-/, ''), 10);
            const matchedLayer = layersRef.current.find((l) => l.sort_order === sortOrder);
            return {
              properties: (feature.properties ?? {}) as Record<string, unknown>,
              layerName: matchedLayer?.display_name || matchedLayer?.dataset_name || t('viewer.featureFallback'),
              columnInfo: matchedLayer?.column_info ?? null,
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
  }, [mapReady, t]);

  // Mousemove: pointer cursor on interactive features
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    let rafId = 0;
    const handleMouseMove = (e: MapMouseEvent) => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        if (!map.getCanvas()) return;
        const queryIds = interactiveLayersRef.current.filter((id) => map.getLayer(id));

        if (queryIds.length === 0) {
          map.getCanvas().style.cursor = '';
          return;
        }

        const features = map.queryRenderedFeatures(e.point, { layers: queryIds });
        map.getCanvas().style.cursor = features.length > 0 ? 'pointer' : '';
      });
    };

    map.on('mousemove', handleMouseMove);
    return () => {
      cancelAnimationFrame(rafId);
      map.off('mousemove', handleMouseMove);
      if (map.getCanvas()) map.getCanvas().style.cursor = '';
    };
  }, [mapReady]);

  // Clear popup when layer visibility changes
  useEffect(() => {
    setPopupInfo(null);
  }, [visibleLayers]);

  // Sync layers to map
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const currentSources = new Set(managedSourcesRef.current);
    const desiredSources = new Set<string>();
    const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url;

    for (const layer of layers) {
      const sourceId = getSourceId(layer.sort_order);
      const token = tokenMap.get(layer.dataset_id) ?? null;
      const tileUrl = buildSignedTileUrl(layer.table_name, token, tileBaseUrl);
      const adapterInput = toAdapterInput(layer, visibleLayers, tileUrl);

      desiredSources.add(sourceId);

      if (!map.getSource(sourceId)) {
        map.addSource(sourceId, {
          type: 'vector',
          tiles: [tileUrl],
          minzoom: 1,
          maxzoom: 22,
        });
        const type = resolveAdapterType(layer.geometry_type, layer.style_config);
        const adapter = getAdapter(type);
        adapter.addLayers(map, adapterInput);
      } else {
        const type = resolveAdapterType(layer.geometry_type, layer.style_config);
        const adapter = getAdapter(type);
        adapter.syncPaint(map, adapterInput);
      }

      // Apply per-layer zoom range from custom layout props (main + outline companion)
      const layerLayout = (layer.layout ?? {}) as Record<string, unknown>;
      const layerMinzoom = (layerLayout['_minzoom'] as number) ?? 0;
      const layerMaxzoom = (layerLayout['_maxzoom'] as number) ?? 22;
      const mainLayerId = getLayerId(layer.sort_order);
      if (map.getLayer(mainLayerId)) {
        map.setLayerZoomRange(mainLayerId, layerMinzoom, layerMaxzoom);
      }
      const outlineLayerId = `${mainLayerId}-outline`;
      if (map.getLayer(outlineLayerId)) {
        map.setLayerZoomRange(outlineLayerId, layerMinzoom, layerMaxzoom);
      }

      // Label layer management (adapters do not handle labels)
      const labelId = getLabelLayerId(layer.sort_order);
      if (map.getSource(sourceId)) {
        if (layer.label_config?.column) {
          const lc = layer.label_config;
          const geomType = getLayerType(layer.geometry_type);
          const sl = `data.${layer.table_name}`;
          const vis = visibleLayers.has(layer.sort_order) ? 'visible' : 'none';

          if (!map.getLayer(labelId)) {
            map.addLayer(buildLabelLayerSpec({ labelId, sourceId, sourceLayer: sl, lc, geomType, visibility: vis }));
            if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
              map.setFilter(labelId, layer.filter);
            }
          } else {
            syncLabelLayer(map, labelId, lc, geomType);
            if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
              map.setFilter(labelId, layer.filter);
            }
          }
        } else if (map.getLayer(labelId)) {
          // Remove label layer when config cleared
          map.removeLayer(labelId);
        }
      }
    }

    // Remove stale layers/sources
    for (const sourceId of currentSources) {
      if (!desiredSources.has(sourceId)) {
        const order = parseInt(sourceId.replace('viewer-source-', ''), 10);
        const layerId = getLayerId(order);
        const outlineId = `${layerId}-outline`;
        const labelId = getLabelLayerId(order);
        if (map.getLayer(labelId)) map.removeLayer(labelId);
        if (map.getLayer(outlineId)) map.removeLayer(outlineId);
        if (map.getLayer(layerId)) map.removeLayer(layerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
      }
    }

    managedSourcesRef.current = desiredSources;

    // Ensure label layers sit above all data/outline layers so labels
    // from lower layers aren't obscured by data layers above them.
    for (const layer of layers) {
      const labelId = getLabelLayerId(layer.sort_order);
      if (map.getLayer(labelId)) {
        map.moveLayer(labelId);
      }
    }

    // Keep basemap labels above data layers (only when order actually changes)
    const orderKey = layers.map((l) => l.sort_order).join(',') + '|' + String(showBasemapLabels);
    if (orderKey !== prevOrderKeyRef.current) {
      prevOrderKeyRef.current = orderKey;
      reorderBasemapLabels(map, showBasemapLabels, 'viewer-source-');
    }
  }, [layers, visibleLayers, mapReady, tileConfig?.cdn_base_url, tokenMap, showBasemapLabels]);

  // Update tile URLs in-place when tokens refresh
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || (!embedToken && tokenMap.size === 0)) return;
    const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url;

    for (const layer of layers) {
      const sourceId = getSourceId(layer.sort_order);
      const source = map.getSource(sourceId);
      if (source && 'setTiles' in source) {
        const token = tokenMap.get(layer.dataset_id) ?? null;
        const newUrl = buildSignedTileUrl(layer.table_name, token, tileBaseUrl);
        (source as maplibregl.VectorTileSource).setTiles([newUrl]);
      }
    }
  }, [tokenMap, layers, mapReady, tileConfig?.cdn_base_url, embedToken]);

  // Toggle visibility when visibleLayers set changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    for (const layer of layers) {
      const type = resolveAdapterType(layer.geometry_type, layer.style_config);
      const adapter = getAdapter(type);
      const adapterInput = toAdapterInput(layer, visibleLayers, '');
      adapter.syncVisibility(map, adapterInput);

      // Also sync label visibility (not handled by adapters)
      const labelId = getLabelLayerId(layer.sort_order);
      if (map.getLayer(labelId)) {
        const vis = visibleLayers.has(layer.sort_order) ? 'visible' : 'none';
        map.setLayoutProperty(labelId, 'visibility', vis);
      }
    }
  }, [visibleLayers, layers, mapReady]);

  // Theme-aware basemap switching -- preserve custom sources/layers
  const prevBasemapUrlRef = useRef(effectiveBasemap?.url ?? fallbackUrl);
  useEffect(() => {
    const map = mapRef.current;
    const currentUrl = effectiveBasemap?.url ?? fallbackUrl;
    if (!map || currentUrl === prevBasemapUrlRef.current) return;
    prevBasemapUrlRef.current = currentUrl;

    const newStyle = toMaplibreStyle(currentUrl);
    map.setStyle(newStyle, {
      transformStyle: (_prev: StyleSpecification | undefined, next: StyleSpecification) => {
        const customSources: Record<string, unknown> = {};
        const customLayers: unknown[] = [];
        if (_prev) {
          for (const [id, src] of Object.entries(_prev.sources || {})) {
            if (id === 'basemap' || next.sources?.[id]) continue;
            customSources[id] = src;
          }
          for (const layer of _prev.layers || []) {
            if (!next.layers?.some((l) => l.id === layer.id)) customLayers.push(layer);
          }
        }
        return {
          ...next,
          sources: { ...next.sources, ...customSources },
          layers: [...next.layers, ...customLayers],
        } as StyleSpecification;
      },
    });
  }, [effectiveBasemap?.url, basemaps]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      mapRef.current = null;
    };
  }, []);

  const defaultView = {
    longitude: initialViewState.center_lng,
    latitude: initialViewState.center_lat,
    zoom: initialViewState.zoom,
    bearing: initialViewState.bearing,
    pitch: initialViewState.pitch,
  };

  const { contextLost, reload } = useWebGLRecovery(mapRef, mapReady);

  return (
    <div className="relative h-full w-full">
      <MapGL
        initialViewState={defaultView}
        mapStyle={styleValue as string}
        style={{ width: '100%', height: '100%' }}
        attributionControl={false}
        minZoom={1}
        onLoad={handleLoad}
        aria-label="Map viewer"
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
      {contextLost && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80">
          <div className="text-center space-y-2">
            <p className="text-sm text-muted-foreground">{t('errors.mapMessage')}</p>
            <button onClick={reload} className="text-sm underline text-primary">{t('common.reload')}</button>
          </div>
        </div>
      )}
    </div>
  );
}
