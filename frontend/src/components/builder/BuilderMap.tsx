import { useEffect, useRef, useCallback, useState, useMemo, memo } from 'react';
import { usePluginStore } from '@/stores/map-plugin-store';
import { useMapDrawStore } from '@/stores/map-draw-store';
import { isPluginIdAvailable } from '@/components/map-plugins';
import { toast } from 'sonner';
import { Map as MapGL, NavigationControl, ScaleControl } from '@vis.gl/react-maplibre';
import { useBasemaps, useEnabledPlugins, useMapDefaults, useTileConfig } from '@/hooks/use-settings';
import {
  findBasemapById,
  makeStyleImageMissingResolver,
  toMaplibreStyle,
  BLANK_BASEMAP_ID,
  FALLBACK_BASEMAP_STYLE_URL,
} from '@/lib/basemap-utils';
import { buildTileTransformRequest, isMvtSourceLayerConfigReady, refreshRasterTileSources } from '@/lib/tile-utils';
import { toMapLibreAttribution } from '@/lib/attribution-safety';
import { useRemoteBasemapStyle } from '@/components/map/hooks/use-remote-basemap-style';
import { isRasterTileAuthError, isRefreshableRasterAuthError, logUnhandledMapError } from '@/lib/map-error-log';
import { useTileTokens, useInvalidateTileTokens } from '@/hooks/use-tile-token';
import { isSessionRenewalPending, useTileAuthRecovery, useVisibleTileTokenRefresh } from '@/hooks/use-tile-auth-recovery';
import { useTileTokenError } from './hooks/use-tile-token-error';
import { getEnvConfig } from '@/lib/env';
import { pushReportEntry, reportTileTokenRemint } from '@/lib/report';
import { useAuthStore } from '@/stores/auth-store';
import { useWebGLRecovery } from '@/hooks/use-webgl-recovery';
import i18n from '@/i18n/i18n';
import { useTranslation } from 'react-i18next';
import { useMapLocale } from '@/hooks/use-map-locale';
import { asFeatureCollection, fetchBoundedGeoJson } from '@/api/geojson-z';
import { FeaturePopup, type FeatureInfo } from '@/components/map/FeaturePopup';
import {
  activateClusterFeature,
  clusterAggregateFeatureInfo,
  clusterFeatureCoordinates,
  clusterInteractiveLayerIds,
  isClusterFeature,
} from '@/components/map/cluster-interactions';
import { substitutePopupTemplate } from '@/lib/popup-template';
import { MapCoordReadout } from '@/components/map/MapCoordReadout';
import { getClusterSourceEligibility, getClusterSourceKey, getClusterSourceStrategy, isClusterRenderMode, shouldFetchClusterGeoJson, type ClusterSourceStatus } from './cluster-source';
import type { VectorTileSource } from 'maplibre-gl';
import {
  toSyncInput,
  getSourceIdForLayer,
  getLayerId,
  ensureRasterDemTerrainSource,
  normalizeTerrainExaggeration,
  refreshVectorSourceTiles,
  registerBasemapStyleGeneration,
  syncRenderContext,
  TERRAIN_SOURCE_ID,
} from './map-sync';
import { describeLayers } from './layer-description';
import { resolveTerrainSourceLayer } from './map-stack';
import { isGenericGeometryType } from './layer-adapters/shared';
import { mixedInteractiveLayerIds } from './layer-adapters/mixed-adapter';
import { maybeWarnSmallDemCoverage, resetSmallDemWarning } from './terrain-coverage';
import { applyMapBasemapAppearance, syncMapComposition } from './map-composition-sync';
import type { MapLibreEvent, MapMouseEvent } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapBasemapConfig, MapLayerResponse, MapTerrainConfig } from '@/types/api';
import type { TileToken } from '@/api/tiles';
import { getVisibleLayerBounds, visibleLayerBoundsKey, clampMinZoomAfterFit } from './builder-bounds';
import 'maplibre-gl/dist/maplibre-gl.css';
// Wires maplibre v6's worker URL. Side-effect import, kept out of
// main.tsx so map-vendor stays out of the eager entry graph.
import '@/lib/maplibre-worker';

/**
 * Map builder canvas, the editable composition surface used by
 * `MapBuilderPage`.
 *
 * Renders authenticated tile layers over a basemap, with imperative tile
 * signing and live re-styling as the user edits paint, filters and layer order.
 * Mousemove is throttled with `requestAnimationFrame` to keep layer-heavy maps
 * responsive.
 *
 * Pairs with the read-only `ViewerMap`; both share the `layer-adapters`
 * registry and `map-sync` helpers so styling renders identically when editing
 * and viewing.
 */
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
  terrainConfig?: MapTerrainConfig | null;
  basemapConfig?: MapBasemapConfig | null;
  onMapRef?: (map: MaplibreMap | null) => void;
  showBasemapLabels?: boolean;
  /** Called when the user clicks a map feature. `null` when clicking empty space. */
  onFeatureSelect?: (feature: FeatureInfo | null) => void;
}

// The five statuses that leave a cluster layer rendering as points, mapped to
// their builderMap.clusterReason.* translation key. 'not-cluster' and
// 'eligible' never reach getClusterFallbackReasonKey's caller below.
const CLUSTER_FALLBACK_REASON_KEYS: Partial<Record<ClusterSourceStatus, string>> = {
  'missing-count': 'builderMap.clusterReason.missingCount',
  'too-many-features': 'builderMap.clusterReason.tooManyFeatures',
  'not-point': 'builderMap.clusterReason.notPoint',
  'not-vector': 'builderMap.clusterReason.notVector',
  'unsupported-record-type': 'builderMap.clusterReason.unsupportedRecordType',
};

function getClusterFallbackReasonKey(status: ClusterSourceStatus): string | null {
  return CLUSTER_FALLBACK_REASON_KEYS[status] ?? null;
}

/**
 * Additive per-source vector-tile 401/403 re-sign-and-retry.
 *
 * During drag-from-catalog a vector source can be added and MapLibre may
 * request a `.pbf` before the signed `tile_url`/`sig` finishes attaching,
 * producing a transient 401/403 that is a token-sync race, not a real auth
 * failure.
 *
 * Re-signs ONLY the failing source using the token already in `tokenMap` for
 * that layer's own dataset_id (the URL the layer description gives the source,
 * as the sync pass signs it) and calls `setTiles([newUrl])` exactly once so
 * MapLibre re-fetches with a fresh sig. It never fabricates, broadens or
 * cross-assigns a token, and never alters the raster path.
 *
 * Returns `true` when it re-signed and the caller should suppress the auth
 * toast; `false` (no setTiles) when the case is non-recoverable: no matching
 * layer, no source, source not vector, or no token in `tokenMap` for that
 * dataset. One re-sign per error event; MapLibre owns the single retry, so
 * there is no unbounded loop.
 *
 * This reduces the race but does not deterministically eliminate it.
 */
type BuilderTileConfig = { cdn_base_url?: string | null; mvt_source_layer_prefix?: string | null };

/**
 * The sources a sync pass describes for these layers; the re-sign and refresh
 * paths sign from them.
 */
function describeBuilderSources(
  layers: MapLayerResponse[],
  tokenMap: Map<string, TileToken>,
  tileConfig: BuilderTileConfig | null | undefined,
  boundedGeoJson?: ReadonlyMap<string, GeoJSON.FeatureCollection>,
) {
  const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url || undefined;
  const context = syncRenderContext(tokenMap, tileBaseUrl, boundedGeoJson, {
    mvtSourceLayerPrefix: tileConfig?.mvt_source_layer_prefix,
  });
  return describeLayers(layers.map(toSyncInput), context).sources;
}

export function resignVectorSourceForRetry(
  map: MaplibreMap,
  sourceId: string,
  layers: MapLayerResponse[],
  tokenMap: Map<string, TileToken>,
  tileConfig?: BuilderTileConfig | null,
): boolean {
  const layer = layers.find((l) => getSourceIdForLayer(l) === sourceId);
  if (!layer) return false;

  const token = tokenMap.get(layer.dataset_id) ?? null;
  // Raster tiles use the nginx auth-check subrequest (Authorization header via
  // setTransformRequest), not a query-param sig — nothing to re-sign here.
  if (!token || token.kind === 'raster') return false;

  const source = map.getSource(sourceId);
  if (!source || source.type !== 'vector') return false;

  // No source is synced while the tenant prefix is unresolved, and describing would throw.
  if (tileConfig?.mvt_source_layer_prefix === null) return false;
  const spec = describeBuilderSources(layers, tokenMap, tileConfig).get(sourceId);
  if (spec?.type !== 'vector' || !spec.tiles?.[0]) return false;
  (source as VectorTileSource).setTiles([spec.tiles[0]]);
  return true;
}

export function shouldSuppressBuilderMapError(error: { message?: string; status?: number } | null | undefined) {
  if (error?.status) return false;
  const message = String(error?.message ?? '').toLowerCase();
  if (!message) return false;

  return (
    message.includes('dem dimension mismatch') ||
    (message.includes(TERRAIN_SOURCE_ID) && (
      message.includes('not found') ||
      message.includes('source') ||
      message.includes('terrain')
    )) ||
    (message.includes('raster-dem') && (
      message.includes('maxzoom') ||
      message.includes('dimension') ||
      message.includes('terrain')
    ))
  );
}

export const BuilderMap = memo(function BuilderMap({
  layers,
  basemapStyle,
  initialViewState,
  terrainConfig = null,
  basemapConfig = null,
  onMapRef,
  showBasemapLabels = true,
  onFeatureSelect,
}: BuilderMapProps) {
  const { t } = useTranslation('builder');
  const mapLocale = useMapLocale();
  const mapRef = useRef<MaplibreMap | null>(null);
  const managedSourcesRef = useRef<Set<string>>(new Set());
  // Mount-time projection for the MapGL prop, frozen because a CHANGED prop
  // hits react-maplibre's unguarded _updateSettings setter, which throws mid
  // style-swap; runtime toggles go through applyMapBasemapAppearance.
  const [initialProjection] = useState(() => basemapConfig?.projection ?? 'mercator');
  const errorHandlerRef = useRef<((e: { error: { message?: string; status?: number }; sourceId?: string }) => void) | null>(null);
  const styleImageMissingHandlerRef = useRef<((id: string) => void) | null>(null);
  // Held so unmount detaches them symmetrically with the
  // error/styleimagemissing handlers.
  const dataLoadingHandlerRef = useRef<(() => void) | null>(null);
  const idleHandlerRef = useRef<(() => void) | null>(null);
  // Re-arming data-tiles-loaded handlers, held for symmetric detach on unmount.
  const tilesIdleMovestartHandlerRef = useRef<(() => void) | null>(null);
  const tilesIdleIdleHandlerRef = useRef<(() => void) | null>(null);
  // Latch first-load success so transient 5xx during save don't surface as outage
  const basemapLoadedAtRef = useRef<number | null>(null);
  // True when a 5xx/unknown tile error fired since the last 'dataloading', so
  // the idle handler clears the 'tiles' basemap notice only after a clean load
  // cycle.
  const sawTileErrorSinceLoadingRef = useRef(false);
  const lastOrderKeyRef = useRef('');
  const [mapReady, setMapReady] = useState(false);
  // State mirror of mapRef.current so MapCoordReadout consumes the map via
  // state rather than reading a ref during render.
  const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);
  const [tilesLoading, setTilesLoading] = useState(false);
  const [basemapNotice, setBasemapNotice] = useState<'style' | 'tiles' | null>(null);
  // `tilesIdle` drives the `data-tiles-loaded` attribute on the outer
  // container, mirroring ViewerMap, so the Playwright showcase-smoke spec can
  // poll a deterministic signal whether /maps/:id resolved to BuilderMap or
  // ViewerMap (via MapViewerGate).
  const [tilesIdle, setTilesIdle] = useState(false);
  const [popupInfo, setPopupInfo] = useState<{
    longitude: number;
    latitude: number;
    features: FeatureInfo[];
  } | null>(null);

  const { data: basemaps } = useBasemaps();
  const { data: mapDefaults } = useMapDefaults();
  const { data: tileConfig } = useTileConfig();
  // MapLibre does not support changing a layer's source-layer in place. Wait
  // for the tenant-aware MVT prefix before the first composition so an async
  // settings response cannot permanently install the Community `data.*` name.
  const tileConfigReady = isMvtSourceLayerConfigReady(tileConfig);
  const enabledPluginsQuery = useEnabledPlugins();
  const enabledPluginIds = useMemo(
    () => enabledPluginsQuery.data ?? (enabledPluginsQuery.isLoading ? [] : null),
    [enabledPluginsQuery.data, enabledPluginsQuery.isLoading],
  );
  const isBlank = basemapStyle === BLANK_BASEMAP_ID;
  const basemapEntry = isBlank ? undefined : findBasemapById(basemaps ?? [], basemapStyle);
  const fallbackUrl = FALLBACK_BASEMAP_STYLE_URL;
  const styleValue = useMemo(
    () => isBlank
      ? toMaplibreStyle(BLANK_BASEMAP_ID)
      : toMaplibreStyle(basemapEntry?.url ?? fallbackUrl, basemapEntry?.attribution),
    [isBlank, basemapEntry?.url, basemapEntry?.attribution, fallbackUrl],
  );
  // Shared fetch-and-sanitize path (see use-remote-basemap-style).
  // Builder-specific behavior rides the callbacks: reset the first-load latch
  // on fetch start, clear the notice and latch success, surface the 'style'
  // notice on failure. No raw-URL fallback on failure: the second fetch is
  // uncancelable and can flash an intermediate state, so the placeholder and
  // notice banner stay.
  const mapStyle = useRemoteBasemapStyle({
    styleValue,
    mapRef,
    logLabel: 'BuilderMap',
    onFetchStart: useCallback(() => {
      // Reset the latch on basemap change so a new basemap's first-load failure
      // surfaces.
      basemapLoadedAtRef.current = null;
    }, []),
    onFetchSuccess: useCallback(() => {
      setBasemapNotice(null);
      // Latch first-load success so transient 5xx during save don't surface as
      // outage.
      basemapLoadedAtRef.current = Date.now();
    }, []),
    onFetchError: useCallback(() => {
      setBasemapNotice('style');
    }, []),
  });
  // Null for a style URL that MapLibre loads itself.
  const basemapSourceIds = useMemo(
    () => (typeof mapStyle === 'string' ? null : new Set(Object.keys(mapStyle.sources ?? {}))),
    [mapStyle],
  );
  const basemapSourceIdsRef = useRef(basemapSourceIds);
  basemapSourceIdsRef.current = basemapSourceIds;

  // Stable dataset ID list — only changes when layers are added/removed, not on paint edits
  const datasetIdKey = layers.map((l) => l.dataset_id).join(',');
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

  // Surface a deduped toast when the tile-token batch query fails, so the user
  // sees an error instead of a silent empty map.
  const tokenBatchIsError = tokenQueries.length > 0 && tokenQueries.some((q) => q.isError);
  useTileTokenError(tokenBatchIsError);

  const clusterGeoJsonDataRef = useRef<Map<string, GeoJSON.FeatureCollection>>(new Map());
  const clusterFallbackNotifiedRef = useRef<Set<string>>(new Set());
  const [clusterGeoJsonVersion, setClusterGeoJsonVersion] = useState(0);
  // Key the fetch effect on a structural signature, not the layers array:
  // paint/opacity/filter edits replace the array identity on every debounce
  // tick (~10Hz during a slider drag) and would re-issue a GeoJSON fetch per
  // bounded-geojson cluster layer each tick.
  const clusterSourceKey = useMemo(() => getClusterSourceKey(layers), [layers]);

  useEffect(() => {
    let cancelled = false;
    const clusterSourceLayers = layersRef.current.filter((layer) => isClusterRenderMode(layer));
    if (clusterSourceLayers.length === 0) {
      if (clusterGeoJsonDataRef.current.size > 0) {
        clusterGeoJsonDataRef.current = new Map();
        setClusterGeoJsonVersion((version) => version + 1);
      }
      return () => {
        cancelled = true;
      };
    }

    const controller = new AbortController();
    async function fetchClusterSources() {
      const next = new Map<string, GeoJSON.FeatureCollection>();
      await Promise.all(clusterSourceLayers.map(async (layer) => {
        const eligibility = getClusterSourceEligibility(layer);
        const strategy = getClusterSourceStrategy(layer);
        const layerName = layer.display_name || layer.dataset_name || layer.dataset_table_name;
        if (strategy.kind === 'server-tile') {
          return;
        }
        if (!shouldFetchClusterGeoJson(layer)) {
          const reasonKey = getClusterFallbackReasonKey(eligibility.status);
          const key = `${layer.id}:${eligibility.status}:${eligibility.featureCount ?? 'unknown'}`;
          if (reasonKey && !clusterFallbackNotifiedRef.current.has(key)) {
            clusterFallbackNotifiedRef.current.add(key);
            toast.warning(t('builderMap.clusterFallback', {
              defaultValue: '{{name}} is rendering as points: {{reason}}',
              name: layerName,
              reason: t(reasonKey),
            }));
          }
          return;
        }
        try {
          const response = await fetchBoundedGeoJson(layer.dataset_id, { signal: controller.signal });
          if (response.truncated || response.total_count > eligibility.limit) {
            const key = `${layer.id}:truncated:${response.total_count}`;
            if (!clusterFallbackNotifiedRef.current.has(key)) {
              clusterFallbackNotifiedRef.current.add(key);
              toast.warning(t('builderMap.clusterFallback', {
                defaultValue: '{{name}} is rendering as points: {{reason}}',
                name: layerName,
                reason: t('builderMap.clusterTruncated', {
                  defaultValue: 'cluster source exceeded the bounded GeoJSON limit',
                }),
              }));
            }
            return;
          }
          next.set(layer.id, asFeatureCollection(response));
        } catch (error) {
          if (controller.signal.aborted) return;
          if (import.meta.env.DEV) console.warn(`[BuilderMap] Cluster GeoJSON fetch failed for ${layer.dataset_id}:`, error);
          const key = `${layer.id}:fetch-error`;
          if (!clusterFallbackNotifiedRef.current.has(key)) {
            clusterFallbackNotifiedRef.current.add(key);
            toast.warning(t('builderMap.clusterLoadError', {
              defaultValue: '{{name}} is rendering as points because cluster data could not load.',
              name: layerName,
            }));
          }
        }
      }));
      if (!cancelled) {
        clusterGeoJsonDataRef.current = next;
        setClusterGeoJsonVersion((version) => version + 1);
      }
    }

    fetchClusterSources().catch(() => {
      // Individual layer errors are handled above.
    });
    return () => {
      cancelled = true;
      controller.abort();
    };
    // layers is read through layersRef (always fresh post-render);
    // clusterSourceKey covers every field that changes what gets fetched.
  }, [clusterSourceKey, t]);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the primitive join is the intended dep; the array identity churns each render
  }, [datasetIds.join(','), tokenSig]);

  const terrainStateRef = useRef({ terrainConfig, layers, tokenMap });
  terrainStateRef.current = { terrainConfig, layers, tokenMap };

  const applyTerrainConfig = useCallback(function apply() {
    const map = mapRef.current;
    if (!map) return;
    // The post-basemap-swap path re-applies terrain via a SINGLE `once('idle',
    // applyTerrainConfig)`. When that idle lands mid style-transition a silent
    // return would drop the apply for good, leaving an enabled terrain_config
    // rendering flat until an unrelated dep changes. Re-arm on the next idle
    // instead; double-applies are idempotent.
    if (!map.isStyleLoaded()) {
      map.once('idle', apply);
      return;
    }

    const { terrainConfig: currentTerrainConfig, layers: currentLayers, tokenMap: currentTokenMap } = terrainStateRef.current;
    if (!currentTerrainConfig?.enabled || !currentTerrainConfig.source_dataset_id) {
      map.setTerrain(null);
      // Terrain off: clear the small-DEM warning dedupe so re-enabling (or
      // selecting a different DEM) can warn again.
      resetSmallDemWarning(map);
      return;
    }

    // Resolve the terrain DEM by source_dataset_id + isTerrainCapableDemLayer
    // ONLY, not render_mode === 'terrain', matching the viewer resolver
    // (viewer/hooks/use-viewer-terrain.ts) so a DEM in hillshade mode can drive
    // the 3D mesh and paint its 2D relief on one dataset. Shared with
    // MapBuilderPage's isTerrainActive so render state and settings status
    // can't drift.
    const demLayer = resolveTerrainSourceLayer(currentLayers, currentTerrainConfig);
    const token = demLayer ? currentTokenMap.get(demLayer.dataset_id) : null;
    // Honor the layer's visibility eye; undefined counts as visible.
    const demLayerVisible = demLayer?.visible !== false;
    const effectiveTerrainEnabled = currentTerrainConfig.enabled === true && demLayerVisible;
    if (!demLayer || token?.kind !== 'raster' || !effectiveTerrainEnabled) {
      map.setTerrain(null);
      return;
    }

    ensureRasterDemTerrainSource(map, token.tile_url, {
      tileSize: token.tile_size,
      minzoom: token.minzoom,
      maxzoom: token.maxzoom,
      bounds: token.bounds,
      // A terrain-mode DEM has no visible layer, so the attributed source its
      // adapter created is unreferenced and MapLibre does not count it; this
      // one is counted through usedForTerrain.
      attribution: toMapLibreAttribution(demLayer.dataset_attribution),
    });
    map.setTerrain({
      source: TERRAIN_SOURCE_ID,
      exaggeration: normalizeTerrainExaggeration(currentTerrainConfig.exaggeration),
    });
    map.triggerRepaint();

    // Warn (once per enable) when this DEM covers only a small slice of the
    // current viewport: a small high-res DEM zoomed out reads as a pedestal.
    // Keep the active dataset's dedupe key, drop any stale one.
    resetSmallDemWarning(map, currentTerrainConfig.source_dataset_id);
    // The LAYER's extent, not the token's bounds. Both come from
    // `records.spatial_extent`, but the token applies `extent_to_span_bbox`
    // (processing/tiles/router.py) because a tile source cannot be bounded by a
    // west > east pair. That flattens a Fiji-shaped DEM to [-180, s, 180, n],
    // bit-identical to a global one, so the guard would read 100% coverage for
    // a DEM occupying a fifth of the screen. `dataset_extent_bbox` is the RFC
    // 7946 form, so the crossing survives.
    //
    // The fallback is reachable only if the two conversions disagree about the
    // same non-null column; it keeps the warning rather than silently deleting
    // it.
    maybeWarnSmallDemCoverage({
      map,
      demBounds: demLayer.dataset_extent_bbox ?? token.bounds,
      dedupeKey: currentTerrainConfig.source_dataset_id,
    });
  }, []);

  const terrainLayerKey = layers
    .map((layer) => {
      const renderMode = (layer.style_config as { render_mode?: unknown } | null | undefined)?.render_mode;
      return `${layer.dataset_id}:${String(layer.is_dem)}:${layer.dataset_record_type ?? ''}:${String(renderMode ?? '')}:${String(layer.visible)}`;
    })
    .join(',');

  // Keep a ref to the latest sync inputs so style.load handler can access them
  const syncInputsRef = useRef({ layers, tokenMap, tileConfig, tileConfigReady, showBasemapLabels, basemapConfig });
  syncInputsRef.current = { layers, tokenMap, tileConfig, tileConfigReady, showBasemapLabels, basemapConfig };

  const layersRef = useRef(layers);
  layersRef.current = layers;

  // Cached queryable layer IDs — updated when layers change, read by click/mousemove handlers
  const queryLayerIdsRef = useRef<string[]>([]);

  // Tracks whether measurement plugin is active — avoids re-registering map handlers on every toggle
  const measureActiveRef = useRef(false);

  useEffect(() => {
    measureActiveRef.current =
      usePluginStore.getState().activePlugins.has('measurement') &&
      isPluginIdAvailable('measurement', enabledPluginIds);
    return usePluginStore.subscribe((state) => {
      measureActiveRef.current =
        state.activePlugins.has('measurement') &&
        isPluginIdAvailable('measurement', enabledPluginIds);
    });
  }, [enabledPluginIds]);

  // A draw mode (the analysis clip mask) owns the pointer while it runs, so
  // feature clicks must not resolve underneath it. Same ref-and-subscribe shape
  // as measurement above: handlers read a ref so toggling does not re-register
  // them.
  const drawActiveRef = useRef(false);

  useEffect(() => {
    drawActiveRef.current = useMapDrawStore.getState().drawActive;
    return useMapDrawStore.subscribe((state) => {
      drawActiveRef.current = state.drawActive;
      // Drop a popup that is already open when drawing starts, or it stays
      // parked over the area being drawn for the rest of the session.
      if (state.drawActive) setPopupInfo(null);
    });
  }, []);

  const invalidateTileTokens = useInvalidateTileTokens();
  // Shared tile-auth recovery: a vector tile 401/403 that the cached-token
  // re-sign can't cure kicks one throttled token re-mint; the token-sync effect
  // re-signs sources when the fresh batch lands. Every mint the recovery path
  // actually kicks is reported (suppressed), so a tab-return recovery leaves a
  // trace.
  const recoverTileAuth = useTileAuthRecovery(invalidateTileTokens, (trigger) =>
    reportTileTokenRemint('builder', trigger),
  );
  // A tab backgrounded past the 900 s sig boundary comes back with stale
  // tokens, so MapLibre's resumed fetches 403 before the handler above can heal
  // them. Kick the same throttled re-mint on the visible edge.
  useVisibleTileTokenRefresh(() => syncInputsRef.current.tokenMap.values(), recoverTileAuth, () =>
    refreshRasterTileSources(mapRef.current),
  );

  const handleLoad = useCallback(
    (e: MapLibreEvent) => {
      const map = e.target;
      mapRef.current = map;
      // FIRST thing in the map-creation path, so this is the
      // earliest-registered `style.load` listener and the basemap paint cache
      // is invalidated before any appearance pass runs against a newly loaded
      // style. Registering it lazily from the appearance helper would put it
      // behind the persistent handler below.
      registerBasemapStyleGeneration(map);
      // Keep the state mirror in sync with the ref so consumers (e.g.
      // MapCoordReadout) re-render when the map binds.
      setMapInstance(map);
      setMapReady(true);

      // `idle` fires when no tiles are loading, no transitions are in progress
      // and no animations are running. Flip the container's data-tiles-loaded
      // attribute to true on idle so the showcase-smoke spec has a
      // deterministic signal. Re-arm on every camera move rather than firing
      // once, so it can tell 'settled' from 'tiles loading after a pan/zoom'
      // (ViewerMap mirrors this).
      tilesIdleMovestartHandlerRef.current = () => setTilesIdle(false);
      tilesIdleIdleHandlerRef.current = () => setTilesIdle(true);
      map.on('movestart', tilesIdleMovestartHandlerRef.current);
      map.on('idle', tilesIdleIdleHandlerRef.current);

      // Tile loading indicator. Keep references so the unmount cleanup can
      // detach them symmetrically.
      dataLoadingHandlerRef.current = () => {
        setTilesLoading(true);
        sawTileErrorSinceLoadingRef.current = false;
      };
      idleHandlerRef.current = () => {
        setTilesLoading(false);
        // A load cycle finished without a hard tile error: the 'tiles' notice's
        // condition has passed, so clear it (the 'style' notice has its own
        // clearing path in the style-fetch effect). During an ongoing outage
        // the errors that precede idle re-arm the flag, so the banner does not
        // flap.
        if (!sawTileErrorSinceLoadingRef.current) {
          setBasemapNotice((notice) => (notice === 'tiles' ? null : notice));
        }
      };
      map.on('dataloading', dataLoadingHandlerRef.current);
      map.on('idle', idleHandlerRef.current);

      // Absolutify URLs and attach the auth header for raster tile requests.
      // Shared builder: react-maplibre v8 ignores the transformRequest PROP
      // after mount, so each map wires it here in onLoad.
      map.setTransformRequest(buildTileTransformRequest({
        getTileConfig: () => syncInputsRef.current.tileConfig,
      }));

      // Filter expected tile errors (no-data tiles outside extent) and surface
      // anything else as a deduped toast so the editor knows a real error
      // occurred.
      errorHandlerRef.current = (e: { error: { message?: string; status?: number; url?: string }; sourceId?: string }) => {
        const status = e.error?.status;
        // A raster/DEM 401/403 is not cured by anything the recovery path
        // produces: raster auth rides the Authorization header
        // (setTransformRequest), so neither the re-sign nor a fresh sig reaches
        // it. Reporting it 'handled' (a suppressed warning) while
        // logUnhandledMapError still console.errors the same failure would
        // double-log it. `isHandledTileAuthError` already excludes these, so
        // report the unsuppressed error and let the toast and single console
        // row own it.
        const rasterAuthError = isRasterTileAuthError(e);
        // Capture EVERY map error into the problem-reporter buffer before the
        // suppression/early-return logic below: suppressed errors (expected
        // no-data tiles, terrain/DEM mismatches) are frequently the actual bug
        // an engineer needs, so flag rather than drop them.
        //
        // An unsuppressed row here pairs with the `console` row
        // initReportCapture derives from logUnhandledMapError's console.error,
        // so an unrecovered failure yields two rows. That is the buffer's shape
        // for every error no surface recovers (any tile 5xx does the same;
        // BuilderMap.raster-tile-auth.test.tsx pins the parity). Dropping
        // either half for raster would cost the sourceId this row carries, or
        // the devtools log the surfaces without a row of their own rely on.
        //
        // A raster auth failure while a session renewal is running is the
        // visibility race, not a dead session: the post-rotation reload is
        // about to cure it, so it reports like any other transient. Only a 401,
        // though; a raster 403 is an upstream denial a fresh JWT cannot cure,
        // so it must still surface.
        const rasterAuthDuringRenewal =
          isRefreshableRasterAuthError(e) && isSessionRenewalPending();
        const isClientError = Boolean(status && status >= 400 && status < 500);
        const suppressedClientError = isClientError && (!rasterAuthError || rasterAuthDuringRenewal);
        pushReportEntry({
          severity: suppressedClientError ? 'warning' : 'error',
          source: 'maplibre',
          message: e.error?.message || (status ? `Map error (HTTP ${status})` : 'Map error'),
          detail: e.sourceId ? `source: ${e.sourceId}` : undefined,
          suppressed: suppressedClientError || shouldSuppressBuilderMapError(e.error),
        });
        // Suppress expected no-data tiles (404) and other client errors
        if (status && status >= 400 && status < 500) {
          if (status === 401 || status === 403) {
            // A vector `.pbf` fetched before its signed token attaches yields a
            // transient 401/403 (a token-sync race, not a real auth failure).
            // Re-sign the failing vector source using the token in tokenMap for
            // its own dataset so MapLibre retries with a fresh sig, and
            // suppress the toast for that recoverable case. Raster sources and
            // no-token cases return false and fall through to the toast below.
            const map = mapRef.current;
            const failingSourceId = e.sourceId;
            if (map && failingSourceId) {
              const { layers: l, tokenMap: tm, tileConfig: tc } = syncInputsRef.current;
              // Nothing here re-signs a raster/DEM source (its auth
              // rides the Authorization header), so don't pretend to.
              const resigned = rasterAuthError
                ? false
                : resignVectorSourceForRetry(map, failingSourceId, l, tm, tc);
              // The cached-token re-sign only cures the attach race; when the
              // sig itself has expired (stranded session) it re-signs with the
              // same stale sig forever. Also kick one throttled token re-mint:
              // the token-sync effect re-signs with the fresh batch, and a
              // conclusively dead session surfaces through the global
              // signed-out handling via the mint request itself.
              //
              // The re-mint runs for raster too: the mint request goes through
              // apiFetch, whose proactive refresh renews an expiring JWT, and
              // that Bearer is the ONLY thing that fixes a raster 401. It must
              // not count as recovery, though: a fresh sig cannot help a raster
              // tile, so a raster failure falls through to the toast below and
              // is reported unsuppressed rather than reading as handled next to
              // logUnhandledMapError's console row.
              const reminted = recoverTileAuth();
              if (!rasterAuthError && (resigned || reminted)) {
                pushReportEntry({
                  severity: 'warning',
                  source: 'maplibre',
                  message: `Vector tile ${resigned ? 're-signed' : 're-mint requested'} after HTTP ${status} (BLDR-TILE-RACE)`,
                  detail: `source: ${failingSourceId}`,
                  suppressed: true,
                });
                return;
              }
            }
            // Don't tell the user to reload for a raster 401 that a renewal
            // already in flight is seconds from healing.
            if (rasterAuthDuringRenewal) return;
            // Once the session is conclusively dead the global signed-out
            // dialog owns the UX and the stale reload toast is noise on top of
            // it; keep it only while a session exists. Keyed on the ACCESS
            // token: the refresh token is an httpOnly cookie, so it reads as
            // null for every cookie-mode user and this predicate would suppress
            // the toast permanently.
            if (useAuthStore.getState().token) {
              toast.error(t('builderMap.authError', { defaultValue: 'Session expired — reload the page to restore tile access.' }), {
                id: 'builder-map-auth-error',
              });
            }
          }
          return;
        }
        if (shouldSuppressBuilderMapError(e.error)) return;
        // Surface server errors (5xx) and unknown errors
        if (import.meta.env.DEV) console.warn('[BuilderMap] Map error:', e.error);
        if (!status || status >= 500) {
          // Suppress the transient connection-issue toast that fires for a few
          // hundred ms right after a successful basemap load (MapLibre raises a
          // stale tile error while transitioning between styles). Narrowed to a
          // bounded window after the latch was armed so ongoing tile-server
          // outages still surface a toast and banner. 3000 ms covers the
          // worst-case post-load transient window observed in smoke without
          // masking ongoing outages.
          const loadedAt = basemapLoadedAtRef.current;
          if (loadedAt !== null && Date.now() - loadedAt < 3000) return;
          // Name the failing layer when the error carries a sourceId. MapLibre
          // attaches it to tile/source errors; style/glyph errors have none and
          // fall back to the generic message. Matched against the current
          // layers ref using the same getSourceIdForLayer contract as the map
          // sync.
          const failingSourceId = e.sourceId;
          const failingLayer = failingSourceId
            ? layersRef.current.find((l) => getSourceIdForLayer(l) === failingSourceId)
            : undefined;
          // Only the basemap style's own sources, or a request error with no
          // source (style, sprite, glyphs; status 0 when unreachable), are a
          // basemap outage. Data layers, terrain and a rejected expression are not.
          const basemapFailed = failingSourceId
            ? basemapSourceIdsRef.current?.has(failingSourceId)
              ?? (!failingLayer && failingSourceId !== TERRAIN_SOURCE_ID)
            : typeof status === 'number';
          if (basemapFailed) {
            sawTileErrorSinceLoadingRef.current = true;
            setBasemapNotice('tiles');
          }
          const failingName = failingLayer?.display_name || failingLayer?.dataset_name;
          toast.error(
            failingName
              ? t('builderMap.mapErrorNamed', {
                  name: failingName,
                  defaultValue: 'Failed to load {{name}} — the layer may not render correctly.',
                })
              : t('builderMap.mapError', { defaultValue: 'Map tile error — some layers may not render correctly.' }),
            {
              id: 'builder-map-error',
            },
          );
        }
      };
      map.on('error', errorHandlerRef.current);

      // Shared resolver; knownImagesOnly keeps the builder's
      // editor-facing missing-image warnings for unknown ids.
      styleImageMissingHandlerRef.current = makeStyleImageMissingResolver(map, { knownImagesOnly: true });
      map.setMissingStyleImageResolver(styleImageMissingHandlerRef.current);

      onMapRef?.(map);
    },
    [onMapRef, t, recoverTileAuth],
  );

  // Refresh the cached list of queryable layer IDs after every sync so the
  // click/hover handlers see the layers that actually exist on the map. Reads
  // `layersRef.current` so the callback identity stays stable.
  const refreshQueryLayerIds = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    queryLayerIdsRef.current = layersRef.current
      .filter((l) => l.visible && l.layer_type !== 'raster_geolens')
      .flatMap((l) => {
        const layerId = getLayerId(l.id);
        // Mixed-geometry layers spread hits across per-family sublayers;
        // include them so point/line features stay clickable (the getLayer
        // filter below drops any that don't exist).
        if (isClusterRenderMode(l)) return clusterInteractiveLayerIds(layerId);
        if (isGenericGeometryType(l.dataset_geometry_type)) return mixedInteractiveLayerIds(layerId);
        return [layerId];
      })
      .filter((id) => map.getLayer(id));
  }, []);

  /**
   * The SINGLE syncMapComposition invocation shared by the style.load handler
   * and the main sync effect's `runSync`. Both read inputs from
   * `syncInputsRef.current` (immune to closure-stale inputs) and wire identical
   * syncOptions / basemapConfig / reorderDataLayerIds; the ONLY difference is
   * whether terrain is applied immediately or deferred to the next `idle`
   * (post-basemap-swap). The token gate stays at each call site.
   */
  const composeSync = useCallback((map: MaplibreMap, { immediateTerrain }: { immediateTerrain: boolean }) => {
    const {
      layers: ls,
      tokenMap: tm,
      tileConfig: tc,
      tileConfigReady: tcReady,
      showBasemapLabels: sbl,
      basemapConfig: bc,
    } = syncInputsRef.current;
    if (!tcReady) return;
    const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tc?.cdn_base_url || undefined;
    const syncInputs = ls.map(toSyncInput);
    syncMapComposition({
      map,
      layers: syncInputs,
      tokenMap: tm,
      tileBaseUrl,
      managedSourcesRef,
      orderKeyRef: lastOrderKeyRef,
      geojsonDataMap: clusterGeoJsonDataRef.current,
      syncOptions: {
        showBasemapLabels: sbl,
        basemapPosition: bc?.basemap_position ?? undefined,
        mvtSourceLayerPrefix: tc?.mvt_source_layer_prefix,
      },
      basemapConfig: bc,
      showBasemapLabels: sbl,
      reorderDataLayerIds: syncInputs,
      afterSync: () => {
        if (immediateTerrain) applyTerrainConfig();
        else map.once('idle', applyTerrainConfig);
        refreshQueryLayerIds();
      },
    });
  }, [applyTerrainConfig, refreshQueryLayerIds]);

  // Re-add data layers after basemap switch (persistent listener). Unlike a
  // per-URL map.once(), this listener survives any number of rapid style swaps;
  // a cleanup that removed it before style.load fired would drop the sync.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!tileConfigReady) return;

    const onStyleLoad = () => {
      const { layers: l, tokenMap: t, showBasemapLabels: sbl, basemapConfig: bc } = syncInputsRef.current;
      managedSourcesRef.current = new Set();
      lastOrderKeyRef.current = '';
      // Gate on tokenMap presence so a later token arrival is picked up by the
      // main sync effect's tokenMap dep — no separate retry needed.
      if (l.some((layer) => layer.dataset_id && !t.has(layer.dataset_id))) {
        // The swap reset the style's projection and basemap appearance; restore
        // them even while the token gate defers layer sync, so token
        // availability never controls projection.
        applyMapBasemapAppearance({ map, basemapConfig: bc, showBasemapLabels: sbl });
        return;
      }
      // Post-basemap-swap: defer terrain to the next idle (immediateTerrain=false).
      composeSync(map, { immediateTerrain: false });
    };

    map.on('style.load', onStyleLoad);
    return () => {
      map.off('style.load', onStyleLoad);
    };
  }, [mapReady, tileConfigReady, composeSync]);

  /**
   * Run a full layer sync against the map, mirroring ViewerMap's `runSync`. The
   * style is already loaded on this path, so terrain is applied immediately.
   */
  const runSync = useCallback((map: MaplibreMap) => {
    composeSync(map, { immediateTerrain: true });
  }, [composeSync]);

  // O(1) lookup map: feature.layer.id (with `layer-` prefix) → layer/source metadata.
  // Rebuilt only when the layers ref content changes; kept in a ref so the
  // effect below doesn't re-register on every layers change.
  const layerByMapIdRef = useRef<Map<string, { layer: MapLayerResponse; sourceId: string }>>(new Map());
  useEffect(() => {
    const byMapId = new Map<string, { layer: MapLayerResponse; sourceId: string }>();
    for (const l of layers) {
      const layerId = getLayerId(l.id);
      // Route through getSourceIdForLayer so the sourceId stored with each
      // layer's MapLibre layer id reflects the dedupe contract. Cluster layers
      // stay per-layer (the helper keeps `source-${id}` for them), so
      // `activateClusterFeature(map, feature, hit.sourceId)` receives the
      // cluster's per-layer source id.
      const sourceId = getSourceIdForLayer(l);
      const ids = isClusterRenderMode(l)
        ? clusterInteractiveLayerIds(layerId)
        : isGenericGeometryType(l.dataset_geometry_type)
          ? mixedInteractiveLayerIds(layerId)
          : [layerId];
      for (const id of ids) byMapId.set(id, { layer: l, sourceId });
    }
    layerByMapIdRef.current = byMapId;
  }, [layers]);

  // Resolve a queryRenderedFeatures hit to its layer config, or null when
  // the layer is unknown or popups are explicitly disabled. Verifies the
  // `layer-` prefix matched before slicing — guards against any non-managed
  // layer that slipped past the queryLayerIds filter.
  const lookupHitLayer = useCallback((featureLayerId: string, includePopupDisabled = false) => {
    const hit = layerByMapIdRef.current.get(featureLayerId);
    if (!hit) return null;
    if (!includePopupDisabled && hit.layer.popup_config?.enabled === false) return null;
    return hit;
  }, []);

  // Click + mousemove handlers: popup and pointer cursor
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const fallbackName = t('common:viewer.featureFallback');
    const buildClusterPopup = (feature: Parameters<typeof isClusterFeature>[0], hit: { layer: MapLayerResponse; sourceId: string }) => (
      clusterAggregateFeatureInfo(feature, {
        layerName: hit.layer.display_name || hit.layer.dataset_name || fallbackName,
        sourceKind: getClusterSourceStrategy(hit.layer).kind,
        locale: i18n.language,
      })
    );

    const handleClusterHit = (
      feature: Parameters<typeof isClusterFeature>[0],
      hit: { layer: MapLayerResponse; sourceId: string },
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
        onFeatureSelect?.(info);
      } else {
        setPopupInfo(null);
        onFeatureSelect?.(null);
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

    // Shared by mouse click and the keyboard handler below so keyboard users
    // get the same non-cluster feature popups as mouse users.
    const mapFeatureHits = (hits: ReturnType<MaplibreMap['queryRenderedFeatures']>): FeatureInfo[] => {
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
          columnInfo: layer.dataset_column_info ?? null,
          datasetId: layer.dataset_id,
          title: cfg?.expression ? substitutePopupTemplate(cfg.expression, props) : null,
          visibleFields: cfg?.visible_fields ?? null,
          zoomAtClick: map.getZoom(),
        });
      }
      return mapped;
    };

    const handleClick = (e: MapMouseEvent) => {
      if (!map.isStyleLoaded()) return;
      if (measureActiveRef.current || drawActiveRef.current) return;
      const queryLayers = queryLayerIdsRef.current;

      if (queryLayers.length === 0) {
        setPopupInfo(null);
        return;
      }

      const hits = map.queryRenderedFeatures(e.point, { layers: queryLayers });
      const clusterHit = findClusterHit(hits);
      if (clusterHit) {
        handleClusterHit(clusterHit.feature, clusterHit.hit, e.lngLat);
        return;
      }

      const mapped = mapFeatureHits(hits);

      if (mapped.length > 0) {
        setPopupInfo({
          longitude: e.lngLat.lng,
          latitude: e.lngLat.lat,
          features: mapped,
        });
        onFeatureSelect?.(mapped[0]);
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
        if (measureActiveRef.current || drawActiveRef.current) return;
        const queryLayers = queryLayerIdsRef.current;

        let canvas;
        try {
          canvas = map.getCanvas();
        } catch {
          return;
        }
        if (!canvas) return;

        if (queryLayers.length === 0) {
          canvas.style.cursor = '';
          return;
        }

        const features = map.queryRenderedFeatures(e.point, { layers: queryLayers });
        // Mirror handleClick's per-feature filter so the cursor only signals
        // interactivity when at least one hit is a cluster or on a popup-enabled layer.
        const interactive = features.some((f) => {
          const hit = lookupHitLayer(f.layer.id, true);
          if (!hit) return false;
          return isClusterFeature(f) || hit.layer.popup_config?.enabled !== false;
        });
        canvas.style.cursor = interactive ? 'pointer' : '';
      });
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      if (measureActiveRef.current || drawActiveRef.current) return;
      const queryLayers = queryLayerIdsRef.current;
      if (queryLayers.length === 0) return;
      let canvas: HTMLCanvasElement | null = null;
      try {
        canvas = map.getCanvas();
      } catch {
        return;
      }
      if (!canvas) return;
      const point: [number, number] = [
        (canvas.clientWidth || canvas.width) / 2,
        (canvas.clientHeight || canvas.height) / 2,
      ];
      const hits = map.queryRenderedFeatures(point, { layers: queryLayers });
      const clusterHit = findClusterHit(hits);
      if (clusterHit) {
        event.preventDefault();
        handleClusterHit(clusterHit.feature, clusterHit.hit, null);
        return;
      }
      // Mirror handleClick's mapping so keyboard users can open the same
      // feature popup as mouse users; the early return above would otherwise
      // make Enter/Space a no-op unless the centre-of-canvas hit is a cluster.
      const mapped = mapFeatureHits(hits);
      if (mapped.length === 0) return;
      event.preventDefault();
      const lngLat = map.unproject(point);
      setPopupInfo({
        longitude: lngLat.lng,
        latitude: lngLat.lat,
        features: mapped,
      });
      onFeatureSelect?.(mapped[0]);
    };

    map.on('click', handleClick);
    map.on('mousemove', handleMouseMove);
    let canvasForKeyboard: HTMLCanvasElement | null = null;
    try {
      canvasForKeyboard = map.getCanvas();
      canvasForKeyboard?.addEventListener?.('keydown', handleKeyDown);
    } catch {
      canvasForKeyboard = null;
    }
    return () => {
      map.off('click', handleClick);
      cancelAnimationFrame(rafId);
      map.off('mousemove', handleMouseMove);
      canvasForKeyboard?.removeEventListener?.('keydown', handleKeyDown);
      try {
        const canvas = map.getCanvas();
        if (canvas) canvas.style.cursor = '';
      } catch {
        // Map already torn down — nothing to reset.
      }
    };
  }, [mapReady, t, lookupHitLayer, onFeatureSelect]);

  // Popup invalidation key: changes whenever any structural property of the
  // layers list shifts (add/remove/reorder/visibility toggle, dataset rename,
  // render-mode-specific style fields). The popup must be cleared on any of
  // these because the feature it references may no longer exist, may be hidden,
  // or may be re-keyed against a different source.
  //
  // Includes dataset_table_name (mid-session rename safety) and the active
  // render mode's primary style_config.builder field (heatmapRamp,
  // heightColumn) so non-cluster modes invalidate when their structural style
  // shifts. The auto-fit effect does not read this key: it gates on
  // `layerCountChanged`, which depends only on `layers.length`.
  const popupInvalidationKey = useMemo(
    () => layers.map((l) => {
      const builder = l.style_config?.builder;
      const renderMode = l.style_config?.render_mode;
      const extras = renderMode === 'cluster'
        ? `:cl:${builder?.clusterRadius ?? ''}:${builder?.clusterMaxZoom ?? ''}`
        : renderMode === 'heatmap'
          ? `:hm:${builder?.heatmapRamp ?? ''}`
          : builder?.heightColumn
            ? `:hc:${builder.heightColumn}`
            : '';
      return `${l.id}:${l.visible}:${l.dataset_id}:${l.dataset_table_name ?? ''}${extras}`;
    }).join(','),
    [layers],
  );

  // Clear the popup when the invalidation key changes.
  useEffect(() => {
    setPopupInfo(null);
  }, [popupInvalidationKey]);

  // Sync layers to map: runs on structural changes (add/remove/visibility) and
  // token refresh. Paint/filter/opacity edits are handled imperatively by
  // use-layer-map-sync.ts. Inputs are read fresh from `syncInputsRef.current`
  // at call time (ViewerMap's `runSync(map)` pattern), which avoids a
  // closure-stale-input race on the first 'Add to map' against an empty
  // builder.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!tileConfigReady) return;
    // Token gate (ViewerMap-style): wait for tokens before any sync.
    if (layers.length > 0 && tokenMap.size === 0) return;
    // Defense in depth: also wait if any specific layer is still missing its
    // token (e.g. a partial batch — one dataset cached, one still in flight).
    if (layers.some((l) => l.dataset_id && !tokenMap.has(l.dataset_id))) return;

    // Style gate. If the basemap style is transitioning, nothing in the dep
    // array would change later and the once-fired `style.load` listener already
    // ran with the pre-add state, so an early return would be a permanent miss.
    // Attach a one-shot `idle` listener to retry as soon as the map settles
    // (after style.load, tile loading and transitions).
    if (!map.isStyleLoaded()) {
      const retry = () => runSync(map);
      map.once('idle', retry);
      return () => { map.off('idle', retry); };
    }
    runSync(map);
    // Include basemap_position so dragging the basemap top/bottom re-runs the
    // sync's reorder pipeline (the orderKey check inside syncLayersToMap
    // includes it too, to avoid the no-change skip).
  }, [layers, mapReady, tileConfigReady, tileConfig?.cdn_base_url, tileConfig?.mvt_source_layer_prefix, tokenMap, showBasemapLabels, basemapConfig?.basemap_position, clusterGeoJsonVersion, runSync]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!map.isStyleLoaded()) {
      const retry = () => applyTerrainConfig();
      map.once('idle', retry);
      return () => { map.off('idle', retry); };
    }
    applyTerrainConfig();
  }, [
    applyTerrainConfig,
    mapReady,
    terrainConfig?.enabled,
    terrainConfig?.source_dataset_id,
    terrainConfig?.exaggeration,
    terrainLayerKey,
    tokenSig,
  ]);

  // Reorder and restyle basemap labels/details when appearance controls change.
  // Data labels must be re-stacked above basemap labels after toggling.
  //
  // If basemap_position='top', run the reorderBasemapAboveData pass LAST so
  // basemap fill/raster layers end up ABOVE data geometry; the standard
  // pipeline above assumes basemap-below-data.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applyMapBasemapAppearance({
      map,
      basemapConfig,
      showBasemapLabels,
      reorderDataLayerIds: layersRef.current.map((l) => ({ id: l.id })),
    });
  }, [basemapConfig, showBasemapLabels, mapReady]);

  // Re-sign vector sources in place when tokens refresh. refreshVectorSourceTiles
  // re-tiles only when the signed URL changed, so an edit that keeps it does not refetch.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !tileConfigReady) return;
    const sources = describeBuilderSources(layers, tokenMap, tileConfig, clusterGeoJsonDataRef.current);

    for (const layer of layers) {
      const token = tokenMap.get(layer.dataset_id) ?? null;
      // Raster tile URLs use nginx auth-check subrequest — nothing to refresh.
      if (!token || token.kind === 'raster') continue;
      const sourceId = getSourceIdForLayer(layer);
      const spec = sources.get(sourceId);
      if (spec?.type === 'vector' && spec.tiles?.[0]) refreshVectorSourceTiles(map, sourceId, spec.tiles[0]);
    }
  }, [tokenMap, layers, mapReady, tileConfigReady, tileConfig]);

  // Track whether we've restored a saved view (skip auto-fit on initial load)
  const hasSavedView = !!(initialViewState?.center_lng != null && initialViewState?.center_lat != null);
  const initialFitDoneRef = useRef(false);
  const prevLayerCountRef = useRef(layers.length);
  // Lazy-seed: a useRef initializer ARGUMENT evaluates on every render, which
  // would walk the full bounds each time.
  const prevVisibleBoundsKeyRef = useRef<string | undefined>(undefined);
  if (prevVisibleBoundsKeyRef.current === undefined) {
    prevVisibleBoundsKeyRef.current = visibleLayerBoundsKey(getVisibleLayerBounds(layers));
  }
  // Id of the live "return to previous view" toast, so a second
  // auto-fit replaces the offer instead of stacking a stale one.
  const returnToViewToastRef = useRef<string | number | undefined>(undefined);

  // Auto-fit to visible layers (skip on initial load if saved view exists)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const layerCountChanged = layers.length !== prevLayerCountRef.current;
    prevLayerCountRef.current = layers.length;
    const visibleBounds = getVisibleLayerBounds(layers);
    const visibleBoundsKey = visibleLayerBoundsKey(visibleBounds);
    const visibleBoundsChanged = visibleBoundsKey !== prevVisibleBoundsKeyRef.current;
    prevVisibleBoundsKeyRef.current = visibleBoundsKey;

    // First auto-fit trigger: skip if we have a saved view to restore
    const isFirstFit = !initialFitDoneRef.current;
    if (isFirstFit) {
      initialFitDoneRef.current = true;
      if (hasSavedView) return; // MapGL already positioned via initialViewState
    } else if (!layerCountChanged || !visibleBoundsChanged) {
      // Only fit when the visible extent genuinely changed. Duplicate renderings
      // add a layer row but keep the same dataset bounds, so they must not move
      // the user's current map view.
      return;
    }
    if (!visibleBounds) return;

    // Capture the camera first and offer a one-shot return, so the fit has a
    // way back. Not on the very first fit: there is no user-chosen view yet, so
    // the offer would be page-load noise.
    const previousCamera = isFirstFit ? null : {
      center: map.getCenter(),
      zoom: map.getZoom(),
      bearing: map.getBearing(),
      pitch: map.getPitch(),
    };

    map.fitBounds(
      visibleBounds,
      { padding: 40, maxZoom: 18, duration: 0 },
    );

    clampMinZoomAfterFit(map);

    if (previousCamera) {
      // Replace rather than stack: a second auto-fit makes the older offer stale,
      // and its camera is no longer the one the user was looking at.
      if (returnToViewToastRef.current !== undefined) toast.dismiss(returnToViewToastRef.current);
      returnToViewToastRef.current = toast(t('map.autoFitMoved'), {
        // Longer than the default: an auto-fit usually rides along with another
        // toast ("Layer removed"), and sonner collapses the stack, so a 4s offer
        // can expire while it is still hidden behind the one in front.
        duration: 10_000,
        action: {
          label: t('map.returnToPreviousView'),
          onClick: () => {
            mapRef.current?.easeTo({ ...previousCamera, duration: 400 });
            if (returnToViewToastRef.current !== undefined) {
              toast.dismiss(returnToViewToastRef.current);
              returnToViewToastRef.current = undefined;
            }
          },
        },
      });
    }
  // Reads `layers.length` rather than popupInvalidationKey: the effect
  // short-circuits on unchanged layer count and visible bounds, so the full key
  // would only add misleading extra runs on heatmap-ramp / height-column edits.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- hasSavedView/layers read from refs, not reactive deps
  }, [layers.length, mapReady]);

  // Cleanup on unmount
  const onMapRefLatest = useRef(onMapRef);
  onMapRefLatest.current = onMapRef;
  useEffect(() => {
    return () => {
      // The Toaster outlives the route change, so a live
      // "return to previous view" offer would follow the user to an unrelated page
      // and ease a torn-down map on click.
      if (returnToViewToastRef.current !== undefined) {
        toast.dismiss(returnToViewToastRef.current);
        returnToViewToastRef.current = undefined;
      }
      if (mapRef.current && errorHandlerRef.current) {
        mapRef.current.off('error', errorHandlerRef.current);
      }
      // v6's resolver is a setter, not an emitter — clear it by
      // passing null. Map.remove() never touches the field, so this only
      // matters for the repo's symmetric-detach convention, not for a leak.
      if (mapRef.current && styleImageMissingHandlerRef.current) {
        mapRef.current.setMissingStyleImageResolver(null);
      }
      if (mapRef.current && dataLoadingHandlerRef.current) {
        mapRef.current.off('dataloading', dataLoadingHandlerRef.current);
      }
      if (mapRef.current && idleHandlerRef.current) {
        mapRef.current.off('idle', idleHandlerRef.current);
      }
      if (mapRef.current && tilesIdleMovestartHandlerRef.current) {
        mapRef.current.off('movestart', tilesIdleMovestartHandlerRef.current);
      }
      if (mapRef.current && tilesIdleIdleHandlerRef.current) {
        mapRef.current.off('idle', tilesIdleIdleHandlerRef.current);
      }
      setMapInstance(null);
      onMapRefLatest.current?.(null);
    };
    // Unmount-only on purpose: depending on `onMapRef` would run this cleanup
    // on every identity change of the parent callback, nulling the parent's map
    // ref mid-session (breaking ephemeral overlays and analysis draw) and
    // detaching the error/styleimagemissing/dataloading/idle handlers with no
    // re-attach path. The latest callback is read through a ref.
  }, []);

  const defaultView = useMemo(() => ({
    longitude: initialViewState?.center_lng ?? mapDefaults?.center_lng ?? 0,
    latitude: initialViewState?.center_lat ?? mapDefaults?.center_lat ?? 20,
    zoom: Math.max(initialViewState?.zoom ?? mapDefaults?.zoom ?? 2, 2),
    bearing: initialViewState?.bearing ?? 0,
    pitch: initialViewState?.pitch ?? 0,
  }), [initialViewState?.center_lng, initialViewState?.center_lat, initialViewState?.zoom, initialViewState?.bearing, initialViewState?.pitch, mapDefaults?.center_lng, mapDefaults?.center_lat, mapDefaults?.zoom]);

  const { contextLost, reload } = useWebGLRecovery(mapRef, mapReady, invalidateTileTokens);

  return (
    <div
      className="relative h-full w-full"
      // aria-label on <MapGL> is silently dropped (@vis.gl/react-maplibre v8
      // forwards only id/ref/style, and MapLibre labels its canvas "Map"), so
      // label the wrapper region instead, as DatasetMap's shell does.
      role="region"
      aria-label={t('map.ariaLabel', { defaultValue: 'Map builder' })}
      data-tiles-loaded={tilesIdle ? 'true' : 'false'}
      // Marker consumed by the `[data-builder-canvas="true"]
      // .maplibregl-ctrl-top-left` rule in `index.css`. Pushes the top-left
      // NavigationControl below the MapCoordReadout pill at the 800px boundary,
      // where the map column compresses to ~316px and the pill's ~237px width
      // can stretch into the zoom-control zone. Scoped via data-attribute so
      // ViewerMap (NavigationControl `top-right`) is unaffected.
      data-builder-canvas="true"
    >
      {tilesLoading && (
        <div className="absolute inset-x-0 top-0 z-10 h-0.5 bg-primary/60 animate-pulse" />
      )}
      {basemapNotice && (
        <div
          role="status"
          aria-live="polite"
          className="absolute end-3 top-3 z-20 max-w-sm rounded-md border bg-background/95 p-3 text-sm shadow-md backdrop-blur"
        >
          <p className="font-medium text-foreground">
            {t('builderMap.basemapIssueTitle', { defaultValue: 'Basemap connection issue' })}
          </p>
          <p className="mt-1 text-muted-foreground">
            {t('builderMap.basemapIssueDescription', {
              defaultValue: 'Your data layers are still editable. Check the basemap service or choose another basemap if the background stays blank.',
            })}
          </p>
        </div>
      )}
      <MapGL
        initialViewState={defaultView}
        mapStyle={mapStyle}
        styleDiffing={false}
        // Cold-mount projection, see ViewerMap's MapGL for rationale.
        locale={mapLocale}
        projection={initialProjection}
        // Captures use map.triggerRepaint() + synchronous toDataURL() in
        // use-builder-save.ts (doCapture / handleExportPNG), so
        // preserveDrawingBuffer stays off and the WebGL canvas keeps its
        // default no-buffer-retention memory profile.
        style={{ width: '100%', height: '100%' }}
        minZoom={1}
        onLoad={handleLoad}
        // Claim the wrapper's `error` fallback so a handled tile-auth 401/403
        // (re-sign or re-mint in handleLoad's error handler) doesn't double-log
        // a red AJAXError console row.
        onError={logUnhandledMapError}
      >
        {/* NavigationControl anchored top-left so it does not collide with the
            right-side BuilderRail (Notes/History/Ask AI buttons) at narrow
            viewports (≤1024px rail mode). ScaleControl stays bottom-left. */}
        <NavigationControl position="top-left" />
        <ScaleControl position="bottom-left" maxWidth={100} unit="metric" />
        {popupInfo && (
          <FeaturePopup
            longitude={popupInfo.longitude}
            latitude={popupInfo.latitude}
            features={popupInfo.features}
            onClose={() => setPopupInfo(null)}
          />
        )}
      </MapGL>
      <MapCoordReadout map={mapInstance} showScale />
      {!mapReady && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/50">
          <div className="text-sm text-muted-foreground animate-pulse">{t('builderMap.loading', { defaultValue: 'Loading map…' })}</div>
        </div>
      )}
      {contextLost && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80">
          <div className="text-center space-y-2">
            <p className="text-sm text-muted-foreground">{t('errors.mapMessage')}</p>
            <button type="button" onClick={reload} className="cursor-pointer text-sm underline text-primary hover:text-primary/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring rounded-sm px-1">{t('common.reload')}</button>
          </div>
        </div>
      )}
    </div>
  );
});
