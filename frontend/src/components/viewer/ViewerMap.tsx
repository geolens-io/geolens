import { useEffect, useRef, useCallback, useState, useMemo, memo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Map as MapGL, NavigationControl, ScaleControl, FullscreenControl, AttributionControl, TerrainControl } from '@vis.gl/react-maplibre';
import { useBasemaps, useBranding, useTileConfig } from '@/hooks/use-settings';
import { useEdition } from '@/hooks/use-edition';
import { useMapLocale } from '@/hooks/use-map-locale';
import {
  findBasemapById,
  makeStyleImageMissingResolver,
  toMaplibreStyle,
  resolveBasemapId,
  BLANK_BASEMAP_ID,
  FALLBACK_BASEMAP_STYLE_URL,
} from '@/lib/basemap-utils';
import { buildTileTransformRequest, isMvtSourceLayerConfigReady, isThirdPartyTileUrl, refreshRasterTileSources, resolveTileBaseUrl } from '@/lib/tile-utils';
import { useRemoteBasemapStyle } from '@/components/map/hooks/use-remote-basemap-style';
import { isRasterTileAuthError, isRefreshableRasterAuthError, logUnhandledMapError } from '@/lib/map-error-log';
import { reportTileTokenRemint } from '@/lib/report';
import { useWebGLRecovery } from '@/hooks/use-webgl-recovery';
import { useInvalidateTileTokens } from '@/hooks/use-tile-token';
import { isSessionRenewalPending, useTileAuthRecovery, useVisibleTileTokenRefresh } from '@/hooks/use-tile-auth-recovery';
import { useViewerTokens } from '@/components/viewer/hooks/use-viewer-tokens';
import { isViewerTerrainExpected, useViewerTerrain } from '@/components/viewer/hooks/use-viewer-terrain';
import { FeaturePopup, type FeatureInfo } from '@/components/map/FeaturePopup';
import {
  activateClusterFeature,
  clusterAggregateFeatureInfo,
  clusterFeatureCoordinates,
  isClusterFeature,
} from '@/components/map/cluster-interactions';
import { MapCoordReadout } from '@/components/map/MapCoordReadout';
import type { DrawnLayer } from '@/components/map/legend-facts';
import { substitutePopupTemplate } from '@/lib/popup-template';
import i18n from '@/i18n/i18n';
import { GEOLENS_SITE_URL } from '@/lib/external-links';
import type { MapLibreEvent, MapMouseEvent } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapBasemapConfig, MapTerrainConfig, SharedLayerResponse } from '@/types/api';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import { clampMinZoomAfterFit } from '@/components/builder/builder-bounds';
import { adapterInputFor, describeLayers } from '@/components/builder/layer-description';
import { prefixed, isDemTerrainVisualSuppressed, registerBasemapStyleGeneration, syncRenderContext } from '@/components/builder/map-sync';
import { applyMapBasemapAppearance, syncMapComposition } from '@/components/builder/map-composition-sync';
import type { SyncLayerInput } from '@/components/builder/map-sync';
import { asFeatureCollection, fetchBoundedGeoJson } from '@/api/geojson-z';
import {
  attributionControlKey,
  collectLayerAttributions,
  createViewerLayerEntries,
  isTerrainBackingLiveVisible,
} from '@/components/viewer/layer-identity';
import { getClusterSourceEligibility, getClusterSourceStrategy, shouldFetchClusterGeoJson } from '@/components/builder/cluster-source';
import { AccessibleMapDataPanel } from '@/components/viewer/AccessibleMapDataPanel';
import {
  toAccessibleMapFeatures,
  type AccessibleMapFeatureResult,
} from '@/components/viewer/accessible-map-data';
import {
  VIEWER_PREFIX,
  viewerManagedLayerIds,
  viewerQueryLayerIds,
} from '@/components/viewer/viewer-query-layer-ids';
import 'maplibre-gl/dist/maplibre-gl.css';
// Wires maplibre v6's worker URL. Side-effect import, kept out of
// main.tsx so map-vendor stays out of the eager entry graph.
import '@/lib/maplibre-worker';

/**
 * Public map viewer canvas, used by the standalone viewer page and the
 * embeddable iframe plugin.
 *
 * Renders a publicly visible map composition with read-only navigation,
 * popups on click and a basemap matching the parent theme. Layers render
 * through the `layer-adapters` registry shared with the builder, so both
 * produce identical visuals. Embed viewers pass `embedToken`, which the
 * tile-token and GeoJSON requests forward in place of a session.
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
    /** Fit these bounds instead of the center and zoom. Read once, at mount. */
    bounds?: [[number, number], [number, number]] | null;
  };
  visibleLayers: Set<string>;
  onMapReady?: (map: MaplibreMap) => void;
  embedToken?: string;
  basemapConfig?: MapBasemapConfig | null;
  showBasemapLabels?: boolean;
  terrainConfig?: MapTerrainConfig | null;
  /** Receives what the map draws each layer as, by layer key, once any bounded cluster GeoJSON has settled. */
  onDrawnChange?: (drawn: ReadonlyMap<string, DrawnLayer>) => void;
  /** True when every layer's dataset is public; lets the data panel link to dataset pages. */
  datasetLinksAllowed?: boolean;
}

/** Convert a SharedLayerResponse to the normalized SyncLayerInput.
 *  Exported for unit testing. */
export function toViewerSyncInput(
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
    // Carry popup_config so the initial source build requests popup
    // visible_fields / title-template cols=; without it a viewer opened at z<10
    // strips those fields until a token refresh rebuilds the URL.
    popup_config: layer.popup_config,
    is_dem: layer.is_dem,
    dataset_id: layer.dataset_id,
    is_3d: layer.is_3d,
    feature_count: layer.feature_count,
    dataset_column_info: layer.column_info,
    layer_type: layer.layer_type,
    dataset_record_type: layer.dataset_record_type,
    tile_url: layer.tile_url,
    // Thread the dataset content version through so tile URLs carry the same
    // `_v=` cache-buster as the builder.
    tile_version: layer.tile_version,
    bounds: layer.dataset_extent_bbox ?? null,
  };
}

export const ViewerMap = memo(function ViewerMap({
  layers,
  basemapStyle,
  initialViewState,
  visibleLayers,
  onMapReady,
  embedToken,
  basemapConfig = null,
  showBasemapLabels = true,
  terrainConfig = null,
  onDrawnChange,
  datasetLinksAllowed = false,
}: ViewerMapProps) {
  const { t } = useTranslation('common');
  const mapLocale = useMapLocale();
  const { isEnterprise, isResolved } = useEdition();
  const { data: branding } = useBranding();
  // isEnterprise defaults to false until the edition resolves, and only Enterprise
  // can opt out, so Enterprise also waits for branding to avoid flashing the credit.
  const showBranding = isResolved && (!isEnterprise || (branding !== undefined && branding.show_badge !== false));
  const mapRef = useRef<MaplibreMap | null>(null);
  const managedSourcesRef = useRef<Set<string>>(new Set());
  const prevOrderKeyRef = useRef('');
  const [mapReady, setMapReady] = useState(false);
  // Mount-time projection for the MapGL prop; see the comment at
  // the <MapGL projection> site for why it must never change after mount.
  const [initialProjection] = useState(() => basemapConfig?.projection ?? 'mercator');
  const [initialBounds] = useState(() => initialViewState.bounds ?? null);
  const layerEntries = useMemo(() => createViewerLayerEntries(layers), [layers]);
  // The visible layers' required credit lines for the attribution control below.
  const layerAttributions = useMemo(
    () => collectLayerAttributions(layers, visibleLayers),
    [layers, visibleLayers],
  );
  const attributionCredits = useMemo(
    () => showBranding
      ? [
          ...layerAttributions,
          `<a href="${GEOLENS_SITE_URL}" target="_blank" rel="noopener noreferrer">GeoLens</a>`,
        ]
      : layerAttributions,
    [layerAttributions, showBranding],
  );

  // Tile token management (fetch, auto-refresh, error toast)
  const { tokenMap, refreshTokens } = useViewerTokens({ layers, embedToken });
  // Shared tile-auth recovery: a vector tile 401/403 kicks one throttled token
  // re-mint, and the sync pass re-signs the sources once the new token lands.
  // Suppressed mints are reported so a tab-return recovery still leaves a trace.
  const recoverTileAuth = useTileAuthRecovery(refreshTokens, (trigger) =>
    reportTileTokenRemint('viewer', trigger),
  );
  // A tab backgrounded past the 900 s sig boundary returns with stale tokens,
  // so resumed fetches 403 before the error handler can heal them; kick the
  // same throttled re-mint on the visible edge.
  useVisibleTileTokenRefresh(() => tokenMap.values(), recoverTileAuth, () =>
    refreshRasterTileSources(mapRef.current),
  );

  // The bound DEM's LIVE visibility (legend eye toggle). Saved visibility is
  // handled inside the hook; this covers the client-side override so hiding the
  // DEM flattens the mesh too. Shared with LayerLegend's synthetic-entry gate
  // so legend and mesh cannot split.
  const demLayerLiveVisible = useMemo(
    () => isTerrainBackingLiveVisible(layers, terrainConfig, visibleLayers),
    [layers, terrainConfig, visibleLayers],
  );

  // Persisted terrain source and exaggeration
  const { terrainReady, reseedTerrainOnStyleLoad } = useViewerTerrain({
    layers,
    mapRef,
    mapReady,
    terrainConfig,
    tokenMap,
    demLayerLiveVisible,
  });

  // Opening a terrain map showed the wide flat DEM slab for several seconds
  // before terrain activation re-anchored the camera to the saved 3D view (the
  // jump is `setTerrain` recomputing the camera once the DEM source is ready).
  // Treat that pre-terrain frame as loading: hold a veil over the map until
  // terrain has applied (terrainReady) for terrain maps, or until the map is
  // ready for non-terrain maps, then latch "revealed" for the session. This is
  // a one-time entry gate, not a re-arming signal like `tilesIdle`.
  // Terrain is applied only when the bound DEM resolves AND is visible
  // (useViewerTerrain gates on the same). A terrain map whose DEM is saved
  // hidden never sets terrainReady, so compute the same effective expectation
  // as the hook to reveal it immediately instead of waiting for the 4s timer.
  const terrainExpected = useMemo(
    () => isViewerTerrainExpected(layers, terrainConfig) && demLayerLiveVisible,
    [layers, terrainConfig, demLayerLiveVisible],
  );
  const [revealed, setRevealed] = useState(false);
  useEffect(() => {
    if (revealed || !mapReady) return;
    if (!terrainExpected || terrainReady) setRevealed(true);
  }, [revealed, mapReady, terrainReady, terrainExpected]);
  // Safety net: never veil the map forever if terrain activation stalls (e.g. a
  // DEM tile source that never resolves); reveal after a short grace period.
  useEffect(() => {
    if (revealed) return;
    const timer = setTimeout(() => setRevealed(true), 4000);
    return () => clearTimeout(timer);
  }, [revealed]);

  // Bounded GeoJSON for cluster layers small enough to cluster in the browser.
  const geojsonDataRef = useRef<Map<string, GeoJSON.FeatureCollection>>(new Map());
  const boundedGeoJsonLayers = useMemo(
    () => layerEntries.filter(({ layer }) => shouldFetchClusterGeoJson(layer)),
    [layerEntries],
  );
  const boundedGeoJsonRequest = useMemo(() => ({
    layers: boundedGeoJsonLayers,
    embedToken,
  }), [boundedGeoJsonLayers, embedToken]);
  const completedBoundedGeoJsonRequestRef = useRef<object | null>(null);
  const [geojsonVersion, setGeojsonVersion] = useState(0);

  // MapLibre activity feeds the composite readiness attributes on the outer
  // container. A raw idle alone is insufficient because viewer-owned sources
  // can arrive later with async config, tokens, or bounded GeoJSON.
  const [tilesIdle, setTilesIdle] = useState(false);
  const tilesLoadingHandlerRef = useRef<(() => void) | null>(null);
  const tilesIdleHandlerRef = useRef<(() => void) | null>(null);
  // A MapLibre `idle` can precede async token/config/GeoJSON work. Track which
  // exact composition request was applied and then observed at a later idle so
  // an already-idle basemap cannot certify a newly arrived data overlay.
  const appliedCompositionRef = useRef<object | null>(null);
  const settledCompositionRef = useRef<object | null>(null);
  const [popupInfo, setPopupInfo] = useState<{
    longitude: number;
    latitude: number;
    features: FeatureInfo[];
  } | null>(null);
  const [dataPanelOpen, setDataPanelOpen] = useState(false);
  const [accessibleFeatures, setAccessibleFeatures] = useState<AccessibleMapFeatureResult>({
    features: [],
    total: 0,
    truncated: false,
  });

  const { data: basemaps } = useBasemaps();
  const { data: tileConfig } = useTileConfig();
  // `source-layer` is immutable in MapLibre. Do not compose vector layers
  // until the settings response supplies the tenant-aware MVT prefix.
  const tileConfigReady = isMvtSourceLayerConfigReady(tileConfig);
  // Ref so the `map.on('error', ...)` handler registered once in handleLoad
  // always reads the current tile config.
  const tileConfigRef = useRef(tileConfig);
  tileConfigRef.current = tileConfig;
  const resolvedId = resolveBasemapId(basemapStyle);
  const isBlank = resolvedId === BLANK_BASEMAP_ID;
  const effectiveBasemap = isBlank
    ? undefined
    : findBasemapById(basemaps ?? [], basemapStyle);
  // Falls back to OpenFreeMap like every other map surface.
  const fallbackUrl = FALLBACK_BASEMAP_STYLE_URL;
  const styleValue = useMemo(
    // Pass the basemap's configured attribution through, as BuilderMap and
    // DatasetMap do; it matters most on this public surface, including for
    // raster XYZ basemaps.
    () => (isBlank
      ? toMaplibreStyle(BLANK_BASEMAP_ID)
      : toMaplibreStyle(effectiveBasemap?.url ?? fallbackUrl, effectiveBasemap?.attribution)),
    [effectiveBasemap?.url, effectiveBasemap?.attribution, fallbackUrl, isBlank],
  );
  // Shared fetch-and-sanitize path (see use-remote-basemap-style). On fetch
  // failure, fall back to handing MapLibre the raw style URL so the map still
  // gets a basemap.
  const mapStyle = useRemoteBasemapStyle({
    styleValue,
    mapRef,
    logLabel: 'ViewerMap',
    fallbackToRawUrlOnError: true,
  });

  const boundedGeoJsonReady = boundedGeoJsonLayers.length === 0
    || completedBoundedGeoJsonRequestRef.current === boundedGeoJsonRequest;
  const layerTokensReady = layers.length === 0 || Boolean(embedToken) || layers.every(
    (layer) => tokenMap.has(layer.dataset_id),
  );
  // Identity is deliberate: every dependency that can alter sources/layers
  // creates a new request. Until that request is applied and reaches idle, the
  // previous request's readiness cannot leak into the DOM contract.
  const compositionRequest = useMemo(() => ({
    layers,
    tokenMap,
    tileConfigReady,
    cdnBaseUrl: tileConfig?.cdn_base_url,
    sourceLayerPrefix: tileConfig?.mvt_source_layer_prefix,
    showBasemapLabels,
    embedToken: embedToken ?? null,
    geojsonVersion,
    mapStyle,
  }), [
    layers,
    tokenMap,
    tileConfigReady,
    tileConfig?.cdn_base_url,
    tileConfig?.mvt_source_layer_prefix,
    showBasemapLabels,
    embedToken,
    geojsonVersion,
    mapStyle,
  ]);
  const compositionRequestRef = useRef(compositionRequest);
  compositionRequestRef.current = compositionRequest;

  const markMapLoading = useCallback(() => {
    settledCompositionRef.current = null;
    setTilesIdle(false);
  }, []);

  // Fetch is independent of map readiness — data lands in a ref, repaint is separate.
  useEffect(() => {
    if (boundedGeoJsonLayers.length === 0) {
      if (geojsonDataRef.current.size > 0) {
        geojsonDataRef.current = new Map();
        setGeojsonVersion((v) => v + 1);
      }
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    async function fetchAll() {
      const newMap = new Map<string, GeoJSON.FeatureCollection>();
      await Promise.all(
        boundedGeoJsonLayers.map(async ({ layer, key }) => {
          try {
            const data = await fetchBoundedGeoJson(layer.dataset_id, { embedToken, signal: controller.signal });
            if (!cancelled && !data.truncated && data.total_count <= getClusterSourceEligibility(layer).limit) {
              newMap.set(key, asFeatureCollection(data));
            }
          } catch (e) {
            if (controller.signal.aborted) return;
            if (import.meta.env.DEV) console.warn(`[ViewerMap] Bounded GeoJSON fetch failed for ${layer.dataset_id}:`, e);
            toast.error(t('viewer.geoJsonLoadError', { defaultValue: 'Failed to load layer data' }), { id: `geojson-z-error-${layer.dataset_id}` });
          }
        }),
      );
      if (!cancelled) {
        geojsonDataRef.current = newMap;
        completedBoundedGeoJsonRequestRef.current = boundedGeoJsonRequest;
        setGeojsonVersion((v) => v + 1);
      }
    }
    fetchAll().catch(() => {
      // Individual layer errors are already toasted above; this only fires on unexpected scaffolding failure
    });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [boundedGeoJsonLayers, boundedGeoJsonRequest, embedToken, t]);

  useEffect(() => {
    if (geojsonVersion === 0) return;
    const map = mapRef.current;
    if (map && mapReady) map.triggerRepaint();
  }, [geojsonVersion, mapReady]);

  // A cluster draws single points while its GeoJSON loads, so reporting waits
  // for the fetch to settle and reports a fallback only when it stays.
  const onDrawnChangeRef = useRef(onDrawnChange);
  onDrawnChangeRef.current = onDrawnChange;
  const hasReportedRef = useRef(false);
  useEffect(() => {
    if (!tileConfigReady || !boundedGeoJsonReady) {
      // The last report describes the last request, so withdraw it while this one loads.
      if (hasReportedRef.current) onDrawnChangeRef.current?.(new Map());
      hasReportedRef.current = false;
      return;
    }
    const context = syncRenderContext(new Map(), undefined, geojsonDataRef.current, {
      idPrefix: VIEWER_PREFIX,
      mvtSourceLayerPrefix: tileConfig?.mvt_source_layer_prefix,
    });
    const drawn = new Map<string, DrawnLayer>();
    for (const { layer, key } of layerEntries) {
      const [described] = describeLayers([toViewerSyncInput(layer, key, visibleLayers)], context).layers;
      if (described) drawn.set(key, { drawsAs: described.drawsAs });
    }
    onDrawnChangeRef.current?.(drawn);
    hasReportedRef.current = drawn.size > 0;
  }, [layerEntries, visibleLayers, geojsonVersion, tileConfigReady, boundedGeoJsonReady, tileConfig?.mvt_source_layer_prefix]);

  const handleLoad = useCallback(
    (e: MapLibreEvent) => {
      const map = e.target;
      mapRef.current = map;
      // FIRST in the map-creation path, so it is the earliest-registered
      // `style.load` listener and the basemap paint cache is invalidated before
      // any appearance pass runs against a newly loaded style. Registering it
      // lazily from the appearance helper would put it behind the persistent
      // handler below.
      registerBasemapStyleGeneration(map);

      // First-party vs third-party request classification (shared
      // `isThirdPartyTileUrl` in lib/tile-utils). Gates both the credential
      // headers below and the embed-auth error toast in the error handler.
      const isThirdPartyUrl = (url?: string): boolean =>
        isThirdPartyTileUrl(url, tileConfigRef.current);

      // Absolutify URLs and attach the embed token / raster Bearer header.
      // react-maplibre v8 ignores the transformRequest PROP after mount, so each
      // map wires it here in onLoad.
      map.setTransformRequest(buildTileTransformRequest({
        embedToken,
        getTileConfig: () => tileConfigRef.current,
      }));

      // Filter expected tile errors (no-data tiles outside extent) and surface
      // anything else as a deduped toast so users know the map has a real
      // problem.
      map.on('error', (e: { error: { message?: string; status?: number; url?: string } }) => {
        const status = e.error?.status;
        // A 401/403 from a third-party CDN is not an embed-token problem (see
        // isThirdPartyUrl above). Embed-token auth failures (expired/invalid
        // X-Embed-Token) get their own deduped "access expired" toast instead of
        // the generic 4xx suppression below. The copy is generic: it must never
        // echo the token, dataset id, or raw error detail.
        if (embedToken && (status === 401 || status === 403) && !isThirdPartyUrl(e.error?.url)) {
          toast.error(t('viewer.embedAuthError', { defaultValue: 'This embedded map\'s access has expired or is no longer valid.' }), {
            id: 'viewer-embed-auth-error',
          });
          return;
        }
        // A first-party tile 401/403 means the signed tile URL has gone stale
        // (expired signature or stranded session). Kick one throttled token
        // re-mint: the sync pass re-signs the sources when it lands, and a dead
        // session surfaces through the global signed-out handling via the mint.
        if ((status === 401 || status === 403) && !isThirdPartyUrl(e.error?.url)) {
          // recoverTileAuth() returning false means a recent re-mint didn't cure
          // the error (revoked grant, expired signature); fall through to the
          // deduped tile-error toast rather than leave the surface silent.
          // The re-mint still runs for a raster/DEM failure: it goes through
          // apiFetch, whose proactive refresh renews an expiring JWT, the ONLY
          // thing that fixes a raster 401. But a fresh sig can't help a raster
          // tile, so its `true` must not silence the surface as it does for a
          // vector tile: toast regardless, matching `isHandledTileAuthError`.
          const recovering = recoverTileAuth();
          // Unless a session renewal is in flight, which does fix a raster 401
          // and whose post-rotation reload is about to retry these tiles.
          const rasterUnrecoverable =
            isRasterTileAuthError(e) &&
            !(isRefreshableRasterAuthError(e) && isSessionRenewalPending());
          if (rasterUnrecoverable || (!isRasterTileAuthError(e) && !recovering)) {
            toast.error(t('viewer.mapError', { defaultValue: 'Map tile error — some layers may not display correctly.' }), {
              id: 'viewer-map-error',
            });
          }
          return;
        }
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

      // Shared resolver; the read-only viewer stubs every missing image
      // (knownImagesOnly: false) to keep the public console clean.
      map.setMissingStyleImageResolver(makeStyleImageMissingResolver(map, { knownImagesOnly: false }));

      // `dataloading` covers app-driven source/style work that doesn't move the
      // camera (async token arrival, terrain seeding, GeoJSON replacement, style
      // swaps), which a movestart-only re-arm would miss while the initial
      // basemap idle stayed true.
      tilesLoadingHandlerRef.current = markMapLoading;
      tilesIdleHandlerRef.current = () => {
        const styleReady = map.isStyleLoaded() === true;
        settledCompositionRef.current = styleReady
          ? appliedCompositionRef.current
          : null;
        setTilesIdle(styleReady);
      };
      map.on('movestart', tilesLoadingHandlerRef.current);
      map.on('dataloading', tilesLoadingHandlerRef.current);
      map.on('idle', tilesIdleHandlerRef.current);

      if (initialBounds) clampMinZoomAfterFit(map);
      setMapReady(true);
      onMapReady?.(map);
    },
    [onMapReady, embedToken, t, recoverTileAuth, markMapLoading, initialBounds],
  );

  // Stable list of interactive (non-heatmap, visible) layer IDs for query operations
  const interactiveLayers = useMemo(
    () => viewerQueryLayerIds(layerEntries, visibleLayers, { includeHeatmaps: false }),
    [layerEntries, visibleLayers],
  );
  // The data alternative is broader than pointer interaction: heatmaps do not
  // produce useful click popups, but their underlying rendered points are
  // still queryable and must remain available to keyboard/screen-reader users.
  const accessibleLayerIds = useMemo(
    () => viewerQueryLayerIds(layerEntries, visibleLayers, { includeHeatmaps: true }),
    [layerEntries, visibleLayers],
  );
  // Ref so event handlers always see current value without re-registration
  const interactiveLayersRef = useRef(interactiveLayers);
  interactiveLayersRef.current = interactiveLayers;
  const accessibleLayerIdsRef = useRef(accessibleLayerIds);
  accessibleLayerIdsRef.current = accessibleLayerIds;
  const layersRef = useRef(layers);
  layersRef.current = layers;

  // Shared by click + mousemove handlers: queryRenderedFeatures over the ref'd
  // interactive layer IDs that are currently attached to the map. Returns null
  // when there are none, so callers can clear their UI state.
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
      const sourceId = prefixed('source', key, VIEWER_PREFIX);
      const ids = viewerManagedLayerIds(layer, key);
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

  // Keyboard and screen-reader equivalent for the visual map: expose the
  // GeoLens features rendered in the current viewport as structured layer,
  // geometry/extent, and attribute data. Basemap features are excluded by the
  // managed GeoLens-layer allowlist, and the result is bounded before it
  // reaches the DOM.
  const refreshAccessibleFeatures = useCallback(() => {
    const map = mapRef.current;
    if (!map) {
      setAccessibleFeatures({ features: [], total: 0, truncated: false });
      return;
    }

    const queryIds = accessibleLayerIdsRef.current.filter((id) => map.getLayer(id));
    if (queryIds.length === 0) {
      setAccessibleFeatures({ features: [], total: 0, truncated: false });
      return;
    }

    try {
      const rendered = map.queryRenderedFeatures({ layers: queryIds });
      setAccessibleFeatures(toAccessibleMapFeatures(
        rendered,
        (mapLayerId) => lookupHitLayer(mapLayerId, true)?.layer ?? null,
      ));
    } catch {
      // Style transitions can briefly invalidate a layer between getLayer()
      // and queryRenderedFeatures(). The next idle event refreshes safely.
      setAccessibleFeatures({ features: [], total: 0, truncated: false });
    }
  }, [lookupHitLayer]);

  useEffect(() => {
    if (!dataPanelOpen) return;
    const map = mapRef.current;
    if (!map) return;

    refreshAccessibleFeatures();
    map.on('idle', refreshAccessibleFeatures);
    return () => {
      map.off('idle', refreshAccessibleFeatures);
    };
  }, [dataPanelOpen, mapReady, visibleLayers, refreshAccessibleFeatures]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

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
          columnInfo: layer.column_info ?? null,
          datasetId: layer.dataset_id,
          title: cfg?.expression ? substitutePopupTemplate(cfg.expression, props) : null,
          visibleFields: cfg?.visible_fields ?? null,
          zoomAtClick: map.getZoom(),
        });
      }
      return mapped;
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

      const mapped = mapFeatureHits(hits);

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
      if (clusterHit) {
        event.preventDefault();
        handleClusterHit(clusterHit.feature, clusterHit.hit, null);
        return;
      }
      // Keyboard parity with BuilderMap: Enter/Space opens the same feature
      // popup as a click. Mirror handleClick's mapping.
      const mapped = mapFeatureHits(hits);
      if (mapped.length === 0) return;
      event.preventDefault();
      const lngLat = map.unproject(point);
      setPopupInfo({
        longitude: lngLat.lng,
        latitude: lngLat.lat,
        features: mapped,
      });
    };

    let canvasForKeyboard: HTMLCanvasElement | null = null;
    const attach = () => {
      map.on('click', handleClick);
      try {
        canvasForKeyboard = map.getCanvas();
        canvasForKeyboard?.addEventListener?.('keydown', handleKeyDown);
      } catch {
        canvasForKeyboard = null;
      }
    };
    // Idle retry (mirrors the layer-sync/visibility effects): on a cold hard
    // load, as a share link opens, the style is still transitioning when this
    // effect runs, and a plain early return would never re-attach the click
    // listener, leaving popups inert on the shared-viewer surface.
    if (!map.isStyleLoaded()) {
      map.once('idle', attach);
    } else {
      attach();
    }
    return () => {
      map.off('idle', attach);
      map.off('click', handleClick);
      canvasForKeyboard?.removeEventListener?.('keydown', handleKeyDown);
    };
  }, [mapReady, t, queryInteractiveFeatures, lookupHitLayer]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

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

    // Same cold-load idle retry as the click effect above.
    const attach = () => map.on('mousemove', handleMouseMove);
    if (!map.isStyleLoaded()) {
      map.once('idle', attach);
    } else {
      attach();
    }
    return () => {
      map.off('idle', attach);
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

  useEffect(() => {
    setPopupInfo(null);
  }, [visibleLayers]);

  // Ref to hold current sync inputs so the style.load callback can access them
  const syncInputsRef = useRef({ layers, visibleLayers, tokenMap, tileConfig, tileConfigReady, showBasemapLabels, basemapConfig });
  syncInputsRef.current = { layers, visibleLayers, tokenMap, tileConfig, tileConfigReady, showBasemapLabels, basemapConfig };

  const applyViewerBasemapConfig = useCallback((map: MaplibreMap) => {
    applyMapBasemapAppearance({
      map,
      basemapConfig,
      showBasemapLabels,
      idPrefix: VIEWER_PREFIX,
    });
  }, [basemapConfig, showBasemapLabels]);

  /** Wrapper: convert viewer state to normalized inputs and run shared composition sync. */
  const runSync = useCallback((map: MaplibreMap) => {
    const {
      layers: ls,
      visibleLayers: vl,
      tokenMap: tm,
      tileConfig: tc,
      tileConfigReady: tcReady,
      showBasemapLabels: sbl,
      basemapConfig: bc,
    } = syncInputsRef.current;
    if (!tcReady) return;
    markMapLoading();
    const tileBaseUrl = resolveTileBaseUrl(tc);
    const syncInputs: SyncLayerInput[] = createViewerLayerEntries(ls).map(({ layer, key }) => (
      toViewerSyncInput(layer, key, vl)
    ));
    syncMapComposition({
      map,
      layers: syncInputs,
      tokenMap: tm,
      tileBaseUrl,
      managedSourcesRef,
      orderKeyRef: prevOrderKeyRef,
      geojsonDataMap: geojsonDataRef.current,
      syncOptions: {
        idPrefix: VIEWER_PREFIX,
        showBasemapLabels: sbl,
        basemapPosition: bc?.basemap_position ?? undefined,
        mvtSourceLayerPrefix: tc?.mvt_source_layer_prefix,
      },
      basemapConfig: bc,
      showBasemapLabels: sbl,
      reorderDataLayerIds: syncInputs,
    });
    const renderableEntries = createViewerLayerEntries(ls).filter(({ layer }) => (
      !isDemTerrainVisualSuppressed(layer)
    ));
    const hasViewerSources = managedSourcesRef.current.size > 0
      && [...managedSourcesRef.current].every((sourceId) => Boolean(map.getSource(sourceId)));
    const hasViewerLayers = renderableEntries.length > 0
      && renderableEntries.every(({ layer, key }) => (
        viewerManagedLayerIds(layer, key).every((layerId) => Boolean(map.getLayer(layerId)))
      ));
    // A terrain-render-mode DEM deliberately has no ordinary style layer or
    // managed composition source; useViewerTerrain owns its terrain-dem source.
    const hasOnlySuppressedTerrain = ls.length > 0 && renderableEntries.length === 0;
    appliedCompositionRef.current = hasOnlySuppressedTerrain || (hasViewerSources && hasViewerLayers)
      ? compositionRequestRef.current
      : null;
  }, [markMapLoading]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!tileConfigReady) return;
    // Gate the first sync on tile tokens arriving: syncLayersToMap picks the
    // raster adapter vs the vector path from `token?.kind === 'raster'`. Synced
    // earlier, every layer (rasters too) becomes a vector source with a `.pbf`
    // URL, which the server rejects for raster datasets and maplibre never
    // recovers from. The embed-token path has its own transformRequest flow and
    // doesn't depend on tokenMap, so it syncs immediately.
    if (!embedToken && layers.length > 0 && tokenMap.size === 0) return;
    // Idle retry (mirrors the visibility effect below): on a cold page load, as
    // a shared-link visitor arrives, the style can still be transitioning when
    // this effect first runs (terrain maps widen that window). A plain
    // `!isStyleLoaded()` early return would leave the data layers unsynced,
    // since nothing re-triggers this effect once the style settles (the
    // style.load listener can attach after the event already fired). Defer the
    // sync to the next idle so it always lands.
    if (!map.isStyleLoaded()) {
      const retrySync = () => runSync(map);
      map.once('idle', retrySync);
      return () => { map.off('idle', retrySync); };
    }
    runSync(map);
  // Note: visibleLayers intentionally excluded — the dedicated visibility effect below handles it
  }, [layers, mapReady, tileConfigReady, tileConfig?.cdn_base_url, tileConfig?.mvt_source_layer_prefix, tokenMap, showBasemapLabels, runSync, embedToken, geojsonVersion]);

  // Toggle visibility when visibleLayers set changes.
  // Note: runSync also calls syncVisibility via syncLayersToMap, but this
  // dedicated effect is needed for *visibility-only* changes where other
  // sync inputs (layers, tokenMap) haven't changed.
  const prevVisibleRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !tileConfigReady) return;

    const applyVisibilityDiff = () => {
      const prev = prevVisibleRef.current;
      // A toggle reads ids and adapters, never sources, so it needs no tokens.
      const context = syncRenderContext(new Map(), undefined, geojsonDataRef.current, {
        idPrefix: VIEWER_PREFIX,
        mvtSourceLayerPrefix: tileConfig?.mvt_source_layer_prefix,
      });
      for (const { layer, key } of layerEntries) {
        const wasVisible = prev.has(key);
        const isVisible = visibleLayers.has(key);
        if (wasVisible === isVisible) continue;

        const input = toViewerSyncInput(layer, key, visibleLayers);
        const [described] = describeLayers([input], context).layers;
        try {
          // Carries the label companion's visibility too, per its own spec.
          if (described) getAdapter(described.drawsAs).syncVisibility(map, adapterInputFor(input, described));
        } catch (e) {
          // An adapter can throw on a saved style it cannot read; the sync pass never drew that layer.
          if (import.meta.env.DEV) console.warn(`[viewer] setting the visibility of ${described?.id} failed:`, e);
        }
      }
      prevVisibleRef.current = new Set(visibleLayers);
    };

    // A plain early return on !isStyleLoaded() would drop the toggle for good:
    // prevVisibleRef isn't advanced and nothing in the deps changes when the
    // style settles, so the checkbox and map stay out of sync. Mirror the
    // BuilderMap idle retry: re-apply the diff once the map settles.
    if (!map.isStyleLoaded()) {
      map.once('idle', applyVisibilityDiff);
      return () => { map.off('idle', applyVisibilityDiff); };
    }
    applyVisibilityDiff();
  }, [visibleLayers, layerEntries, mapReady, tileConfigReady, tileConfig?.mvt_source_layer_prefix]);

  // Re-add data layers after any basemap/style change. <MapGL
  // styleDiffing={false}> calls map.setStyle() when mapStyle changes, which
  // wipes all custom sources/layers; clear tracked state and re-sync on
  // style.load (as BuilderMap).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const onStyleLoad = () => {
      markMapLoading();
      appliedCompositionRef.current = null;
      managedSourcesRef.current = new Set();
      prevOrderKeyRef.current = '';
      // Skip if layers haven't loaded; the sync effect runs when they arrive.
      // Also match the main sync effect's token gate so private vector sources
      // are never created with transient unsigned tile URLs.
      const hasLayers = syncInputsRef.current.layers.length > 0;
      const hasTokens = syncInputsRef.current.tokenMap.size > 0;
      if (!hasLayers || embedToken || hasTokens) {
        runSync(map);
      } else {
        applyViewerBasemapConfig(map);
      }
      // style.load wipes all custom sources; re-seed terrain source if a DEM is present.
      reseedTerrainOnStyleLoad();
    };

    map.on('style.load', onStyleLoad);
    return () => {
      map.off('style.load', onStyleLoad);
    };
  }, [mapReady, embedToken, runSync, reseedTerrainOnStyleLoad, applyViewerBasemapConfig, markMapLoading]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    applyViewerBasemapConfig(map);
  }, [basemapConfig, showBasemapLabels, mapReady, applyViewerBasemapConfig]);

  useEffect(() => {
    return () => {
      const map = mapRef.current;
      if (map && tilesLoadingHandlerRef.current) {
        map.off('movestart', tilesLoadingHandlerRef.current);
        map.off('dataloading', tilesLoadingHandlerRef.current);
      }
      if (map && tilesIdleHandlerRef.current) {
        map.off('idle', tilesIdleHandlerRef.current);
      }
      appliedCompositionRef.current = null;
      settledCompositionRef.current = null;
      mapRef.current = null;
    };
  }, []);

  const defaultView = useMemo(() => ({
    longitude: initialViewState.center_lng,
    latitude: initialViewState.center_lat,
    zoom: initialViewState.zoom,
    bearing: initialViewState.bearing,
    pitch: initialViewState.pitch,
    // MapLibre fits these at construction, overriding longitude, latitude and zoom.
    ...(initialBounds && { bounds: initialBounds, fitBoundsOptions: { padding: 40, maxZoom: 18 } }),
  }), [initialViewState.center_lng, initialViewState.center_lat, initialViewState.zoom, initialViewState.bearing, initialViewState.pitch, initialBounds]);

    const invalidateTileTokens = useInvalidateTileTokens();
  const { contextLost, reload } = useWebGLRecovery(mapRef, mapReady, invalidateTileTokens);

  const compositionPrerequisitesReady = layers.length === 0 || (
    tileConfigReady && layerTokensReady && boundedGeoJsonReady
  );
  const compositionSettled = layers.length === 0 || (
    appliedCompositionRef.current === compositionRequest
    && settledCompositionRef.current === compositionRequest
  );
  const viewerReady = mapReady
    && tilesIdle
    && compositionPrerequisitesReady
    && compositionSettled
    && (!terrainExpected || terrainReady);

  return (
    <div
      className={`relative h-full w-full [&_.maplibregl-ctrl-bottom-right]:max-w-[calc(50%-4.5rem)] max-[399px]:[&_.maplibregl-ctrl-bottom-right]:max-w-[calc(50%-1.75rem)] [&_.maplibregl-ctrl-attrib-inner]:[overflow-wrap:break-word] ${!mapReady ? 'bg-muted animate-pulse' : ''}`}
      // aria-label on <MapGL> is silently dropped (react-maplibre v8 forwards
      // only id/ref/style; MapLibre labels its canvas "Map"), so the wrapper
      // region is labelled instead, as in DatasetMap's shell.
      role="region"
      aria-label={t('viewer.map.ariaLabel', { defaultValue: 'Map viewer' })}
      data-tiles-loaded={viewerReady ? 'true' : 'false'}
      data-map-ready={viewerReady ? 'true' : 'false'}
      data-terrain-ready={terrainReady ? 'true' : 'false'}
    >
      <MapGL
        initialViewState={defaultView}
        mapStyle={mapStyle}
        styleDiffing={false}
        locale={mapLocale}
        // Covers the cold-mount window: react-maplibre applies it on the initial
        // style.load, before our onLoad-captured appearance sync can run. Frozen
        // at mount because a CHANGED projection prop goes through
        // react-maplibre's unguarded _updateSettings setter, which throws
        // mid style-swap. Runtime changes and basemap switches go through
        // applyMapBasemapAppearance instead.
        projection={initialProjection}
        style={{ width: '100%', height: '100%' }}
        attributionControl={false}
        minZoom={1}
        onLoad={handleLoad}
        // Claim the wrapper's `error` fallback so a handled tile-auth 401/403
        // (re-mint / embed-expired toast in handleLoad) doesn't double-log a
        // red AJAXError console row.
        onError={logUnhandledMapError}
      >
        <NavigationControl position="top-right" />
        <FullscreenControl position="top-right" />
        {terrainReady && (
          <TerrainControl source="terrain-dem" position="top-right" />
        )}
        <ScaleControl position="bottom-left" maxWidth={100} unit="metric" />
        {/* The `key` is load-bearing, not cosmetic. react-maplibre's
            useControl builds the control once with `useMemo(…, [])`, so a
            changed `customAttribution` prop never reaches MapLibre. Keying on
            the credit set remounts the control (removeControl + addControl)
            exactly when that set changes, and not on any other render.
            attributionControlKey owns the derivation so its injectivity can be
            tested directly — see the note there. */}
        <AttributionControl
          key={attributionControlKey(attributionCredits)}
          position="bottom-right"
          compact={true}
          customAttribution={
            attributionCredits.length > 0 ? attributionCredits : undefined
          }
        />
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
      <AccessibleMapDataPanel
        layers={layers}
        visibleLayers={visibleLayers}
        featureResult={accessibleFeatures}
        open={dataPanelOpen}
        onOpenChange={setDataPanelOpen}
        onRefresh={refreshAccessibleFeatures}
        disabled={!mapReady}
        datasetLinksAllowed={datasetLinksAllowed}
      />
      {/* Loading veil over the pre-terrain flat-DEM frame — fades
          out once the saved-camera 3D view is ready to show (or immediately
          for non-terrain maps). */}
      <div
        aria-hidden="true"
        data-testid="viewer-entry-veil"
        className={`pointer-events-none absolute inset-0 z-20 bg-muted transition-opacity duration-500 ${revealed ? 'opacity-0' : 'opacity-100'}`}
      />
      {contextLost && (
        <div role="alert" className="absolute inset-0 z-50 flex items-center justify-center bg-background/80">
          <div className="text-center space-y-2">
            <p className="text-sm text-muted-foreground">{t('errorBoundary.mapMessage')}</p>
            <button type="button" onClick={reload} className="text-sm underline text-primary hover:text-primary/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring rounded-sm px-1">{t('reload')}</button>
          </div>
        </div>
      )}
    </div>
  );
});
