import { useEffect, useRef, useCallback, useState } from 'react';
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
import { getLayerType } from '@/components/builder/map-sync';
import { getTileTokenWithApiKey } from '@/api/tiles';
import type { TileToken } from '@/api/tiles';
import { getEnvConfig } from '@/lib/env';
import { FeaturePopup } from '@/components/map/FeaturePopup';
import type { MapLibreEvent, MapMouseEvent, StyleSpecification } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { MAP_COLORS } from '@/lib/map-colors';
import type { SharedLayerResponse } from '@/types/api';
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

/** Move basemap symbol/label layers above data layers, or hide them. */
function reorderBasemapLabels(map: MaplibreMap, show: boolean) {
  const style = map.getStyle();
  if (!style?.layers) return;

  const basemapSymbolLayers = style.layers.filter(
    (l) => l.type === 'symbol' && (!('source' in l) || !String(l.source ?? '').startsWith('viewer-source-')),
  );

  for (const layer of basemapSymbolLayers) {
    if (show) {
      map.setLayoutProperty(layer.id, 'visibility', 'visible');
      map.moveLayer(layer.id);
    } else {
      map.setLayoutProperty(layer.id, 'visibility', 'none');
    }
  }
}

function getSourceId(sortOrder: number) {
  return `viewer-source-${sortOrder}`;
}

function getLayerId(sortOrder: number) {
  return `viewer-layer-${sortOrder}`;
}

function getOutlineLayerId(sortOrder: number) {
  return `viewer-layer-${sortOrder}-outline`;
}

function getLabelLayerId(sortOrder: number) {
  return `viewer-layer-${sortOrder}-label`;
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
  useEffect(() => {
    if (embedToken || !apiKey || layers.length === 0) return;

    let cancelled = false;

    async function fetchTokens() {
      const uniqueIds = [...new Set(layers.map((l) => l.dataset_id).filter(Boolean))];
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
        console.warn('ViewerMap: failed to fetch tile tokens', err);
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
  }, [embedToken, apiKey, layers.map((l) => l.dataset_id).join(',')]);

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

  // Click handler: show popup with feature attributes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const handleClick = (e: MapMouseEvent) => {
      const queryLayers = layers
        .filter((l) => visibleLayers.has(l.sort_order))
        .map((l) => getLayerId(l.sort_order))
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
            const sortOrder = parseInt(feature.layer.id.replace(/^viewer-layer-/, ''), 10);
            const matchedLayer = layers.find((l) => l.sort_order === sortOrder);
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
  }, [layers, visibleLayers, mapReady]);

  // Mousemove: pointer cursor on interactive features
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const handleMouseMove = (e: MapMouseEvent) => {
      const queryLayers = layers
        .filter((l) => visibleLayers.has(l.sort_order))
        .map((l) => getLayerId(l.sort_order))
        .filter((id) => map.getLayer(id));

      if (queryLayers.length === 0) {
        map.getCanvas().style.cursor = '';
        return;
      }

      const features = map.queryRenderedFeatures(e.point, { layers: queryLayers });
      map.getCanvas().style.cursor = features.length > 0 ? 'pointer' : '';
    };

    map.on('mousemove', handleMouseMove);
    return () => {
      map.off('mousemove', handleMouseMove);
      if (map.getCanvas()) map.getCanvas().style.cursor = '';
    };
  }, [layers, visibleLayers, mapReady]);

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
      const layerId = getLayerId(layer.sort_order);
      const outlineId = getOutlineLayerId(layer.sort_order);
      const token = tokenMap.get(layer.dataset_id) ?? null;
      const tileUrl = buildSignedTileUrl(layer.table_name, token, tileBaseUrl);

      desiredSources.add(sourceId);

      // Add source + layer if not on map
      if (!map.getSource(sourceId)) {
        const sourceLayer = `data.${layer.table_name}`;

        map.addSource(sourceId, {
          type: 'vector',
          tiles: [tileUrl],
          minzoom: 1,
          maxzoom: 22,
        });

        const type = getLayerType(layer.geometry_type);
        const vis = visibleLayers.has(layer.sort_order) ? 'visible' : 'none';

        if (type === 'circle') {
          map.addLayer({
            id: layerId,
            type: 'circle',
            source: sourceId,
            'source-layer': sourceLayer,
            paint: (layer.paint as Record<string, unknown>) ?? {
              'circle-radius': 5,
              'circle-color': MAP_COLORS.default.fill,
              'circle-stroke-color': MAP_COLORS.default.stroke,
              'circle-stroke-width': 1,
            },
            layout: {
              ...(layer.layout as Record<string, unknown>) ?? {},
              visibility: vis,
            },
          });
          if (layer.opacity !== undefined && layer.opacity < 1) {
            map.setPaintProperty(layerId, 'circle-opacity', layer.opacity);
          }
          if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
            map.setFilter(layerId, layer.filter);
          }
        } else if (type === 'line') {
          map.addLayer({
            id: layerId,
            type: 'line',
            source: sourceId,
            'source-layer': sourceLayer,
            paint: (layer.paint as Record<string, unknown>) ?? {
              'line-color': MAP_COLORS.default.fill,
              'line-width': 2,
            },
            layout: {
              ...(layer.layout as Record<string, unknown>) ?? {},
              visibility: vis,
              'line-cap': 'round' as const,
              'line-join': 'round' as const,
            },
          });
          if (layer.opacity !== undefined && layer.opacity < 1) {
            map.setPaintProperty(layerId, 'line-opacity', layer.opacity);
          }
          if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
            map.setFilter(layerId, layer.filter);
          }
        } else {
          map.addLayer({
            id: layerId,
            type: 'fill',
            source: sourceId,
            'source-layer': sourceLayer,
            paint: (layer.paint as Record<string, unknown>) ?? {
              'fill-color': MAP_COLORS.default.fill,
              'fill-opacity': MAP_COLORS.default.fillOpacity,
            },
            layout: {
              ...(layer.layout as Record<string, unknown>) ?? {},
              visibility: vis,
            },
          });
          if (layer.opacity !== undefined && layer.opacity < 1) {
            const fillOpacity =
              ((layer.paint as Record<string, unknown>)?.['fill-opacity'] as number) ?? 0.3;
            map.setPaintProperty(layerId, 'fill-opacity', fillOpacity * layer.opacity);
          }
          if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
            map.setFilter(layerId, layer.filter);
          }
          const outlineColor =
            (layer.paint as Record<string, unknown>)?.['_outline-color'] as string | undefined;
          const outlineWidth =
            (layer.paint as Record<string, unknown>)?.['_outline-width'] as number | undefined;
          map.addLayer({
            id: outlineId,
            type: 'line',
            source: sourceId,
            'source-layer': sourceLayer,
            paint: {
              'line-color': outlineColor ?? MAP_COLORS.default.stroke,
              'line-width': outlineWidth ?? 1,
            },
            layout: {
              visibility: vis,
            },
          });
          if (layer.opacity !== undefined && layer.opacity < 1) {
            map.setPaintProperty(outlineId, 'line-opacity', layer.opacity);
          }
          if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
            map.setFilter(outlineId, layer.filter);
          }
        }

      }

      // Sync label layer for existing sources (add/update/remove)
      const labelId = getLabelLayerId(layer.sort_order);
      if (map.getSource(sourceId)) {
        if (layer.label_config && (layer.label_config as { column?: string }).column) {
          const lc = layer.label_config as { column: string; fontSize?: number; textColor?: string; haloColor?: string; haloWidth?: number };
          const geomType = getLayerType(layer.geometry_type);
          const sl = `data.${layer.table_name}`;
          const vis = visibleLayers.has(layer.sort_order) ? 'visible' : 'none';

          if (!map.getLayer(labelId)) {
            map.addLayer({
              id: labelId,
              type: 'symbol',
              source: sourceId,
              'source-layer': sl,
              layout: {
                'text-field': ['get', lc.column],
                'text-size': lc.fontSize ?? 12,
                'symbol-placement': geomType === 'line' ? 'line' : 'point',
                'text-allow-overlap': false,
                'text-font': ['Noto Sans Regular'],
                'text-max-width': 10,
                visibility: vis,
                ...(geomType === 'circle' ? { 'text-offset': [0, -1.5] as [number, number] } : {}),
              },
              paint: {
                'text-color': lc.textColor ?? MAP_COLORS.label.color,
                'text-halo-color': lc.haloColor ?? MAP_COLORS.label.halo,
                'text-halo-width': lc.haloWidth ?? 1.5,
              },
            });
            if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
              map.setFilter(labelId, layer.filter);
            }
          } else {
            // Update existing label layer properties
            map.setLayoutProperty(labelId, 'text-field', ['get', lc.column]);
            map.setLayoutProperty(labelId, 'text-size', lc.fontSize ?? 12);
            map.setPaintProperty(labelId, 'text-color', lc.textColor ?? MAP_COLORS.label.color);
            map.setPaintProperty(labelId, 'text-halo-color', lc.haloColor ?? MAP_COLORS.label.halo);
            map.setPaintProperty(labelId, 'text-halo-width', lc.haloWidth ?? 1.5);
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
        const outlineId = getOutlineLayerId(order);
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

    // Keep basemap labels above data layers
    reorderBasemapLabels(map, showBasemapLabels);
  }, [layers, mapReady, tileConfig?.cdn_base_url, tokenMap, showBasemapLabels]);

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
      const layerId = getLayerId(layer.sort_order);
      const outlineId = getOutlineLayerId(layer.sort_order);
      const vis = visibleLayers.has(layer.sort_order) ? 'visible' : 'none';

      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, 'visibility', vis);
      }
      if (map.getLayer(outlineId)) {
        map.setLayoutProperty(outlineId, 'visibility', vis);
      }
      const labelId = getLabelLayerId(layer.sort_order);
      if (map.getLayer(labelId)) {
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

  return (
    <MapGL
      initialViewState={defaultView}
      mapStyle={styleValue as string}
      style={{ width: '100%', height: '100%' }}
      attributionControl={false}
      minZoom={1}
      onLoad={handleLoad}
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
