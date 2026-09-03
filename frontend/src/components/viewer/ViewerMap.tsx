import { useEffect, useRef, useCallback, useState, useMemo, memo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Map as MapGL, NavigationControl, ScaleControl, FullscreenControl, AttributionControl, TerrainControl } from '@vis.gl/react-maplibre';
import { useBasemaps, useBranding, useTileConfig } from '@/hooks/use-settings';
import { useEdition } from '@/hooks/use-edition';
import {
  findBasemapById,
  makeStyleImageMissingResolver,
  toMaplibreStyle,
  resolveBasemapId,
  BLANK_BASEMAP_ID,
  FALLBACK_BASEMAP_STYLE_URL,
} from '@/lib/basemap-utils';
import { buildClusterTileUrl, buildSignedTileUrl, buildTileTransformRequest, getMvtSourceLayerName, isMvtSourceLayerConfigReady, isThirdPartyTileUrl, refreshRasterTileSources, resolveTileBaseUrl } from '@/lib/tile-utils';
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
import { substitutePopupTemplate } from '@/lib/popup-template';
import i18n from '@/i18n/i18n';
import type { MapLibreEvent, MapMouseEvent, VectorTileSource } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapBasemapConfig, MapTerrainConfig, SharedLayerResponse } from '@/types/api';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import { resolveAdapterType, prefixed, getDataDrivenColumnsForLayer, registerBasemapStyleGeneration } from '@/components/builder/map-sync';
import { applyMapBasemapAppearance, syncMapComposition } from '@/components/builder/map-composition-sync';
import type { SyncLayerInput } from '@/components/builder/map-sync';
import { asFeatureCollection, fetchBoundedGeoJson } from '@/api/geojson-z';
import {
  attributionControlKey,
  collectLayerAttributions,
  createViewerLayerEntries,
  isTerrainBackingLiveVisible,
} from '@/components/viewer/layer-identity';
import { getClusterSourceEligibility, getClusterSourceStrategy, isClusterRenderMode, shouldFetchClusterGeoJson } from '@/components/builder/cluster-source';
import { effectiveDemRenderMode } from '@/lib/dem-render-mode';
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
// feat(#846): wires maplibre v6's worker URL. Side-effect import, kept out of
// main.tsx so map-vendor stays out of the eager entry graph (fix(#1624)).
import '@/lib/maplibre-worker';

/**
 * Public map viewer canvas — used by the standalone viewer page and the
 * embeddable iframe plugin.
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
  /** When true and edition is community (or enterprise with show_badge !== false),
   *  renders an inline "Powered by GeoLens" overlay anchored to the map canvas.
   *  Defaults to false — non-embed callers stay clean.
   */
  showInlineBranding?: boolean;
}

/** Convert a SharedLayerResponse to the normalized SyncLayerInput.
 *  Exported for unit testing (popup_config preservation, #350). */
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
    // Carry popup_config so the INITIAL source build (syncMapComposition) requests
    // popup visible_fields / title-template cols=. Without this a viewer opened at
    // z<10 strips those fields until a later token-refresh rebuilds the URL (#350).
    popup_config: layer.popup_config,
    is_dem: layer.is_dem,
    dataset_id: layer.dataset_id,
    is_3d: layer.is_3d,
    feature_count: layer.feature_count,
    layer_type: layer.layer_type,
    dataset_record_type: layer.dataset_record_type,
    tile_url: layer.tile_url,
    // fix(#394) VT-02: thread the dataset content version through so the
    // viewer's tile URLs carry the same `_v=` cache-buster as the builder.
    tile_version: layer.tile_version,
  };
}

/** Build an AdapterLayerInput for viewer visibility syncing (no tile URL needed). */
function toAdapterInput(
  layer: SharedLayerResponse,
  layerKey: string,
  visibleLayers: Set<string>,
  mvtSourceLayerPrefix?: string | null,
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
    // fix(#394) VT-03: derive via the shared helper instead of a hand-rolled
    // template — the URL path and source-layer name must come from one place
    // or a drift is a silent empty layer (see tile-utils parity test, VT-04).
    sourceLayer: getMvtSourceLayerName(layer.table_name, mvtSourceLayerPrefix),
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
  showInlineBranding = false,
}: ViewerMapProps) {
  const { t } = useTranslation('common');
  const { isEnterprise } = useEdition();
  const { data: branding } = useBranding();
  // Gate on branding !== undefined so enterprise users with show_badge:false do
  // not see a flash of the badge while the branding query is still loading (IN-02).
  const showBranding = showInlineBranding && (
    branding !== undefined &&
    (!isEnterprise || branding?.show_badge !== false)
  );
  const mapRef = useRef<MaplibreMap | null>(null);
  const managedSourcesRef = useRef<Set<string>>(new Set());
  const prevOrderKeyRef = useRef('');
  const [mapReady, setMapReady] = useState(false);
  // feat(#845): mount-time projection for the MapGL prop; see the comment at
  // the <MapGL projection> site for why it must never change after mount.
  const [initialProjection] = useState(() => basemapConfig?.projection ?? 'mercator');
  const layerEntries = useMemo(() => createViewerLayerEntries(layers), [layers]);
  // feat(#1472): the visible layers' required credit lines, for the attribution
  // control below.
  const layerAttributions = useMemo(
    () => collectLayerAttributions(layers, visibleLayers),
    [layers, visibleLayers],
  );

  // Tile token management (fetch, auto-refresh, error toast)
  const { tokenMap, refreshTokens } = useViewerTokens({ layers, apiKey, embedToken });
  // fix(#621): shared tile-auth recovery — a vector tile 401/403 kicks one
  // throttled token re-mint; the token-refresh effect below re-signs sources.
  // fix(#890): report every mint the recovery path actually kicks (suppressed),
  // so a tab-return recovery still leaves a trace now that it no longer arrives
  // wrapped in a 403 burst.
  const recoverTileAuth = useTileAuthRecovery(refreshTokens, (trigger) =>
    reportTileTokenRemint('viewer', trigger),
  );
  // fix(#755): a tab backgrounded past the 900 s sig boundary comes back with
  // stale tokens, so MapLibre's resumed fetches 403 before the error handler
  // can heal them. Kick the same throttled re-mint on the visible edge.
  useVisibleTileTokenRefresh(() => tokenMap.values(), recoverTileAuth, () =>
    refreshRasterTileSources(mapRef.current),
  );

  // fix(#452): the bound DEM's LIVE visibility (legend eye toggle). Saved
  // visibility is handled inside the hook (HT-12); this covers the client-side
  // override so hiding the DEM in the viewer flattens the mesh too. Shared
  // with LayerLegend's synthetic-entry gate so legend and mesh cannot split.
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

  // fix(#430 V-05): opening a terrain map showed the wide flat DEM slab for
  // several seconds before terrain activation re-anchored the camera to the
  // saved 3D view (no entry animation exists — the jump is `setTerrain`
  // recomputing the camera once the DEM source is ready). Treat that
  // pre-terrain frame as loading state, not content: hold a veil over the map
  // until terrain has applied (terrainReady) for terrain maps, or until the
  // map is simply ready for non-terrain maps, then latch "revealed" true for
  // the rest of the session — this is a one-time entry gate, not a re-arming
  // signal like `tilesIdle`.
  // codex(#451): terrain is only actually applied when the bound DEM resolves
  // AND is visible (useViewerTerrain gates on the same). A map with terrain
  // enabled but the DEM saved hidden never sets terrainReady, so without this
  // gate it stayed under the veil until the 4s safety timer. Compute the same
  // effective expectation the hook uses so those maps reveal immediately.
  const terrainExpected = useMemo(
    () => isViewerTerrainExpected(layers, terrainConfig) && demLayerLiveVisible,
    [layers, terrainConfig, demLayerLiveVisible],
  );
  const [revealed, setRevealed] = useState(false);
  useEffect(() => {
    if (revealed || !mapReady) return;
    if (!terrainExpected || terrainReady) setRevealed(true);
  }, [revealed, mapReady, terrainReady, terrainExpected]);
  // Safety net: never veil the map forever if terrain activation stalls
  // (e.g. a DEM tile source that never resolves) — fall back to revealing
  // after a short grace period so the map is never permanently hidden.
  useEffect(() => {
    if (revealed) return;
    const timer = setTimeout(() => setRevealed(true), 4000);
    return () => clearTimeout(timer);
  }, [revealed]);

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
  // container. The Playwright showcase-smoke spec polls for this attribute to
  // avoid an arbitrary `waitForTimeout` delay after networkidle.
  const [tilesIdle, setTilesIdle] = useState(false);
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
  // (see below) always reads the current tile config without needing to
  // re-register the handler on every tileConfig change.
  const tileConfigRef = useRef(tileConfig);
  tileConfigRef.current = tileConfig;
  const resolvedId = resolveBasemapId(basemapStyle);
  const isBlank = resolvedId === BLANK_BASEMAP_ID;
  const effectiveBasemap = isBlank
    ? undefined
    : findBasemapById(basemaps ?? [], basemapStyle);
  // fix(#1778): was a lone CARTO fallback with no attribution string; every
  // other map surface falls back to OpenFreeMap.
  const fallbackUrl = FALLBACK_BASEMAP_STYLE_URL;
  const styleValue = useMemo(
    // chore(#835): pass the basemap's configured attribution through, matching
    // BuilderMap/DatasetMap — the viewer (the public surface where attribution
    // matters most) previously dropped it for raster XYZ basemaps.
    () => (isBlank
      ? toMaplibreStyle(BLANK_BASEMAP_ID)
      : toMaplibreStyle(effectiveBasemap?.url ?? fallbackUrl, effectiveBasemap?.attribution)),
    [effectiveBasemap?.url, effectiveBasemap?.attribution, fallbackUrl, isBlank],
  );
  // chore(#835): shared fetch-and-sanitize path (see use-remote-basemap-style).
  // Viewer-specific behavior: on fetch failure, fall back to handing MapLibre
  // the raw style URL so the map still gets a basemap.
  const mapStyle = useRemoteBasemapStyle({
    styleValue,
    mapRef,
    logLabel: 'ViewerMap',
    fallbackToRawUrlOnError: true,
  });

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
      // fix(#1778 codex round 5): FIRST thing in the map-creation path, so this
      // is the earliest-registered `style.load` listener and the basemap paint
      // cache is already invalidated by the time any appearance pass runs
      // against a newly loaded style. Registering it lazily from the appearance
      // helper would put it behind the persistent handler below.
      registerBasemapStyleGeneration(map);

      // First-party vs third-party request classification
      // (chore(#835): shared `isThirdPartyTileUrl` in lib/tile-utils). Used to
      // gate BOTH the credential headers below (fix(#394) SH-02/B-022,
      // fix(#819)) and the embed-auth error toast in the error handler.
      const isThirdPartyUrl = (url?: string): boolean =>
        isThirdPartyTileUrl(url, tileConfigRef.current);

      // Absolutify URLs and attach the embed token / raster Bearer header.
      // chore(#835): shared builder — react-maplibre v8 ignores the
      // transformRequest PROP after mount, so each map wires it here in onLoad.
      map.setTransformRequest(buildTileTransformRequest({
        embedToken,
        getTileConfig: () => tileConfigRef.current,
      }));

      // Filter expected tile errors (no-data tiles outside extent) and
      // surface anything else as a deduped toast so users know the map
      // has a real problem (RES-3). Previously suppressed entirely in prod.
      map.on('error', (e: { error: { message?: string; status?: number; url?: string } }) => {
        const status = e.error?.status;
        // A 401/403 from a third-party CDN is not an embed-token problem —
        // see isThirdPartyUrl above.
        // Embed-token auth failures (expired/invalid X-Embed-Token) get their own
        // deduped "access expired" toast instead of being swallowed by the generic
        // 4xx suppression below. Copy is intentionally generic — must never echo
        // the token, dataset id, or raw error detail.
        if (embedToken && (status === 401 || status === 403) && !isThirdPartyUrl(e.error?.url)) {
          toast.error(t('viewer.embedAuthError', { defaultValue: 'This embedded map\'s access has expired or is no longer valid.' }), {
            id: 'viewer-embed-auth-error',
          });
          return;
        }
        // fix(#621): a first-party tile 401/403 means the signed tile URL has
        // gone stale (expired sig / stranded session). Kick one throttled
        // token re-mint — the token-refresh effect re-signs the sources when
        // it lands, and a conclusively dead session surfaces through the
        // global signed-out handling (#628) via the mint request itself.
        if ((status === 401 || status === 403) && !isThirdPartyUrl(e.error?.url)) {
          // audit(w3-maps A2): recoverTileAuth() returning false is
          // contractual — a recent re-mint didn't cure the error (revoked
          // grant, expired signature). Previously the return value was
          // discarded and the surface stayed fully silent; fall through to
          // the existing deduped tile-error toast instead.
          // fix(#890): the re-mint still runs for a raster/DEM failure — the
          // mint request goes through apiFetch, whose proactive refresh renews
          // an expiring JWT, and that Bearer is the ONLY thing that fixes a
          // raster 401 (fix(#890) codex P1). But a fresh sig cannot help a
          // raster tile, so its `true` must not silence the surface the way it
          // does for a vector tile: toast regardless, matching
          // `isHandledTileAuthError`, which keeps logging these.
          const recovering = recoverTileAuth();
          // fix(#907): …unless a session renewal is in flight, which is the one
          // thing that DOES fix a raster 401, and whose post-rotation reload is
          // about to retry these tiles.
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

      // chore(#835): shared resolver; the read-only viewer stubs every missing
      // image (knownImagesOnly: false) to keep the public console clean.
      map.setMissingStyleImageResolver(makeStyleImageMissingResolver(map, { knownImagesOnly: false }));

      // `idle` fires when no tiles are loading, no transitions are in
      // progress, and no animations are running. We flip the container's
      // data-tiles-loaded attribute to true on idle so Playwright (and V-13's
      // loading-affordance consumers) can rely on a deterministic signal
      // instead of an arbitrary wait.
      // fix(#430 V-13): re-arm on every camera move instead of firing once — the
      // attribute previously never toggled back to "false" after the initial
      // idle, so it couldn't distinguish "settled" from "tiles loading after
      // a pan/zoom" (a false "map fully rendered" signal mid-move).
      map.on('movestart', () => setTilesIdle(false));
      map.on('idle', () => setTilesIdle(true));

      setMapReady(true);
      onMapReady?.(map);
    },
    [onMapReady, embedToken, t, recoverTileAuth],
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

  // Click handler: show popup with feature attributes
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
      // Keyboard parity with BuilderMap: the popup was mouse-only for
      // non-cluster features — Enter/Space was a no-op unless the
      // centre-of-canvas hit happened to be a cluster. Mirror handleClick's
      // mapping so keyboard users can open the same feature popup.
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
    // BUG-037-style idle retry (mirrors the layer-sync/visibility effects):
    // on a cold hard load — exactly how a share link opens — the style is
    // still transitioning when this effect runs, and a plain early-return
    // never re-attached the click listener, leaving popups inert for every
    // geometry family on the shared-viewer surface (#431 QA finding).
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

  // Mousemove: pointer cursor on interactive features
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

  // Clear popup when layer visibility changes
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
        basemapPosition: bc?.basemap_position,
        mvtSourceLayerPrefix: tc?.mvt_source_layer_prefix,
      },
      basemapConfig: bc,
      showBasemapLabels: sbl,
      reorderDataLayerIds: syncInputs,
    });
  }, []);

  // Sync layers to map (on data/visibility changes)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!tileConfigReady) return;
    // Gate the first sync on tile tokens arriving: syncLayersToMap branches
    // on `token?.kind === 'raster'` to pick the raster adapter vs. the
    // vector path. If we sync before tokens land, every layer — including
    // rasters — is added as a vector source with a `.pbf` URL, which the
    // server rejects for raster datasets and maplibre never recovers from.
    // The embed-token path has its own transformRequest flow and doesn't
    // depend on tokenMap, so it's allowed to sync immediately.
    if (!embedToken && layers.length > 0 && tokenMap.size === 0) return;
    // BUG-037-style idle retry (mirrors the visibility effect below): on a
    // cold/hard page load — exactly how a shared-link visitor arrives — the
    // style can still be transitioning when this effect first runs. Terrain
    // maps widen that window (the raster-dem terrain source delays readiness).
    // A plain `!isStyleLoaded()` early-return left the data layers permanently
    // unsynced because nothing re-triggers this effect once the style settles
    // (the style.load listener can attach after the event already fired on a
    // cold mount). Defer the sync to the next idle so it always lands.
    if (!map.isStyleLoaded()) {
      const retrySync = () => runSync(map);
      map.once('idle', retrySync);
      return () => { map.off('idle', retrySync); };
    }
    runSync(map);
  // Note: visibleLayers intentionally excluded — the dedicated visibility effect below handles it
  }, [layers, mapReady, tileConfigReady, tileConfig?.cdn_base_url, tileConfig?.mvt_source_layer_prefix, tokenMap, showBasemapLabels, runSync, embedToken, geojsonVersion]);

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
        // the column set comes from THIS layer only. fix(#403): the
        // server-cluster path needs the cols= opt-in too — its unclustered
        // features are styled/popup-inspected like plain vector features.
        const cols = getDataDrivenColumnsForLayer({
          style_config: layer.style_config ?? null,
          paint: (layer.paint as Record<string, unknown> | undefined) ?? {},
          label_config: layer.label_config ?? null,
          // codex P2 on fix(#403): include filter-only columns, or a layer
          // whose filter references a column unused by paint/labels/popups
          // loses it from cols= on the first token refresh (parity with the
          // initial getDataDrivenColumnsForSource build).
          filter: layer.filter ?? null,
          popup_config: layer.popup_config ?? null,
        });
        // fix(#394) VT-02 (codex P2): keep the `_v=` cache-buster on
        // token-refresh rebuilds (parity with the initial source build).
        const newUrl = strategy.kind === 'server-tile'
          ? buildClusterTileUrl(layer.table_name, token, tileBaseUrl, layer.tile_version ?? undefined, {
              clusterRadius: typeof builder?.clusterRadius === 'number' ? builder.clusterRadius : 48,
              clusterMaxZoom: typeof builder?.clusterMaxZoom === 'number' ? builder.clusterMaxZoom : 14,
            }, cols)
          : buildSignedTileUrl(layer.table_name, token, tileBaseUrl, layer.tile_version ?? undefined, cols);
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
    if (!map || !tileConfigReady) return;

    const applyVisibilityDiff = () => {
      const prev = prevVisibleRef.current;
      for (const { layer, key } of layerEntries) {
        const wasVisible = prev.has(key);
        const isVisible = visibleLayers.has(key);
        if (wasVisible === isVisible) continue;

        const type = layer.is_dem === true && effectiveDemRenderMode(layer.style_config, layer.is_dem) === 'hillshade'
          ? 'hillshade'
          : resolveAdapterType(layer.geometry_type, layer.style_config, layer.paint as Record<string, unknown>);
        const adapter = getAdapter(type);
        const adapterInput = toAdapterInput(
          layer,
          key,
          visibleLayers,
          tileConfig?.mvt_source_layer_prefix,
        );
        adapter.syncVisibility(map, adapterInput);

        const labelId = prefixed('label', key, VIEWER_PREFIX);
        if (map.getLayer(labelId)) {
          map.setLayoutProperty(labelId, 'visibility', isVisible ? 'visible' : 'none');
        }
      }
      prevVisibleRef.current = new Set(visibleLayers);
    };

    // BUG-037: a plain early-return on !isStyleLoaded() dropped the toggle
    // permanently — prevVisibleRef wasn't advanced, and nothing in the deps
    // changes when the style finishes transitioning, so the checkbox and the
    // map stayed out of sync until the user toggled again. Mirror the
    // BuilderMap idle-retry: re-apply the diff once the map settles.
    if (!map.isStyleLoaded()) {
      map.once('idle', applyVisibilityDiff);
      return () => { map.off('idle', applyVisibilityDiff); };
    }
    applyVisibilityDiff();
  }, [visibleLayers, layerEntries, mapReady, tileConfigReady, tileConfig?.mvt_source_layer_prefix]);

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
  }, [mapReady, embedToken, runSync, reseedTerrainOnStyleLoad, applyViewerBasemapConfig]);

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

    const invalidateTileTokens = useInvalidateTileTokens();
  const { contextLost, reload } = useWebGLRecovery(mapRef, mapReady, invalidateTileTokens);

  return (
    <div
      className={`relative h-full w-full ${!mapReady ? 'bg-muted animate-pulse' : ''}`}
      // audit(w3-maps): aria-label on <MapGL> is silently dropped —
      // @vis.gl/react-maplibre v8 forwards only id/ref/style, and MapLibre
      // labels its canvas "Map". Label the wrapper region instead (same
      // pattern as DatasetMap's shell).
      role="region"
      aria-label={t('viewer.map.ariaLabel', { defaultValue: 'Map viewer' })}
      data-tiles-loaded={tilesIdle ? 'true' : 'false'}
      data-terrain-ready={terrainReady ? 'true' : 'false'}
    >
      <MapGL
        initialViewState={defaultView}
        mapStyle={mapStyle}
        styleDiffing={false}
        // feat(#845): the prop covers the cold-mount window — react-maplibre
        // applies it on the initial style.load, before our onLoad-captured
        // appearance sync can run. Frozen at mount: a CHANGED projection prop
        // goes through react-maplibre's unguarded _updateSettings setter,
        // which throws mid style-swap (Codex P2 r4 on #848). Runtime changes
        // and basemap switches go through applyMapBasemapAppearance instead.
        projection={initialProjection}
        style={{ width: '100%', height: '100%' }}
        attributionControl={false}
        minZoom={1}
        onLoad={handleLoad}
        // fix(#755): claim the wrapper's `error` fallback so a handled
        // tile-auth 401/403 (#621 re-mint / embed-expired toast in
        // handleLoad's error handler) stops double-logging a red AJAXError
        // console row.
        onError={logUnhandledMapError}
      >
        <NavigationControl position="top-right" />
        <FullscreenControl position="top-right" />
        {terrainReady && (
          <TerrainControl source="terrain-dem" position="top-right" />
        )}
        <ScaleControl position="bottom-left" maxWidth={100} unit="metric" />
        {/* feat(#1472): the `key` is load-bearing, not cosmetic. react-maplibre's
            useControl builds the control once with `useMemo(…, [])`, so a
            changed `customAttribution` prop never reaches MapLibre. Keying on
            the credit set remounts the control (removeControl + addControl)
            exactly when that set changes, and not on any other render.
            attributionControlKey owns the derivation so its injectivity can be
            tested directly — see the note there. */}
        <AttributionControl
          key={attributionControlKey(layerAttributions)}
          position="bottom-right"
          compact={true}
          customAttribution={
            layerAttributions.length > 0 ? layerAttributions : undefined
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
      />
      {/* fix(#430 V-05): loading veil over the pre-terrain flat-DEM frame — fades
          out once the saved-camera 3D view is ready to show (or immediately
          for non-terrain maps). */}
      <div
        aria-hidden="true"
        data-testid="viewer-entry-veil"
        className={`pointer-events-none absolute inset-0 z-20 bg-muted transition-opacity duration-500 ${revealed ? 'opacity-0' : 'opacity-100'}`}
      />
      {showBranding && (
        <span
          data-testid="viewer-branding-overlay"
          className="absolute bottom-2 left-2 z-10 text-xs text-muted-foreground bg-background/70 rounded-sm px-2 py-1 pointer-events-none"
        >
          {t('export.poweredBy', { defaultValue: 'Powered by GeoLens' })}
        </span>
      )}
      {contextLost && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80">
          <div className="text-center space-y-2">
            <p className="text-sm text-muted-foreground">{t('errorBoundary.mapMessage')}</p>
            <button type="button" onClick={reload} className="text-sm underline text-primary hover:text-primary/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring rounded-sm px-1">{t('reload')}</button>
          </div>
        </div>
      )}
    </div>
  );
});
