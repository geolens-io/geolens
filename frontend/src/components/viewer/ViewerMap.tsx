import { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Map as MapGL, NavigationControl, ScaleControl, FullscreenControl, AttributionControl } from '@vis.gl/react-maplibre';
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
import { buildSignedTileUrl, resolveTileBaseUrl } from '@/lib/tile-utils';
import { useWebGLRecovery } from '@/hooks/use-webgl-recovery';
import { getTileTokenWithApiKey, getTileTokensBatch } from '@/api/tiles';
import type { TileToken, VectorTileToken } from '@/api/tiles';
import { FeaturePopup } from '@/components/map/FeaturePopup';
import type { MapLibreEvent, MapMouseEvent, VectorTileSource } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { SharedLayerResponse } from '@/types/api';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import { resolveAdapterType, syncLayersToMap } from '@/components/builder/map-sync';
import type { SyncLayerInput, SyncOptions } from '@/components/builder/map-sync';
import 'maplibre-gl/dist/maplibre-gl.css';

/**
 * Public map viewer canvas — used by the standalone viewer page and the
 * embeddable iframe widget.
 *
 * Renders multiple shared layers from a publicly visible map composition with
 * read-only navigation, popups on click, and a basemap matching the parent
 * theme. Layer rendering uses the unified `layer-adapters` registry shared
 * with the builder, ensuring viewer + builder produce identical visuals.
 *
 * Authentication is implicit: signed share or embed tokens are passed in via
 * `apiKey` (query parameter) and used to sign tile URLs.
 */
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
  /** When true, basemapStyle was explicitly chosen by the user — skip theme auto-switching */
  basemapOverride?: boolean;
}

/** ID prefix used for viewer map layers — keeps IDs distinct from builder. */
const VIEWER_PREFIX = 'viewer-';

function getViewerSourceId(sortOrder: number) {
  return `viewer-source-${sortOrder}`;
}

function getViewerLayerId(sortOrder: number) {
  return `viewer-layer-${sortOrder}`;
}

function getViewerLabelLayerId(sortOrder: number) {
  return `viewer-layer-${sortOrder}-label`;
}

/** Convert a SharedLayerResponse to the normalized SyncLayerInput. */
function toViewerSyncInput(
  layer: SharedLayerResponse,
  visibleLayers: Set<number>,
): SyncLayerInput {
  return {
    id: String(layer.sort_order),
    dataset_id: layer.dataset_id,
    dataset_table_name: layer.table_name,
    dataset_geometry_type: layer.geometry_type,
    opacity: layer.opacity ?? 1,
    visible: visibleLayers.has(layer.sort_order),
    paint: (layer.paint as Record<string, unknown>) ?? {},
    layout: (layer.layout as Record<string, unknown>) ?? {},
    filter: layer.filter ?? null,
    label_config: layer.label_config,
    style_config: layer.style_config,
  };
}

/** Build an AdapterLayerInput for viewer visibility syncing (no tile URL needed). */
function toAdapterInput(
  layer: SharedLayerResponse,
  visibleLayers: Set<number>,
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
    sourceId: getViewerSourceId(layer.sort_order),
    layerId: getViewerLayerId(layer.sort_order),
    sourceLayer: `data.${layer.table_name}`,
    tileUrl: '',
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
  basemapOverride = false,
}: ViewerMapProps) {
  const { t } = useTranslation('common');
  const mapRef = useRef<MaplibreMap | null>(null);
  const managedSourcesRef = useRef<Set<string>>(new Set());
  const prevOrderKeyRef = useRef('');
  const [mapReady, setMapReady] = useState(false);
  // `tilesIdle` drives the `data-tiles-loaded` DOM attribute on the outer
  // container. The Playwright demo-smoke spec polls for this attribute to
  // avoid an arbitrary `waitForTimeout` delay after networkidle.
  const [tilesIdle, setTilesIdle] = useState(false);
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
  // For default basemaps (positron/dark-matter), auto-switch with theme —
  // but only when the basemap comes from the saved map data, not a user override.
  const isDefaultBasemap = !basemapOverride && (resolvedId === LIGHT_PRESET_ID || resolvedId === DARK_PRESET_ID);
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
    if (embedToken || layerDatasetIds.length === 0) return;

    let cancelled = false;

    async function fetchTokens() {
      try {
        let newMap: Map<string, TileToken>;

        if (apiKey) {
          // API-key path (per-dataset) — used by embedded/API-key viewers.
          const results = await Promise.all(
            layerDatasetIds.map((id) => getTileTokenWithApiKey(id, apiKey!)),
          );
          newMap = new Map<string, TileToken>();
          for (let i = 0; i < layerDatasetIds.length; i++) {
            newMap.set(layerDatasetIds[i], results[i]);
          }
        } else {
          // Anonymous / JWT path — single batch request. Required for the
          // public PublicMapViewerPage → ViewerMap path, which has no
          // apiKey and no embedToken. Without this branch, tokenMap stays
          // empty and the first sync treats every layer as vector data,
          // producing `.pbf` tile URLs for rasters and breaking anonymous
          // raster rendering.
          const response = await getTileTokensBatch(layerDatasetIds);
          newMap = new Map<string, TileToken>();
          for (const [datasetId, entry] of Object.entries(response.tokens)) {
            if ('kind' in entry) {
              newMap.set(datasetId, entry);
            }
          }
        }

        if (cancelled) return;
        setTokenMap(newMap);

        // Refresh at 80% of the minimum vector-token TTL. Raster tokens
        // have no expires_in (the tile_url is stable), so if there are no
        // vector tokens in the map, skip the refresh cycle entirely.
        const vectorTtls = [...newMap.values()]
          .filter((t): t is VectorTileToken => t.kind === 'vector')
          .map((t) => t.expires_in);
        if (vectorTtls.length > 0) {
          const minTtl = Math.min(...vectorTtls);
          const refreshMs = Math.max(minTtl * 800, 30_000);
          if (refreshTimerRef.current) {
            clearTimeout(refreshTimerRef.current);
          }
          refreshTimerRef.current = setTimeout(() => {
            if (!cancelled) fetchTokens();
          }, refreshMs);
        }
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

      // Filter expected tile errors (no-data tiles outside extent) and
      // surface anything else as a deduped toast so users know the map
      // has a real problem (RES-3). Previously suppressed entirely in prod.
      map.on('error', (e: { error: { message?: string; status?: number } }) => {
        const msg = e.error?.message ?? '';
        // Expected: 404 tiles outside extent, or our managed source errors
        if (msg.includes('source-') || e.error?.status === 404) {
          return;
        }
        if (import.meta.env.DEV) console.warn('[ViewerMap] Map error:', e.error);
        // Deduped toast (stable ID replaces prior error instead of stacking)
        toast.error(t('viewer.mapError', { defaultValue: 'Map tile error — some layers may not display correctly.' }), {
          id: 'viewer-map-error',
        });
      });

      // `idle` fires when no tiles are loading, no transitions are in
      // progress, and no animations are running. We flip the container's
      // data-tiles-loaded attribute on first idle (and keep it true) so
      // Playwright can replace its 2 s arbitrary wait with a deterministic
      // signal. The flag never toggles back — once the initial view has
      // settled, it stays "ready" for the duration of the viewer session.
      map.once('idle', () => setTilesIdle(true));

      setMapReady(true);
      onMapReady?.(map);
    },
    [onMapReady, embedToken, t],
  );

  // Stable list of interactive (non-heatmap, visible) layer IDs for query operations
  const interactiveLayers = useMemo(
    () =>
      layers
        .filter((l) => visibleLayers.has(l.sort_order))
        .filter((l) => (l.style_config as Record<string, unknown> | undefined)?.render_mode !== 'heatmap')
        .map((l) => getViewerLayerId(l.sort_order)),
    [layers, visibleLayers],
  );
  // Ref so event handlers always see current value without re-registration
  const interactiveLayersRef = useRef(interactiveLayers);
  interactiveLayersRef.current = interactiveLayers;
  const layersRef = useRef(layers);
  layersRef.current = layers;

  // KISS-N5: shared helper for click + mousemove handlers. Filters the ref'd
  // interactive layer IDs down to ones currently attached to the map and runs
  // queryRenderedFeatures with that guarded set. Returns null when there are
  // no interactive layers to query (so callers can clear their UI state).
  const queryInteractiveFeatures = useCallback(
    (map: MaplibreMap, point: MapMouseEvent['point']) => {
      const queryIds = interactiveLayersRef.current.filter((id) => map.getLayer(id));
      if (queryIds.length === 0) return null;
      return map.queryRenderedFeatures(point, { layers: queryIds });
    },
    [],
  );

  // Click handler: show popup with feature attributes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const handleClick = (e: MapMouseEvent) => {
      const hits = queryInteractiveFeatures(map, e.point);
      if (hits === null) {
        setPopupInfo(null);
        return;
      }

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
  }, [mapReady, t, queryInteractiveFeatures]);

  // Mousemove: pointer cursor on interactive features
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    let rafId = 0;
    const handleMouseMove = (e: MapMouseEvent) => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        if (!map.getCanvas()) return;
        const features = queryInteractiveFeatures(map, e.point);
        if (features === null) {
          map.getCanvas().style.cursor = '';
          return;
        }
        map.getCanvas().style.cursor = features.length > 0 ? 'pointer' : '';
      });
    };

    map.on('mousemove', handleMouseMove);
    return () => {
      cancelAnimationFrame(rafId);
      map.off('mousemove', handleMouseMove);
      if (map.getCanvas()) map.getCanvas().style.cursor = '';
    };
  }, [mapReady, queryInteractiveFeatures]);

  // Clear popup when layer visibility changes
  useEffect(() => {
    setPopupInfo(null);
  }, [visibleLayers]);

  // Ref to hold current sync inputs so the style.load callback can access them
  const syncInputsRef = useRef({ layers, visibleLayers, tokenMap, tileConfig, showBasemapLabels });
  syncInputsRef.current = { layers, visibleLayers, tokenMap, tileConfig, showBasemapLabels };

  /** Wrapper: convert viewer state to normalized inputs and call unified syncLayersToMap */
  const runSync = useCallback((map: MaplibreMap) => {
    const { layers: ls, visibleLayers: vl, tokenMap: tm, tileConfig: tc, showBasemapLabels: sbl } = syncInputsRef.current;
    const tileBaseUrl = resolveTileBaseUrl(tc);
    const syncInputs: SyncLayerInput[] = ls.map((l) => toViewerSyncInput(l, vl));
    const syncOpts: SyncOptions = { idPrefix: VIEWER_PREFIX, showBasemapLabels: sbl };
    syncLayersToMap(map, syncInputs, tm, tileBaseUrl, managedSourcesRef, prevOrderKeyRef, syncOpts);
  }, []);

  // Sync layers to map (on data/visibility changes)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    // Gate the first sync on tile tokens arriving: syncLayersToMap branches
    // on `token?.kind === 'raster'` to pick the raster adapter vs. the
    // vector path. If we sync before tokens land, every layer — including
    // rasters — is added as a vector source with a `.pbf` URL, which the
    // server rejects for raster datasets and maplibre never recovers from.
    // The embed-token path has its own transformRequest flow and doesn't
    // depend on tokenMap, so it's allowed to sync immediately.
    if (!embedToken && layers.length > 0 && tokenMap.size === 0) return;
    runSync(map);
  }, [layers, visibleLayers, mapReady, tileConfig?.cdn_base_url, tokenMap, showBasemapLabels, runSync, embedToken]);

  // Update tile URLs in-place when vector tokens refresh (token rotation).
  // Narrow the dep to the single primitive the effect actually reads so the
  // hook only re-runs when the CDN base URL changes (not on any tileConfig
  // object identity churn).
  //
  // IMPORTANT: raster sources also expose `setTiles`, so the old
  // `'setTiles' in source` check matched both vector and raster sources
  // indiscriminately — and `buildSignedTileUrl` always produces a vector
  // URL. That meant on every token refresh we were overwriting raster
  // sources' correct `/raster-tiles/.../tiles/{z}/{x}/{y}.png` URLs with
  // broken vector `.pbf` URLs, which the server rejects and the raster
  // never renders again.
  // Gate on `source.type === 'vector'` and on the token also being the
  // vector kind so rasters (which have stable URLs and no expiration) are
  // left untouched.
  const cdnBaseUrl = tileConfig?.cdn_base_url;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || (!embedToken && tokenMap.size === 0)) return;
    const tileBaseUrl = resolveTileBaseUrl({ cdn_base_url: cdnBaseUrl });

    for (const layer of layers) {
      const token = tokenMap.get(layer.dataset_id) ?? null;
      // Skip rasters — their tile_url is stable, no refresh needed.
      if (token && token.kind !== 'vector') continue;
      const sourceId = getViewerSourceId(layer.sort_order);
      const source = map.getSource(sourceId);
      // Only vector sources need query-param URL refreshes.
      if (source && source.type === 'vector') {
        const newUrl = buildSignedTileUrl(layer.table_name, token, tileBaseUrl);
        (source as VectorTileSource).setTiles([newUrl]);
      }
    }
  }, [tokenMap, layers, mapReady, cdnBaseUrl, embedToken]);

  // Toggle visibility when visibleLayers set changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    for (const layer of layers) {
      const type = resolveAdapterType(layer.geometry_type, layer.style_config);
      const adapter = getAdapter(type);
      const adapterInput = toAdapterInput(layer, visibleLayers);
      adapter.syncVisibility(map, adapterInput);

      // Also sync label visibility (not handled by adapters)
      const labelId = getViewerLabelLayerId(layer.sort_order);
      if (map.getLayer(labelId)) {
        const vis = visibleLayers.has(layer.sort_order) ? 'visible' : 'none';
        map.setLayoutProperty(labelId, 'visibility', vis);
      }
    }
  }, [visibleLayers, layers, mapReady]);

  // Re-add data layers after any basemap/style change.
  // <MapGL styleDiffing={false}> calls map.setStyle() when mapStyle prop changes,
  // which wipes all custom sources/layers. Listen for the style.load event to
  // clear tracked state and re-sync layers immediately (mirrors BuilderMap pattern).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const onStyleLoad = () => {
      managedSourcesRef.current = new Set();
      prevOrderKeyRef.current = '';
      // Guard: if layers haven't loaded yet, skip — the sync effect will
      // run when layers arrive via its own dependency on the layers prop.
      if (syncInputsRef.current.layers.length > 0) {
        runSync(map);
      }
    };

    map.on('style.load', onStyleLoad);
    return () => {
      map.off('style.load', onStyleLoad);
    };
  }, [mapReady, runSync]);

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
    <div
      className={`relative h-full w-full ${!mapReady ? 'bg-muted animate-pulse' : ''}`}
      data-tiles-loaded={tilesIdle ? 'true' : 'false'}
    >
      <MapGL
        initialViewState={defaultView}
        mapStyle={styleValue as string}
        styleDiffing={false}
        style={{ width: '100%', height: '100%' }}
        attributionControl={false}
        minZoom={1}
        onLoad={handleLoad}
        aria-label={t('viewer.legend.title')}
      >
        <NavigationControl position="top-right" />
        <FullscreenControl position="top-right" />
        <ScaleControl position="bottom-left" maxWidth={100} unit="metric" />
        <AttributionControl position="bottom-right" compact={true} />
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
            <p className="text-sm text-muted-foreground">{t('errorBoundary.mapMessage')}</p>
            <button onClick={reload} className="text-sm underline text-primary">{t('reload')}</button>
          </div>
        </div>
      )}
    </div>
  );
}
