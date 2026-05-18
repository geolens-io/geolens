import { useEffect, useRef, useCallback, useState, useMemo, memo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Map as MapGL, NavigationControl, ScaleControl, FullscreenControl, AttributionControl, TerrainControl } from '@vis.gl/react-maplibre';
import { useBasemaps, useTileConfig } from '@/hooks/use-settings';
import {
  findBasemapById,
  sanitizeMaplibreStyle,
  toMaplibreStyle,
  resolveBasemapId,
  BLANK_BASEMAP_ID,
} from '@/lib/basemap-utils';
import { buildClusterTileUrl, buildSignedTileUrl, resolveTileBaseUrl } from '@/lib/tile-utils';
import { useWebGLRecovery } from '@/hooks/use-webgl-recovery';
import { useViewerTokens } from '@/components/viewer/hooks/use-viewer-tokens';
import { useViewerTerrain } from '@/components/viewer/hooks/use-viewer-terrain';
import { FeaturePopup, type FeatureInfo } from '@/components/map/FeaturePopup';
import {
  activateClusterFeature,
  clusterAggregateFeatureInfo,
  clusterFeatureCoordinates,
  clusterInteractiveLayerIds,
  isClusterFeature,
} from '@/components/map/cluster-interactions';
import { MapCoordReadout } from '@/components/map/MapCoordReadout';
import { substitutePopupTemplate } from '@/lib/popup-template';
import i18n from '@/i18n/i18n';
import type { MapLibreEvent, MapMouseEvent, StyleSpecification, VectorTileSource } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapBasemapConfig, MapTerrainConfig, SharedLayerResponse } from '@/types/api';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import { applyBasemapConfigToMap, resolveAdapterType, syncLayersToMap, prefixed, getDataDrivenColumnsForLayer } from '@/components/builder/map-sync';
import type { SyncLayerInput, SyncOptions } from '@/components/builder/map-sync';
import { asFeatureCollection, fetchBoundedGeoJson } from '@/api/geojson-z';
import { createViewerLayerEntries } from '@/components/viewer/layer-identity';
import { getClusterSourceEligibility, getClusterSourceStrategy, isClusterRenderMode, shouldFetchClusterGeoJson } from '@/components/builder/cluster-source';
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
  visibleLayers: Set<string>;
  onMapReady?: (map: MaplibreMap) => void;
  apiKey?: string;
  embedToken?: string;
  basemapConfig?: MapBasemapConfig | null;
  showBasemapLabels?: boolean;
  terrainConfig?: MapTerrainConfig | null;
}

/** ID prefix used for viewer map layers — keeps IDs distinct from builder. */
const VIEWER_PREFIX = 'viewer-';
const VIEWER_SOURCE_PREFIX = `${VIEWER_PREFIX}source-`;

/** Convert a SharedLayerResponse to the normalized SyncLayerInput. */
function toViewerSyncInput(
  layer: SharedLayerResponse,
  layerKey: string,
  visibleLayers: Set<string>,
): SyncLayerInput {
  return {
    id: layerKey,
    dataset_table_name: layer.table_name,
    dataset_geometry_type: layer.geometry_type,
    opacity: layer.opacity ?? 1,
    visible: visibleLayers.has(layerKey),
    paint: layer.paint ?? {},
    layout: layer.layout ?? {},
    filter: layer.filter ?? null,
    label_config: layer.label_config,
    style_config: layer.style_config,
    is_dem: layer.is_dem,
    dataset_id: layer.dataset_id,
    is_3d: layer.is_3d,
    feature_count: layer.feature_count,
  };
}

/** Build an AdapterLayerInput for viewer visibility syncing (no tile URL needed). */
function toAdapterInput(
  layer: SharedLayerResponse,
  layerKey: string,
  visibleLayers: Set<string>,
): AdapterLayerInput {
  return {
    id: layerKey,
    dataset_table_name: layer.table_name,
    dataset_geometry_type: layer.geometry_type,
    opacity: layer.opacity ?? 1,
    visible: visibleLayers.has(layerKey),
    paint: layer.paint ?? {},
    layout: layer.layout ?? {},
    filter: layer.filter ?? null,
    label_config: layer.label_config,
    style_config: layer.style_config,
    is_dem: layer.is_dem,
    sourceId: prefixed('source', layerKey, VIEWER_PREFIX),
    layerId: prefixed('layer', layerKey, VIEWER_PREFIX),
    sourceLayer: `data.${layer.table_name}`,
    tileUrl: '',
  };
}

export const ViewerMap = memo(function ViewerMap({
  layers,
  basemapStyle,
  initialViewState,
  visibleLayers,
  onMapReady,
  apiKey,
  embedToken,
  basemapConfig = null,
  showBasemapLabels = true,
  terrainConfig = null,
}: ViewerMapProps) {
  const { t } = useTranslation('common');
  const mapRef = useRef<MaplibreMap | null>(null);
  const managedSourcesRef = useRef<Set<string>>(new Set());
  const prevOrderKeyRef = useRef('');
  const [mapReady, setMapReady] = useState(false);
  const layerEntries = useMemo(() => createViewerLayerEntries(layers), [layers]);

  // Tile token management (fetch, auto-refresh, error toast)
  const { tokenMap } = useViewerTokens({ layers, apiKey, embedToken });

  // Persisted terrain source and exaggeration
  const { terrainReady, reseedTerrainOnStyleLoad } = useViewerTerrain({
    layers,
    mapRef,
    mapReady,
    terrainConfig,
    tokenMap,
  });

  // Bounded GeoJSON data for small 3D datasets and eligible cluster layers.
  const geojsonDataRef = useRef<Map<string, GeoJSON.FeatureCollection>>(new Map());
  const boundedGeoJsonLayers = useMemo(
    () => layerEntries.filter(({ layer }) => (
      (layer.is_3d && layer.feature_count != null && layer.feature_count <= 5000)
      || shouldFetchClusterGeoJson(layer)
    )),
    [layerEntries],
  );

  // `tilesIdle` drives the `data-tiles-loaded` DOM attribute on the outer
  // container. The Playwright demo-smoke spec polls for this attribute to
  // avoid an arbitrary `waitForTimeout` delay after networkidle.
  const [tilesIdle, setTilesIdle] = useState(false);
  const [popupInfo, setPopupInfo] = useState<{
    longitude: number;
    latitude: number;
    features: FeatureInfo[];
  } | null>(null);

  const { data: basemaps } = useBasemaps();
  const { data: tileConfig } = useTileConfig();
  const resolvedId = resolveBasemapId(basemapStyle);
  const isBlank = resolvedId === BLANK_BASEMAP_ID;
  const effectiveBasemap = isBlank
    ? undefined
    : findBasemapById(basemaps ?? [], basemapStyle);
  const fallbackUrl = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';
  const styleValue = useMemo(
    () => (isBlank
      ? toMaplibreStyle(BLANK_BASEMAP_ID)
      : toMaplibreStyle(effectiveBasemap?.url ?? fallbackUrl)),
    [effectiveBasemap?.url, fallbackUrl, isBlank],
  );
  const [mapStyle, setMapStyle] = useState(styleValue);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    if (typeof styleValue !== 'string' || !styleValue.includes('/styles/')) {
      setMapStyle(styleValue);
      return () => {
        controller.abort();
      };
    }

    // Remote GL styles can reference sprite patterns that are unavailable in
    // their published sprite sheet. Fetch and sanitize first so MapLibre never
    // emits noisy missing-image warnings during demo validation.
    setMapStyle({
      version: 8,
      sources: {},
      layers: [
        {
          id: 'background',
          type: 'background',
          paint: { 'background-color': '#111111' },
        },
      ],
    });

    fetch(styleValue, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Basemap style request failed: ${response.status}`);
        return response.json() as Promise<StyleSpecification>;
      })
      .then((style) => {
        if (!cancelled) setMapStyle(sanitizeMaplibreStyle(style));
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (import.meta.env.DEV) console.warn('[ViewerMap] Basemap style sanitization failed:', error);
        if (!cancelled) setMapStyle(styleValue);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [styleValue]);

  // Fetch bounded GeoJSON data for small 3D datasets (auto-switch from MVT per D-07)
  // and for eligible point cluster layers.
  // Fetch is independent of map readiness — data lands in a ref, repaint is separate.
  const [geojsonVersion, setGeojsonVersion] = useState(0);
  useEffect(() => {
    if (boundedGeoJsonLayers.length === 0) {
      if (geojsonDataRef.current.size > 0) {
        geojsonDataRef.current = new Map();
        setGeojsonVersion((v) => v + 1);
      }
      return;
    }
    let cancelled = false;
    async function fetchAll() {
      const newMap = new Map<string, GeoJSON.FeatureCollection>();
      await Promise.all(
        boundedGeoJsonLayers.map(async ({ layer, key }) => {
          try {
            const data = await fetchBoundedGeoJson(layer.dataset_id, { apiKey, embedToken });
            if (!cancelled) {
              const eligibility = getClusterSourceEligibility(layer);
              const isClusterLayer = isClusterRenderMode(layer);
              if (!isClusterLayer || (!data.truncated && data.total_count <= eligibility.limit)) {
                newMap.set(key, asFeatureCollection(data));
              }
            }
          } catch (e) {
            if (import.meta.env.DEV) console.warn(`[ViewerMap] Bounded GeoJSON fetch failed for ${layer.dataset_id}:`, e);
            toast.error(t('viewer.geoJsonLoadError', { defaultValue: 'Failed to load layer data' }), { id: `geojson-z-error-${layer.dataset_id}` });
          }
        }),
      );
      if (!cancelled) {
        geojsonDataRef.current = newMap;
        setGeojsonVersion((v) => v + 1);
      }
    }
    fetchAll().catch(() => {
      // Individual layer errors are already toasted above; this only fires on unexpected scaffolding failure
    });
    return () => { cancelled = true; };
  }, [boundedGeoJsonLayers, apiKey, embedToken, t]);

  // Trigger repaint when GeoJSON-Z data arrives and map is ready
  useEffect(() => {
    if (geojsonVersion === 0) return;
    const map = mapRef.current;
    if (map && mapReady) map.triggerRepaint();
  }, [geojsonVersion, mapReady]);

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
        const status = e.error?.status;
        // Suppress expected no-data tiles (404) and other client errors
        if (status && status >= 400 && status < 500) {
          return;
        }
        // Surface server errors (5xx) and unknown errors
        if (import.meta.env.DEV) console.warn('[ViewerMap] Map error:', e.error);
        if (!status || status >= 500) {
          toast.error(t('viewer.mapError', { defaultValue: 'Map tile error — some layers may not display correctly.' }), {
            id: 'viewer-map-error',
          });
        }
      });

      map.on('styleimagemissing', (event: { id: string }) => {
        if (!map.hasImage(event.id)) {
          map.addImage(event.id, { width: 1, height: 1, data: new Uint8Array(4) });
        }
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
      layerEntries
        .filter(({ key }) => visibleLayers.has(key))
        .filter(({ layer }) => layer.style_config?.render_mode !== 'heatmap')
        .flatMap(({ layer, key }) => {
          const layerId = prefixed('layer', key, VIEWER_PREFIX);
          return isClusterRenderMode(layer) ? clusterInteractiveLayerIds(layerId) : [layerId];
        }),
    [layerEntries, visibleLayers],
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

  // O(1) lookup: feature.layer.id (with `viewer-layer-` prefix) → layer/source metadata.
  const layerByMapIdRef = useRef<Map<string, { layer: SharedLayerResponse; sourceId: string }>>(new Map());
  useEffect(() => {
    const m = new Map<string, { layer: SharedLayerResponse; sourceId: string }>();
    for (const { layer, key } of layerEntries) {
      const layerId = prefixed('layer', key, VIEWER_PREFIX);
      const sourceId = prefixed('source', key, VIEWER_PREFIX);
      const ids = isClusterRenderMode(layer) ? clusterInteractiveLayerIds(layerId) : [layerId];
      for (const id of ids) m.set(id, { layer, sourceId });
    }
    layerByMapIdRef.current = m;
  }, [layerEntries]);

  // Resolve a hit to its layer config; returns null when the layer is unknown
  // (verifies the prefix matched) or popups are explicitly disabled.
  const lookupHitLayer = useCallback((featureLayerId: string, includePopupDisabled = false) => {
    const hit = layerByMapIdRef.current.get(featureLayerId);
    if (!hit) return null;
    if (!includePopupDisabled && hit.layer.popup_config?.enabled === false) return null;
    return hit;
  }, []);

  // Click handler: show popup with feature attributes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const fallbackName = t('viewer.featureFallback');
    const buildClusterPopup = (feature: Parameters<typeof isClusterFeature>[0], hit: { layer: SharedLayerResponse; sourceId: string }) => (
      clusterAggregateFeatureInfo(feature, {
        layerName: hit.layer.display_name || hit.layer.dataset_name || fallbackName,
        sourceKind: getClusterSourceStrategy(hit.layer).kind,
        locale: i18n.language,
      })
    );

    const handleClusterHit = (
      feature: Parameters<typeof isClusterFeature>[0],
      hit: { layer: SharedLayerResponse; sourceId: string },
      fallbackLngLat: { lng: number; lat: number } | null,
    ) => {
      const coordinates = clusterFeatureCoordinates(feature);
      if (hit.layer.popup_config?.enabled !== false) {
        const info = buildClusterPopup(feature, hit);
        setPopupInfo({
          longitude: coordinates?.[0] ?? fallbackLngLat?.lng ?? 0,
          latitude: coordinates?.[1] ?? fallbackLngLat?.lat ?? 0,
          features: [info],
        });
      } else {
        setPopupInfo(null);
      }
      void activateClusterFeature(map, feature, hit.sourceId);
    };

    const findClusterHit = (hits: ReturnType<MaplibreMap['queryRenderedFeatures']>) => {
      for (const feature of hits) {
        if (!isClusterFeature(feature)) continue;
        const hit = lookupHitLayer(feature.layer.id, true);
        if (hit) return { feature, hit };
      }
      return null;
    };

    const handleClick = (e: MapMouseEvent) => {
      const hits = queryInteractiveFeatures(map, e.point);
      if (hits === null) {
        setPopupInfo(null);
        return;
      }

      const clusterHit = findClusterHit(hits);
      if (clusterHit) {
        handleClusterHit(clusterHit.feature, clusterHit.hit, e.lngLat);
        return;
      }

      const mapped: FeatureInfo[] = [];
      for (const feature of hits) {
        const hit = lookupHitLayer(feature.layer.id);
        if (!hit) continue;
        const layer = hit.layer;
        const cfg = hit.layer.popup_config;
        const props = (feature.properties ?? {}) as Record<string, unknown>;
        mapped.push({
          properties: props,
          layerName: layer.display_name || layer.dataset_name || fallbackName,
          columnInfo: layer.column_info ?? null,
          title: cfg?.expression ? substitutePopupTemplate(cfg.expression, props) : null,
          visibleFields: cfg?.visible_fields ?? null,
        });
      }

      if (mapped.length > 0) {
        setPopupInfo({
          longitude: e.lngLat.lng,
          latitude: e.lngLat.lat,
          features: mapped,
        });
      } else {
        setPopupInfo(null);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      let canvas: HTMLCanvasElement | null = null;
      try {
        canvas = map.getCanvas();
      } catch {
        return;
      }
      if (!canvas) return;
      const point = {
        x: (canvas.clientWidth || canvas.width) / 2,
        y: (canvas.clientHeight || canvas.height) / 2,
      } as MapMouseEvent['point'];
      const hits = queryInteractiveFeatures(map, point);
      if (hits === null) return;
      const clusterHit = findClusterHit(hits);
      if (!clusterHit) return;
      event.preventDefault();
      handleClusterHit(clusterHit.feature, clusterHit.hit, null);
    };

    map.on('click', handleClick);
    let canvasForKeyboard: HTMLCanvasElement | null = null;
    try {
      canvasForKeyboard = map.getCanvas();
      canvasForKeyboard?.addEventListener?.('keydown', handleKeyDown);
    } catch {
      canvasForKeyboard = null;
    }
    return () => {
      map.off('click', handleClick);
      canvasForKeyboard?.removeEventListener?.('keydown', handleKeyDown);
    };
  }, [mapReady, t, queryInteractiveFeatures, lookupHitLayer]);

  // Mousemove: pointer cursor on interactive features
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    let rafId = 0;
    const handleMouseMove = (e: MapMouseEvent) => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        let canvas;
        try {
          canvas = map.getCanvas();
        } catch {
          return;
        }
        if (!canvas) return;
        const features = queryInteractiveFeatures(map, e.point);
        if (features === null) {
          canvas.style.cursor = '';
          return;
        }
        // Mirror handleClick's per-feature filter: cursor goes pointer only
        // when at least one hit is a cluster or on a popup-enabled layer.
        const interactive = features.some((f) => {
          const hit = lookupHitLayer(f.layer.id, true);
          if (!hit) return false;
          return isClusterFeature(f) || hit.layer.popup_config?.enabled !== false;
        });
        canvas.style.cursor = interactive ? 'pointer' : '';
      });
    };

    map.on('mousemove', handleMouseMove);
    return () => {
      cancelAnimationFrame(rafId);
      map.off('mousemove', handleMouseMove);
      try {
        const canvas = map.getCanvas();
        if (canvas) canvas.style.cursor = '';
      } catch {
        // Map already torn down — nothing to reset.
      }
    };
  }, [mapReady, queryInteractiveFeatures, lookupHitLayer]);

  // Clear popup when layer visibility changes
  useEffect(() => {
    setPopupInfo(null);
  }, [visibleLayers]);

  // Ref to hold current sync inputs so the style.load callback can access them
  const syncInputsRef = useRef({ layers, visibleLayers, tokenMap, tileConfig, showBasemapLabels, basemapConfig });
  syncInputsRef.current = { layers, visibleLayers, tokenMap, tileConfig, showBasemapLabels, basemapConfig };

  const applyViewerBasemapConfig = useCallback((map: MaplibreMap) => {
    if (!map.isStyleLoaded()) return;
    applyBasemapConfigToMap(map, basemapConfig, showBasemapLabels, VIEWER_SOURCE_PREFIX);
  }, [basemapConfig, showBasemapLabels]);

  /** Wrapper: convert viewer state to normalized inputs and call unified syncLayersToMap */
  const runSync = useCallback((map: MaplibreMap) => {
    const { layers: ls, visibleLayers: vl, tokenMap: tm, tileConfig: tc, showBasemapLabels: sbl } = syncInputsRef.current;
    const tileBaseUrl = resolveTileBaseUrl(tc);
    const syncInputs: SyncLayerInput[] = createViewerLayerEntries(ls).map(({ layer, key }) => (
      toViewerSyncInput(layer, key, vl)
    ));
    const syncOpts: SyncOptions = { idPrefix: VIEWER_PREFIX, showBasemapLabels: sbl };
    syncLayersToMap(map, syncInputs, tm, tileBaseUrl, managedSourcesRef, prevOrderKeyRef, geojsonDataRef.current, syncOpts);
    applyViewerBasemapConfig(map);
  }, [applyViewerBasemapConfig]);

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
  // Note: visibleLayers intentionally excluded — the dedicated visibility effect below handles it
  }, [layers, mapReady, tileConfig?.cdn_base_url, tokenMap, showBasemapLabels, runSync, embedToken, geojsonVersion]);

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
  // NOTE: The setTiles call intentionally duplicates what syncLayersToMap does —
  // this effect fires on token refresh alone without triggering a full layer sync.
  const cdnBaseUrl = tileConfig?.cdn_base_url;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || (!embedToken && tokenMap.size === 0)) return;
    const tileBaseUrl = resolveTileBaseUrl({ cdn_base_url: cdnBaseUrl });

    for (const { layer, key } of layerEntries) {
      const token = tokenMap.get(layer.dataset_id) ?? null;
      // Skip rasters — their tile_url is stable, no refresh needed.
      if (token && token.kind !== 'vector') continue;
      const sourceId = prefixed('source', key, VIEWER_PREFIX);
      const source = map.getSource(sourceId);
      // Only vector sources need query-param URL refreshes.
      if (source && source.type === 'vector') {
        const strategy = getClusterSourceStrategy(layer);
        const builder = layer.style_config?.builder;
        // Per-layer source in viewer context (no dedupe by table_name), so
        // the column set comes from THIS layer only.
        const cols = strategy.kind === 'server-tile'
          ? null
          : getDataDrivenColumnsForLayer({
              style_config: layer.style_config ?? null,
              paint: (layer.paint as Record<string, unknown> | undefined) ?? {},
            });
        const newUrl = strategy.kind === 'server-tile'
          ? buildClusterTileUrl(layer.table_name, token, tileBaseUrl, undefined, {
              clusterRadius: typeof builder?.clusterRadius === 'number' ? builder.clusterRadius : 48,
              clusterMaxZoom: typeof builder?.clusterMaxZoom === 'number' ? builder.clusterMaxZoom : 14,
            })
          : buildSignedTileUrl(layer.table_name, token, tileBaseUrl, undefined, cols);
        (source as VectorTileSource).setTiles([newUrl]);
      }
    }
  }, [tokenMap, layerEntries, mapReady, cdnBaseUrl, embedToken]);

  // Toggle visibility when visibleLayers set changes.
  // Note: runSync also calls syncVisibility via syncLayersToMap, but this
  // dedicated effect is needed for *visibility-only* changes where other
  // sync inputs (layers, tokenMap) haven't changed.
  const prevVisibleRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const prev = prevVisibleRef.current;
    for (const { layer, key } of layerEntries) {
      const wasVisible = prev.has(key);
      const isVisible = visibleLayers.has(key);
      if (wasVisible === isVisible) continue;

      const type = layer.is_dem === true && layer.style_config?.render_mode === 'hillshade'
        ? 'hillshade'
        : resolveAdapterType(layer.geometry_type, layer.style_config, layer.paint as Record<string, unknown>);
      const adapter = getAdapter(type);
      const adapterInput = toAdapterInput(layer, key, visibleLayers);
      adapter.syncVisibility(map, adapterInput);

      const labelId = prefixed('label', key, VIEWER_PREFIX);
      if (map.getLayer(labelId)) {
        map.setLayoutProperty(labelId, 'visibility', isVisible ? 'visible' : 'none');
      }
    }
    prevVisibleRef.current = new Set(visibleLayers);
  }, [visibleLayers, layerEntries, mapReady]);

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
      // Also match the main sync effect's token gate so private vector
      // sources are never created with transient unsigned tile URLs.
      const hasLayers = syncInputsRef.current.layers.length > 0;
      const hasTokens = syncInputsRef.current.tokenMap.size > 0;
      if (hasLayers && (embedToken || hasTokens)) {
        runSync(map);
      }
      // style.load wipes all custom sources; re-seed terrain source if a DEM is present.
      reseedTerrainOnStyleLoad();
      applyViewerBasemapConfig(map);
    };

    map.on('style.load', onStyleLoad);
    return () => {
      map.off('style.load', onStyleLoad);
    };
  }, [mapReady, runSync, reseedTerrainOnStyleLoad, applyViewerBasemapConfig]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    applyViewerBasemapConfig(map);
  }, [basemapConfig, showBasemapLabels, mapReady, applyViewerBasemapConfig]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      mapRef.current = null;
    };
  }, []);

  const defaultView = useMemo(() => ({
    longitude: initialViewState.center_lng,
    latitude: initialViewState.center_lat,
    zoom: initialViewState.zoom,
    bearing: initialViewState.bearing,
    pitch: initialViewState.pitch,
  }), [initialViewState.center_lng, initialViewState.center_lat, initialViewState.zoom, initialViewState.bearing, initialViewState.pitch]);

  const { contextLost, reload } = useWebGLRecovery(mapRef, mapReady);

  return (
    <div
      className={`relative h-full w-full ${!mapReady ? 'bg-muted animate-pulse' : ''}`}
      data-tiles-loaded={tilesIdle ? 'true' : 'false'}
      data-terrain-ready={terrainReady ? 'true' : 'false'}
    >
      <MapGL
        initialViewState={defaultView}
        mapStyle={mapStyle}
        styleDiffing={false}
        style={{ width: '100%', height: '100%' }}
        attributionControl={false}
        minZoom={1}
        onLoad={handleLoad}
        aria-label={t('viewer.legend.title')}
      >
        <NavigationControl position="top-right" />
        <FullscreenControl position="top-right" />
        {terrainReady && (
          <TerrainControl source="terrain-dem" position="top-right" />
        )}
        <ScaleControl position="bottom-left" maxWidth={100} unit="metric" />
        <AttributionControl position="bottom-right" compact={true} />
        {popupInfo && (
          <FeaturePopup
            longitude={popupInfo.longitude}
            latitude={popupInfo.latitude}
            features={popupInfo.features}
            onClose={() => setPopupInfo(null)}
          />
        )}
      </MapGL>
      <MapCoordReadout map={mapRef.current} />
      {contextLost && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80">
          <div className="text-center space-y-2">
            <p className="text-sm text-muted-foreground">{t('errorBoundary.mapMessage')}</p>
            <button type="button" onClick={reload} className="text-sm underline text-primary hover:text-primary/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring rounded px-1">{t('reload')}</button>
          </div>
        </div>
      )}
    </div>
  );
});
