import { useEffect, useRef, useCallback, useState, useMemo, memo } from 'react';
import { useWidgetStore } from '@/stores/map-widget-store';
import { isWidgetIdAvailable } from '@/components/map-widgets';
import { toast } from 'sonner';
import { Map as MapGL, NavigationControl, ScaleControl } from '@vis.gl/react-maplibre';
import { useBasemaps, useEnabledWidgets, useMapDefaults, useTileConfig } from '@/hooks/use-settings';
import { findBasemapById, sanitizeMaplibreStyle, toMaplibreStyle, BLANK_BASEMAP_ID } from '@/lib/basemap-utils';
import { buildClusterTileUrl, buildSignedTileUrl } from '@/lib/tile-utils';
import { useTileTokens } from '@/hooks/use-tile-token';
import { getEnvConfig } from '@/lib/env';
import { useAuthStore } from '@/stores/auth-store';
import { useWebGLRecovery } from '@/hooks/use-webgl-recovery';
import i18n from '@/i18n/i18n';
import { useTranslation } from 'react-i18next';
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
import { clusterFallbackMessage, getClusterSourceEligibility, getClusterSourceStrategy, isClusterRenderMode, shouldFetchClusterGeoJson } from './cluster-source';
import type { StyleSpecification, VectorTileSource } from 'maplibre-gl';
import {
  syncLayersToMap,
  toSyncInput,
  reorderBasemapLabels,
  reorderBasemapAboveData,
  reorderDataLayers,
  applyBasemapConfigToMap,
  getSourceIdForLayer,
  getLayerId,
  ensureRasterDemTerrainSource,
  isTerrainCapableDemLayer,
  normalizeTerrainExaggeration,
  TERRAIN_SOURCE_ID,
} from './map-sync';
import type { MapLibreEvent, MapMouseEvent } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapBasemapConfig, MapLayerResponse, MapTerrainConfig } from '@/types/api';
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
  const mapRef = useRef<MaplibreMap | null>(null);
  const managedSourcesRef = useRef<Set<string>>(new Set());
  const errorHandlerRef = useRef<((e: { error: { message?: string; status?: number } }) => void) | null>(null);
  // SF-08: latch first-load success so transient 5xx during save don't surface as outage
  const basemapLoadedAtRef = useRef<number | null>(null);
  const lastOrderKeyRef = useRef('');
  const [mapReady, setMapReady] = useState(false);
  // Phase 1051 WR-04: state mirror of mapRef.current so MapCoordReadout consumes
  // the map via state, not by reading a ref during render. Refs don't trigger
  // re-renders, so passing mapRef.current directly relied on setMapReady firing
  // in the same render cycle — a fragile implicit coupling.
  const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);
  const [tilesLoading, setTilesLoading] = useState(false);
  const [basemapNotice, setBasemapNotice] = useState<'style' | 'tiles' | null>(null);
  // `tilesIdle` drives the `data-tiles-loaded` DOM attribute on the outer
  // container. Mirrors the ViewerMap hook from 6a5f0181 so the Playwright
  // demo-smoke spec can poll a deterministic signal regardless of whether
  // /maps/:id resolved to BuilderMap (authenticated editor) or ViewerMap
  // (anonymous viewer) via MapViewerGate.
  const [tilesIdle, setTilesIdle] = useState(false);
  const [popupInfo, setPopupInfo] = useState<{
    longitude: number;
    latitude: number;
    features: FeatureInfo[];
  } | null>(null);

  const { data: basemaps } = useBasemaps();
  const { data: mapDefaults } = useMapDefaults();
  const { data: tileConfig } = useTileConfig();
  const enabledWidgetsQuery = useEnabledWidgets();
  const enabledWidgetIds = useMemo(
    () => enabledWidgetsQuery.data ?? (enabledWidgetsQuery.isLoading ? [] : null),
    [enabledWidgetsQuery.data, enabledWidgetsQuery.isLoading],
  );
  const isBlank = basemapStyle === BLANK_BASEMAP_ID;
  const basemapEntry = isBlank ? undefined : findBasemapById(basemaps ?? [], basemapStyle);
  const fallbackUrl = 'https://tiles.openfreemap.org/styles/positron';
  const styleValue = useMemo(
    () => isBlank
      ? toMaplibreStyle(BLANK_BASEMAP_ID)
      : toMaplibreStyle(basemapEntry?.url ?? fallbackUrl, basemapEntry?.attribution),
    [isBlank, basemapEntry?.url, basemapEntry?.attribution],
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

    // SF-08: reset latch on basemap change so a new basemap's first-load failure
    // surfaces correctly.
    basemapLoadedAtRef.current = null;

    fetch(styleValue, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Basemap style request failed: ${response.status}`);
        return response.json() as Promise<StyleSpecification>;
      })
      .then((style) => {
        if (!cancelled) {
          setMapStyle(sanitizeMaplibreStyle(style));
          setBasemapNotice(null);
          // SF-08: latch first-load success so transient 5xx during save don't
          // surface as outage.
          basemapLoadedAtRef.current = Date.now();
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (import.meta.env.DEV) console.warn('[BuilderMap] Basemap style sanitization failed:', error);
        if (!cancelled) {
          setBasemapNotice('style');
          // Phase 1051 WR-06: keep the placeholder background style on fetch
          // failure. Previously we passed the raw URL string to MapGL, which
          // triggered a second (uncancelable) fetch and could flash a different
          // intermediate state. The user already sees the toast surfaced by
          // errorHandlerRef + the basemapNotice banner.
        }
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [styleValue]);

  // Fetch tile tokens for all layers
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

  const clusterGeoJsonDataRef = useRef<Map<string, GeoJSON.FeatureCollection>>(new Map());
  const clusterFallbackNotifiedRef = useRef<Set<string>>(new Set());
  const [clusterGeoJsonVersion, setClusterGeoJsonVersion] = useState(0);
  const clusterSourceLayers = useMemo(
    () => layers.filter((layer) => isClusterRenderMode(layer)),
    [layers],
  );

  useEffect(() => {
    let cancelled = false;
    if (clusterSourceLayers.length === 0) {
      if (clusterGeoJsonDataRef.current.size > 0) {
        clusterGeoJsonDataRef.current = new Map();
        setClusterGeoJsonVersion((version) => version + 1);
      }
      return () => {
        cancelled = true;
      };
    }

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
          const message = clusterFallbackMessage(eligibility.status);
          const key = `${layer.id}:${eligibility.status}:${eligibility.featureCount ?? 'unknown'}`;
          if (message && !clusterFallbackNotifiedRef.current.has(key)) {
            clusterFallbackNotifiedRef.current.add(key);
            toast.warning(t('builderMap.clusterFallback', {
              defaultValue: '{{name}} is rendering as points: {{reason}}',
              name: layerName,
              reason: message,
            }));
          }
          return;
        }
        try {
          const response = await fetchBoundedGeoJson(layer.dataset_id);
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
    };
  }, [clusterSourceLayers, t]);

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

  const terrainStateRef = useRef({ terrainConfig, layers, tokenMap });
  terrainStateRef.current = { terrainConfig, layers, tokenMap };

  const applyTerrainConfig = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const { terrainConfig: currentTerrainConfig, layers: currentLayers, tokenMap: currentTokenMap } = terrainStateRef.current;
    if (!currentTerrainConfig?.enabled || !currentTerrainConfig.source_dataset_id) {
      map.setTerrain(null);
      return;
    }

    const demLayer = currentLayers.find(
      (layer) => layer.dataset_id === currentTerrainConfig.source_dataset_id && isTerrainCapableDemLayer(layer),
    );
    const token = demLayer ? currentTokenMap.get(demLayer.dataset_id) : null;
    if (!demLayer || token?.kind !== 'raster') {
      map.setTerrain(null);
      return;
    }

    ensureRasterDemTerrainSource(map, token.tile_url, {
      tileSize: token.tile_size,
      minzoom: token.minzoom,
      maxzoom: token.maxzoom,
      bounds: token.bounds,
    });
    map.setTerrain({
      source: TERRAIN_SOURCE_ID,
      exaggeration: normalizeTerrainExaggeration(currentTerrainConfig.exaggeration),
    });
  }, []);

  const terrainLayerKey = layers
    .map((layer) => `${layer.dataset_id}:${String(layer.is_dem)}:${layer.dataset_record_type ?? ''}`)
    .join(',');

  // Keep a ref to the latest sync inputs so style.load handler can access them
  const syncInputsRef = useRef({ layers, tokenMap, tileConfig, showBasemapLabels, basemapConfig });
  syncInputsRef.current = { layers, tokenMap, tileConfig, showBasemapLabels, basemapConfig };

  const layersRef = useRef(layers);
  layersRef.current = layers;

  // Cached queryable layer IDs — updated when layers change, read by click/mousemove handlers
  const queryLayerIdsRef = useRef<string[]>([]);

  // Tracks whether measurement widget is active — avoids re-registering map handlers on every toggle
  const measureActiveRef = useRef(false);

  useEffect(() => {
    measureActiveRef.current =
      useWidgetStore.getState().activeWidgets.has('measurement') &&
      isWidgetIdAvailable('measurement', enabledWidgetIds);
    return useWidgetStore.subscribe((state) => {
      measureActiveRef.current =
        state.activeWidgets.has('measurement') &&
        isWidgetIdAvailable('measurement', enabledWidgetIds);
    });
  }, [enabledWidgetIds]);

  const handleLoad = useCallback(
    (e: MapLibreEvent) => {
      const map = e.target;
      mapRef.current = map;
      // Phase 1051 WR-04: keep state mirror in sync with the ref so consumers
      // (e.g. MapCoordReadout) re-render when the map binds.
      setMapInstance(map);
      setMapReady(true);

      // `idle` fires when no tiles are loading, no transitions are in
      // progress, and no animations are running. Flip the outer container's
      // data-tiles-loaded attribute on first idle so the demo-smoke spec can
      // replace its 2 s arbitrary wait with a deterministic signal. Matches
      // the ViewerMap hook from 6a5f0181.
      map.once('idle', () => setTilesIdle(true));

      // Tile loading indicator
      map.on('dataloading', () => setTilesLoading(true));
      map.on('idle', () => setTilesLoading(false));

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
        const status = e.error?.status;
        // Suppress expected no-data tiles (404) and other client errors
        if (status && status >= 400 && status < 500) {
          if (status === 401 || status === 403) {
            toast.error(t('builderMap.authError', { defaultValue: 'Session expired — reload the page to restore tile access.' }), {
              id: 'builder-map-auth-error',
            });
          }
          return;
        }
        // Surface server errors (5xx) and unknown errors
        if (import.meta.env.DEV) console.warn('[BuilderMap] Map error:', e.error);
        if (!status || status >= 500) {
          // SF-08: suppress the transient connection-issue toast that fires
          // for a few hundred ms immediately after a successful basemap load
          // (MapLibre raises a stale tile error while it transitions between
          // styles). WR-02 (Phase 1050-rev): narrow the suppression to a
          // bounded window after the latch was armed so ongoing tile-server
          // outages (basemap loaded OK → tile CDN goes down 30 min later)
          // still surface a toast / banner. 3000 ms covers the worst-case
          // post-load transient window observed in MCP smoke without
          // masking ongoing outages.
          const loadedAt = basemapLoadedAtRef.current;
          if (loadedAt !== null && Date.now() - loadedAt < 3000) return;
          setBasemapNotice('tiles');
          toast.error(t('builderMap.mapError', { defaultValue: 'Map tile error — some layers may not render correctly.' }), {
            id: 'builder-map-error',
          });
        }
      };
      map.on('error', errorHandlerRef.current);

      onMapRef?.(map);
    },
    [onMapRef, t],
  );

  // Re-add data layers after basemap switch (persistent listener).
  // Unlike the previous map.once() approach that re-registered per URL change,
  // this listener survives any number of rapid style swaps — fixing the race
  // where cleanup removed the listener before style.load fired.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const onStyleLoad = () => {
      const { layers: l, tokenMap: t, tileConfig: tc, showBasemapLabels: sbl, basemapConfig: bc } = syncInputsRef.current;
      managedSourcesRef.current = new Set();
      lastOrderKeyRef.current = '';
      // B-01 fix: gate on tokenMap presence rather than the isLoading boolean
      // so a later token arrival is picked up by the main sync effect's
      // tokenMap dep — no separate retry needed.
      if (l.some((layer) => layer.dataset_id && !t.has(layer.dataset_id))) return;
      const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tc?.cdn_base_url || undefined;
      syncLayersToMap(map, l.map(toSyncInput), t, tileBaseUrl, managedSourcesRef, lastOrderKeyRef, clusterGeoJsonDataRef.current, { showBasemapLabels: sbl, basemapPosition: bc?.basemap_position });
      applyBasemapConfigToMap(map, bc, sbl);
      reorderBasemapAboveData(map, bc?.basemap_position);
      applyTerrainConfig();
      refreshQueryLayerIds();
    };

    map.on('style.load', onStyleLoad);
    return () => {
      map.off('style.load', onStyleLoad);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refreshQueryLayerIds is stable; [mapReady] is the only structural trigger
  }, [mapReady, applyTerrainConfig]);

  // Helper: refresh the cached list of queryable layer IDs.
  // Called after every syncLayersToMap so the click/hover handlers
  // see the layers that actually exist on the map right now.
  // Reads from `layersRef.current` (updated on every render) so the callback
  // identity stays stable — required because `runSync` below lists it as a
  // dep and is itself a dep of the main sync effect.
  const refreshQueryLayerIds = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    queryLayerIdsRef.current = layersRef.current
      .filter((l) => l.visible && l.layer_type !== 'raster_geolens')
      .flatMap((l) => {
        const layerId = getLayerId(l.id);
        return isClusterRenderMode(l) ? clusterInteractiveLayerIds(layerId) : [layerId];
      })
      .filter((id) => map.getLayer(id));
  }, []);

  /**
   * Run a full layer sync against the map, reading all inputs from
   * `syncInputsRef.current` so the effect that calls this is immune to
   * closure-stale inputs. Mirrors ViewerMap.tsx's `runSync` shape — see the
   * SP-03 / B-01-followup quick task for why this pattern is required.
   */
  const runSync = useCallback((map: MaplibreMap) => {
    const { layers: ls, tokenMap: tm, tileConfig: tc, showBasemapLabels: sbl, basemapConfig: bc } = syncInputsRef.current;
    const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tc?.cdn_base_url || undefined;
    const syncInputs = ls.map(toSyncInput);
    syncLayersToMap(map, syncInputs, tm, tileBaseUrl, managedSourcesRef, lastOrderKeyRef, clusterGeoJsonDataRef.current, { showBasemapLabels: sbl, basemapPosition: bc?.basemap_position });
    applyTerrainConfig();
    refreshQueryLayerIds();
  }, [applyTerrainConfig, refreshQueryLayerIds]);

  // O(1) lookup map: feature.layer.id (with `layer-` prefix) → layer/source metadata.
  // Rebuilt only when the layers ref content changes; kept in a ref so the
  // effect below doesn't re-register on every layers change.
  const layerByMapIdRef = useRef<Map<string, { layer: MapLayerResponse; sourceId: string }>>(new Map());
  useEffect(() => {
    const byMapId = new Map<string, { layer: MapLayerResponse; sourceId: string }>();
    for (const l of layers) {
      const layerId = getLayerId(l.id);
      // CR-02 (Phase 1050-rev): route through getSourceIdForLayer so the
      // sourceId stored alongside each layer's MapLibre layer id reflects
      // the SF-04 dedupe contract. Cluster layers stay per-layer (the
      // helper's branching keeps `source-${id}` for clusters), so
      // `activateClusterFeature(map, feature, hit.sourceId)` (line 544)
      // continues to receive the cluster's per-layer source id.
      const sourceId = getSourceIdForLayer(l);
      const ids = isClusterRenderMode(l) ? clusterInteractiveLayerIds(layerId) : [layerId];
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

    const handleClick = (e: MapMouseEvent) => {
      if (!map.isStyleLoaded()) return;
      if (measureActiveRef.current) return;
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
        if (measureActiveRef.current) return;
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
      if (measureActiveRef.current) return;
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
      if (!clusterHit) return;
      event.preventDefault();
      handleClusterHit(clusterHit.feature, clusterHit.hit, null);
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

  // Structural key: only changes when layers are added/removed/reordered/toggled —
  // NOT on paint/filter edits (those are handled incrementally by use-layer-map-sync).
  // Also drives popup clearing on visibility changes (P-17: single key replaces separate visibilityKey).
  const structuralKey = useMemo(
    () => layers.map((l) => {
      const builder = l.style_config?.builder;
      const clusterKey = l.style_config?.render_mode === 'cluster'
        ? `:${builder?.clusterRadius ?? ''}:${builder?.clusterMaxZoom ?? ''}`
        : '';
      return `${l.id}:${l.visible}:${l.dataset_id}${clusterKey}`;
    }).join(','),
    [layers],
  );

  // Clear popup when layer visibility changes
  useEffect(() => {
    setPopupInfo(null);
  }, [structuralKey]);

  // Sync layers to map — runs on structural changes (add/remove/visibility) and token refresh.
  // Paint/filter/opacity edits are handled imperatively by use-layer-map-sync.ts.
  //
  // SP-03 / B-01-followup: this effect was previously keyed on `structuralKey`
  // (a derived string) and called `syncLayersToMap` directly with a memoized
  // `syncInputs`. That combination left a closure-stale-input race on the very
  // first "Add to map" against an empty builder. Mirroring ViewerMap's
  // `runSync(map)` + `syncInputsRef.current` pattern eliminates the race by
  // construction: every input is read fresh from the ref at call time.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    // Token gate (ViewerMap-style): wait for tokens before any sync.
    if (layers.length > 0 && tokenMap.size === 0) return;
    // Defense in depth: also wait if any specific layer is still missing its
    // token (e.g. a partial batch — one dataset cached, one still in flight).
    if (layers.some((l) => l.dataset_id && !tokenMap.has(l.dataset_id))) return;

    // Style gate. If the basemap style is currently transitioning, the
    // previous shape (return early) left a permanent miss: nothing in the
    // effect's dep array would change later, and the once-fired `style.load`
    // listener already ran with the pre-add state. SP-03 / B-01-followup:
    // attach a one-shot `idle` listener so the sync is retried as soon as
    // the map settles. `idle` fires after style.load + tile loading +
    // transitions complete, which is exactly when `runSync` can succeed.
    if (!map.isStyleLoaded()) {
      const retry = () => runSync(map);
      map.once('idle', retry);
      return () => { map.off('idle', retry); };
    }
    runSync(map);
    // UX-03 (Phase 1051): include basemap_position so dragging basemap top↔bottom
    // re-runs the sync's reorder pipeline (the orderKey check inside
    // syncLayersToMap also includes basemap_position to avoid the no-change skip).
  }, [layers, mapReady, tileConfig?.cdn_base_url, tokenMap, showBasemapLabels, basemapConfig?.basemap_position, clusterGeoJsonVersion, runSync]);

  useEffect(() => {
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
  // UX-03 (Phase 1051 Plan 06): if basemap_position='top', run the
  // reorderBasemapAboveData pass LAST so basemap fill/raster layers end up
  // ABOVE data geometry in the MapLibre stack. The standard pipeline above
  // assumes basemap-below-data (the 'bottom' default + legacy behaviour) —
  // when the user drags basemap to top, that ordering must be reversed.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    reorderBasemapLabels(map, showBasemapLabels);
    applyBasemapConfigToMap(map, basemapConfig, showBasemapLabels);
    reorderDataLayers(map, layersRef.current.map((l) => ({ id: l.id })));
    reorderBasemapAboveData(map, basemapConfig?.basemap_position);
  }, [basemapConfig, showBasemapLabels, mapReady]);

  // Update tile URLs in-place when tokens refresh (vector only)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url;

    for (const layer of layers) {
      const token = tokenMap.get(layer.dataset_id) ?? null;
      // Raster tile URLs use nginx auth-check subrequest — nothing to refresh
      if (token?.kind === 'raster') continue;
      // CR-02 (Phase 1050-rev): route through getSourceIdForLayer so the
      // deduped vector source (`source-data-${dataset_table_name}`) is
      // actually located and `setTiles([newUrl])` propagates the refreshed
      // signed token. Before the fix, every non-cluster vector layer's
      // tile URL silently fell out of sync once the signed token expired
      // (~1hr into a session) → MapLibre started emitting 401/403 on every
      // subsequent tile fetch.
      const sourceId = getSourceIdForLayer(layer);
      const source = map.getSource(sourceId);
      if (source && source.type === 'vector') {
        const strategy = getClusterSourceStrategy(layer);
        const builder = layer.style_config?.builder;
        const newUrl = strategy.kind === 'server-tile'
          ? buildClusterTileUrl(layer.dataset_table_name, token, tileBaseUrl, undefined, {
              clusterRadius: typeof builder?.clusterRadius === 'number' ? builder.clusterRadius : 48,
              clusterMaxZoom: typeof builder?.clusterMaxZoom === 'number' ? builder.clusterMaxZoom : 14,
            })
          : buildSignedTileUrl(layer.dataset_table_name, token, tileBaseUrl);
        (source as VectorTileSource).setTiles([newUrl]);
      }
    }
  }, [tokenMap, layers, mapReady, tileConfig?.cdn_base_url]);

  // Track whether we've restored a saved view (skip auto-fit on initial load)
  const hasSavedView = !!(initialViewState?.center_lng != null && initialViewState?.center_lat != null);
  const initialFitDoneRef = useRef(false);
  const prevLayerCountRef = useRef(layers.length);

  // Auto-fit to visible layers (skip on initial load if saved view exists)
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

    const visibleLayers = layers.filter((l): l is MapLayerResponse & { dataset_extent_bbox: number[] } => l.visible && !!l.dataset_extent_bbox);
    if (visibleLayers.length === 0) return;

    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;

    for (const l of visibleLayers) {
      const bbox = l.dataset_extent_bbox;
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
  }, [layers.length, structuralKey, mapReady]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (mapRef.current && errorHandlerRef.current) {
        mapRef.current.off('error', errorHandlerRef.current);
      }
      // Phase 1051 WR-04: keep state mirror in sync on teardown.
      setMapInstance(null);
      onMapRef?.(null);
    };
  }, [onMapRef]);

  const defaultView = useMemo(() => ({
    longitude: initialViewState?.center_lng ?? mapDefaults?.center_lng ?? 0,
    latitude: initialViewState?.center_lat ?? mapDefaults?.center_lat ?? 20,
    zoom: Math.max(initialViewState?.zoom ?? mapDefaults?.zoom ?? 2, 2),
    bearing: initialViewState?.bearing ?? 0,
    pitch: initialViewState?.pitch ?? 0,
  }), [initialViewState?.center_lng, initialViewState?.center_lat, initialViewState?.zoom, initialViewState?.bearing, initialViewState?.pitch, mapDefaults?.center_lng, mapDefaults?.center_lat, mapDefaults?.zoom]);

  const { contextLost, reload } = useWebGLRecovery(mapRef, mapReady);

  return (
    <div
      className="relative h-full w-full"
      data-tiles-loaded={tilesIdle ? 'true' : 'false'}
    >
      {tilesLoading && (
        <div className="absolute top-0 left-0 right-0 z-10 h-0.5 bg-primary/60 animate-pulse" />
      )}
      {basemapNotice && (
        <div
          role="status"
          aria-live="polite"
          className="absolute left-3 top-3 z-20 max-w-sm rounded-md border bg-background/95 p-3 text-sm shadow-md backdrop-blur"
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
        // PERF-08 (Phase 274): preserveDrawingBuffer dropped — captures use
        // map.triggerRepaint() + synchronous toDataURL() in use-builder-save.ts
        // doCapture / handleExportPNG so the WebGL canvas keeps its default
        // (no-buffer-retention) memory profile during normal editing.
        style={{ width: '100%', height: '100%' }}
        minZoom={1}
        onLoad={handleLoad}
        aria-label={t('map.ariaLabel', { defaultValue: 'Map builder' })}
      >
        {/* RESP-01 (Phase 1051): NavigationControl anchored top-left so it does not
            collide with the right-side BuilderRail (Notes/History/Ask AI buttons) at
            narrow viewports (≤1024px rail mode). ScaleControl stays bottom-left;
            no vertical overlap with the new NavigationControl placement. */}
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
            <button type="button" onClick={reload} className="cursor-pointer text-sm underline text-primary hover:text-primary/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring rounded px-1">{t('common.reload')}</button>
          </div>
        </div>
      )}
    </div>
  );
});
