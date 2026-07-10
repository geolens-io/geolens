import { memo, useMemo, useEffect, useRef, useCallback, useState, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { Map as MapGL, Source, Layer, NavigationControl } from '@vis.gl/react-maplibre';
import { useTheme } from '@/components/theme-provider';
import { useBasemaps, useMapDefaults, useTileConfig } from '@/hooks/use-settings';
import { getThemeBasemap, toMaplibreStyle, findBasemapById } from '@/lib/basemap-utils';
import { BasemapToggle } from '@/components/map/BasemapToggle';
import { useDrawingStore } from '@/stores/drawing-store';
import { useTerraDraw } from '@/components/drawing/hooks/use-terra-draw';
import { useFeatureEditing, showAllFeaturesInTiles } from '@/components/dataset/hooks/use-feature-editing';
import { DrawingToolbar } from '@/components/drawing/DrawingToolbar';
import { AttributeForm } from '@/components/drawing/AttributeForm';
import { useTileToken, useInvalidateTileTokens } from '@/hooks/use-tile-token';
import { useMapLayers, getSourceLayerName } from '@/components/maps/hooks/use-map-layers';
import { computeLargeExtentView, isLargeExtent } from '@/lib/map-extent';
import { findElevationColumn } from '@/lib/geo-utils';
import { useAuthStore } from '@/stores/auth-store';
import { useWebGLRecovery } from '@/hooks/use-webgl-recovery';
import { MAP_COLORS } from '@/lib/map-colors';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Focus, Maximize2, Minimize2, PenLine } from 'lucide-react';
import { toast } from 'sonner';
import maplibregl from 'maplibre-gl';
import type { LngLatBoundsLike, MapLibreEvent, StyleSpecification } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { Feature, Geometry, GeoJsonProperties } from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';
import { motionDuration } from '@/lib/reduced-motion';

/** System columns excluded from the attribute form */
const SYSTEM_COLUMNS = new Set(['gid', 'geom', 'geom_4326']);

/**
 * Dataset detail map preview.
 *
 * Renders a single dataset's vector tiles with the user's currently active
 * basemap, supports drawing/editing features (when the user has edit permission),
 * and exposes a fullscreen toggle. The map applies the @vis.gl/react-maplibre v8
 * `setTransformRequest` workaround imperatively in `onLoad` because the
 * declarative `transformRequest` prop is silently ignored in v8.
 *
 * Used by the dataset detail page (`pages/DatasetPage.tsx`).
 *
 * fix(#438): ARC-05 — this map is intentionally declarative (@vis.gl JSX
 * <Source>/<Layer>), unlike the builder/viewer which drive an imperative
 * adapter core (map-sync + getAdapter). The split is defensible: this host
 * renders one dataset's tiles with light interaction, so JSX is simpler and
 * needs no incremental paint diffing. Converge onto the adapter core only if
 * this page grows builder-like styling; revisit after the ARC-01 extraction.
 */

interface DatasetMapProps {
  bbox: [number, number, number, number] | null;
  tableName: string | null;
  geometryType: string | null;
  /** fix(#430 codex r18/r19/r22): generic created datasets accept any
   * subtype. Switches BOTH draw-mode gating and rendering to the GEOMETRY
   * sentinel — use-map-layers installs all-family renderers for it, so
   * features of any family drawn in the current visit stay visible. */
  hasGenericGeometry?: boolean;
  datasetId?: string;
  columnInfo?: { name: string; type: string }[] | null;
  containerRef?: RefObject<HTMLDivElement | null>;
  canEdit?: boolean;
  recordType?: string;
  rasterTileUrl?: string | null;
  /** ISO timestamp or version string appended to tile URLs to bust browser cache after mutations */
  tileVersion?: string | null;
  onMapReady?: () => void;
  onTileError?: () => void;
  /** Callback for read-only (non-editing) feature clicks, receives the gid */
  onFeatureClick?: (gid: number) => void;
}

export const DatasetMap = memo(function DatasetMap({
  bbox,
  tableName,
  geometryType,
  hasGenericGeometry,
  datasetId,
  columnInfo,
  containerRef,
  canEdit = false,
  recordType,
  rasterTileUrl,
  tileVersion,
  onMapReady,
  onTileError,
  onFeatureClick,
}: DatasetMapProps) {
  const { t } = useTranslation(['dataset', 'common']);
  const { resolvedTheme } = useTheme();
  const { data: basemaps } = useBasemaps();
  const { data: mapDefaults } = useMapDefaults();
  const { data: tileConfig } = useTileConfig();
  const { data: rawTileToken } = useTileToken(datasetId);
  // Narrow to the vector-tile shape expected by downstream hooks.
  // Raster tokens are a separate payload with a preformatted tile_url and
  // are consumed via the rasterTileUrl prop path instead.
  const tileToken = useMemo(
    () =>
      rawTileToken && rawTileToken.kind === 'vector'
        ? { sig: rawTileToken.sig, exp: rawTileToken.exp, scope: rawTileToken.scope }
        : null,
    [rawTileToken],
  );
  const [userBasemapId, setUserBasemapId] = useState<string | null>(null);
  const themeBasemap = getThemeBasemap(basemaps ?? [], resolvedTheme);
  const activeBasemap = useMemo(
    () => userBasemapId
      ? findBasemapById(basemaps ?? [], userBasemapId) ?? themeBasemap
      : themeBasemap,
    [userBasemapId, basemaps, themeBasemap],
  );
  // Initial style for <MapGL> — never changes after first render.
  // All subsequent basemap changes are handled imperatively via the effect below.
  const initialBasemapStyle = useRef<string | import('maplibre-gl').StyleSpecification | null>(null);
  if (initialBasemapStyle.current === null) {
    const bm = themeBasemap;
    initialBasemapStyle.current = bm
      ? toMaplibreStyle(bm.url, bm.attribution)
      : toMaplibreStyle(
          resolvedTheme === 'dark'
            ? 'https://tiles.openfreemap.org/styles/dark'
            : 'https://tiles.openfreemap.org/styles/positron',
        );
  }

  const hasBbox = bbox && bbox.length >= 4;
  const mapRef = useRef<MaplibreMap | null>(null);
  const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);
    const invalidateTileTokens = useInvalidateTileTokens();
  const { contextLost, reload } = useWebGLRecovery(mapRef, !!mapInstance, invalidateTileTokens);
  // fix(#430 V-13): dataset-detail preview map had no data-tiles-loaded signal at
  // all. Mirror the re-arming ViewerMap/BuilderMap behavior: false while a
  // camera move is in flight, true once idle (no tiles loading / no
  // transitions / no animations running).
  const [tilesIdle, setTilesIdle] = useState(false);
  const tilesIdleMovestartHandlerRef = useRef<(() => void) | null>(null);
  const tilesIdleIdleHandlerRef = useRef<(() => void) | null>(null);

  // Raster hero-state hardening (#13): ensure onMapReady / onTileError each fire
  // AT MOST ONCE per map mount, and that the imperatively-attached
  // ``sourcedata``/``error`` listeners are removed on teardown so a
  // ``key={mapKey}`` remount can't stack listeners (which churned setState and
  // could freeze the tab when titiler is cold and the tile grid is a mix of
  // 200/204/error). Refs are reset whenever a new map mounts via handleLoad.
  const readyFiredRef = useRef(false);
  // Tracks a *confirmed* raster load (isSourceLoaded) vs a soft 204-only ready,
  // so a sparse-COG 204 doesn't permanently block the error/retry overlay.
  const readyConfirmedRef = useRef(false);
  const errorFiredRef = useRef(false);
  const rasterListenersRef = useRef<{
    error?: (e: { error: { message?: string; status?: number } }) => void;
    sourcedata?: (e: { sourceId?: string; isSourceLoaded?: boolean }) => void;
  }>({});

  const elevationColumn = useMemo(
    () => geometryType?.toUpperCase().includes('POLYGON') ? findElevationColumn(columnInfo) : null,
    [geometryType, columnInfo],
  );

  // fix(#430 codex r19/r22): generic datasets use the GEOMETRY sentinel for
  // BOTH drawing and rendering — use-map-layers installs all-family
  // renderers for it (r21), so a point-only generic sketch still renders a
  // line drawn in the same visit. elevationColumn above stays keyed on the
  // concrete display type (extrusion never applies to generic sketches).
  const drawGeometryType = hasGenericGeometry ? 'GEOMETRY' : geometryType;

  const { addVectorLayers, addRasterLayers, addOverlaySource } = useMapLayers({
    tableName,
    geometryType: drawGeometryType,
    rasterTileUrl,
    tileVersion,
    tileToken: tileToken ?? null,
    tileConfigCdnBaseUrl: tileConfig?.cdn_base_url ?? undefined,
    mapRef,
    elevationColumn,
  });

  const [isFullscreen, setIsFullscreen] = useState(false);
  const [pendingGeometry, setPendingGeometry] = useState<Geometry | null>(null);
  const [editingAttributes, setEditingAttributes] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  const discardActionRef = useRef<(() => void) | null>(null);

  const isDrawing = useDrawingStore((s) => s.isDrawing);
  const activeMode = useDrawingStore((s) => s.activeMode);
  const setDrawing = useDrawingStore((s) => s.setDrawing);
  const setMode = useDrawingStore((s) => s.setMode);
  const clearDrawing = useDrawingStore((s) => s.clearDrawing);
  const selectedFeature = useDrawingStore((s) => s.selectedFeature);

  // Editable columns (non-system) for the attribute form
  const editableColumns = useMemo(
    () => (columnInfo ?? []).filter((c) => !SYSTEM_COLUMNS.has(c.name)),
    [columnInfo],
  );

  // Refs to break circular dependency: handleDrawFinish needs saveAndRefresh,
  // and onEditFinish needs setEditDirty — both come from hooks that need TerraDraw.
  const saveAndRefreshRef = useRef<(g: Geometry, p: Record<string, unknown>) => void>(() => {});
  const editFinishRef = useRef<(tdId: string, feature: Feature) => void>(() => {});
  const stableEditFinish = useCallback((tdId: string, feature: Feature) => {
    editFinishRef.current(tdId, feature);
  }, []);

  const handleDrawFinish = useCallback(
    (feature: Feature<Geometry, GeoJsonProperties>) => {
      const geom = feature.geometry;
      if (!geom) return;
      if (editableColumns.length > 0) {
        setPendingGeometry(geom);
      } else {
        saveAndRefreshRef.current(geom, {});
      }
    },
    [editableColumns],
  );

  // --- Terra Draw hook ---
  const {
    setMode: tdSetMode,
    isReady,
    addFeatures,
    removeFeatures,
    selectFeature: tdSelectFeature,
    getSnapshotFeature,
    clear,
    undo,
    canUndo,
  } = useTerraDraw(mapInstance, handleDrawFinish, stableEditFinish);

  // --- Feature editing hook (all CRUD logic) ---
  const {
    saveAndRefresh,
    performDeselect,
    handleSaveEdit,
    handleDeleteFeature,
    handleEditFinish,
    handleEditAttributeSubmit,
    selectFeatureFromMap,
    cleanupOverlayListener,
  } = useFeatureEditing({
    mapRef,
    datasetId,
    tableName,
    tileConfig: tileConfig ?? null,
    tileToken,
    removeFeatures,
    getSnapshotFeature,
    addFeatures,
    selectFeature: tdSelectFeature,
    clear,
  });

  // Keep refs current for callbacks that break circular deps
  saveAndRefreshRef.current = saveAndRefresh;
  editFinishRef.current = handleEditFinish;

  // Clean up overlay listeners on unmount
  useEffect(() => {
    return () => { cleanupOverlayListener(); };
  }, [cleanupOverlayListener]);

  // Clean up imperatively-attached raster tile listeners on unmount (#13).
  // Prevents listeners stacking across a key={mapKey} remount, which churned
  // setState on every tile event and could freeze the tab.
  useEffect(() => {
    return () => {
      const map = mapRef.current;
      if (map) {
        if (rasterListenersRef.current.error) {
          map.off('error', rasterListenersRef.current.error);
        }
        if (rasterListenersRef.current.sourcedata) {
          map.off('sourcedata', rasterListenersRef.current.sourcedata);
        }
        // fix(#430 V-13): detach the re-arming data-tiles-loaded handlers symmetrically.
        if (tilesIdleMovestartHandlerRef.current) {
          map.off('movestart', tilesIdleMovestartHandlerRef.current);
        }
        if (tilesIdleIdleHandlerRef.current) {
          map.off('idle', tilesIdleIdleHandlerRef.current);
        }
      }
      rasterListenersRef.current = {};
    };
  }, []);

  const requestDiscardConfirmation = useCallback((action: () => void) => {
    discardActionRef.current = action;
    setDiscardConfirmOpen(true);
  }, []);

  const handleConfirmDiscard = useCallback(() => {
    discardActionRef.current?.();
    discardActionRef.current = null;
    setDiscardConfirmOpen(false);
    toast(t('map.unsavedDiscarded'));
  }, [t]);

  const handleDeselect = useCallback(() => {
    if (useDrawingStore.getState().isEditDirty) {
      requestDiscardConfirmation(performDeselect);
      return;
    }
    performDeselect();
  }, [performDeselect, requestDiscardConfirmation]);

  // Sync activeMode from store to Terra Draw
  useEffect(() => {
    if (isReady && activeMode) {
      tdSetMode(activeMode);
    }
  }, [isReady, activeMode, tdSetMode]);

  // --- Select mode click handler ---
  // Use canvas click instead of map.on('click') because TerraDraw's adapter
  // intercepts pointer events and prevents MapLibre click events from firing.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || activeMode !== 'select') return;

    const canvas = map.getCanvas();
    let pointerDownPos: { x: number; y: number } | null = null;
    const handlePointerDown = (e: PointerEvent) => {
      pointerDownPos = { x: e.clientX, y: e.clientY };
    };
    const handlePointerUp = (e: PointerEvent) => {
      // Only treat as click if pointer didn't move (not a drag)
      if (!pointerDownPos) return;
      const dx = e.clientX - pointerDownPos.x;
      const dy = e.clientY - pointerDownPos.y;
      pointerDownPos = null;
      if (Math.abs(dx) > 5 || Math.abs(dy) > 5) return;

      // Skip if a TerraDraw feature is already selected (drag/edit in progress)
      if (useDrawingStore.getState().selectedFeature) return;
      const rect = canvas.getBoundingClientRect();
      const point = new maplibregl.Point(e.clientX - rect.left, e.clientY - rect.top);
      selectFeatureFromMap(map, point);
    };

    canvas.addEventListener('pointerdown', handlePointerDown, { capture: true });
    canvas.addEventListener('pointerup', handlePointerUp, { capture: true });
    return () => {
      canvas.removeEventListener('pointerdown', handlePointerDown, { capture: true } as EventListenerOptions);
      canvas.removeEventListener('pointerup', handlePointerUp, { capture: true } as EventListenerOptions);
    };
  }, [activeMode, mapInstance, selectFeatureFromMap]);

  // --- Read-only feature click handler (non-editing mode) ---
  useEffect(() => {
    const map = mapInstance;
    if (!map || !onFeatureClick || !tableName) return;
    // Only active when NOT in drawing/select mode
    if (activeMode) return;

    const handleReadOnlyClick = (e: maplibregl.MapMouseEvent) => {
      const sourceLayer = getSourceLayerName(tableName);
      const features = map.queryRenderedFeatures(e.point, {
        layers: map.getStyle().layers
          ?.filter((l) => (l as Record<string, unknown>)['source-layer'] === sourceLayer)
          .map((l) => l.id) ?? [],
      });
      if (features.length > 0) {
        const gid = features[0].properties?.gid;
        if (gid != null) onFeatureClick(Number(gid));
      }
    };
    map.on('click', handleReadOnlyClick);
    return () => { map.off('click', handleReadOnlyClick); };
  }, [activeMode, mapInstance, onFeatureClick, tableName]);

  // --- Escape key listener ---
  useEffect(() => {
    if (!selectedFeature && !(canUndo && activeMode && activeMode !== 'select')) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        const hasSketchInProgress = canUndo && useDrawingStore.getState().activeMode !== 'select';
        if (selectedFeature) {
          if (useDrawingStore.getState().isEditDirty) {
            requestDiscardConfirmation(performDeselect);
            return;
          }
          performDeselect();
          return;
        }
        if (hasSketchInProgress) {
          requestDiscardConfirmation(() => {
            clear();
            tdSetMode('select');
          });
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [activeMode, canUndo, clear, performDeselect, requestDiscardConfirmation, selectedFeature, tdSetMode]);

  // --- Ctrl+Z / Meta+Z undo shortcut ---
  useEffect(() => {
    if (!isDrawing) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        // Only undo in drawing modes, not select mode
        const currentMode = useDrawingStore.getState().activeMode;
        if (currentMode && currentMode !== 'select') {
          e.preventDefault();
          undo();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isDrawing, undo]);

  // --- Fullscreen state sync ---
  useEffect(() => {
    const el = containerRef?.current;
    if (!el) return;
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    el.addEventListener('fullscreenchange', handler);
    return () => el.removeEventListener('fullscreenchange', handler);
  }, [containerRef]);

  // --- Zoom to extent handler ---
  const handleZoomToExtent = useCallback(() => {
    const map = mapRef.current;
    if (!map || !hasBbox) return;
    if (isLargeExtent(bbox!)) {
      const { center, zoom } = computeLargeExtentView(bbox!);
      // fix(#438): A11Y-08 — instant under prefers-reduced-motion.
      map.flyTo({ center, zoom, duration: motionDuration(1000) });
    } else {
      map.fitBounds(bbox!, { padding: 60, duration: motionDuration(1000) });
    }
  }, [hasBbox, bbox]);

  // --- Fullscreen toggle handler ---
  const handleToggleFullscreen = useCallback(() => {
    if (!containerRef?.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen();
    } else {
      document.exitFullscreen();
    }
  }, [containerRef]);

  // --- Basemap switching (theme change or user selection) ---
  // Single imperative path with transformStyle to preserve custom sources/layers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!activeBasemap) return;
    const newStyle = toMaplibreStyle(activeBasemap.url, activeBasemap.attribution);
    const style = map.getStyle();
    if (!style) return;
    // Only switch if the current style differs
    if (typeof newStyle === 'string' && style.name && newStyle.includes(style.name)) return;
    map.setStyle(newStyle, {
      transformStyle: (_prev: StyleSpecification | undefined, next: StyleSpecification) => {
        const customSources: Record<string, unknown> = {};
        const customLayers: unknown[] = [];
        if (_prev) {
          for (const [id, src] of Object.entries(_prev.sources || {})) {
            if (id === 'basemap' || next.sources?.[id]) continue;
            customSources[id] = src;
          }
          // Only carry over layers whose source exists in the merged style
          const mergedSourceIds = new Set([
            ...Object.keys(next.sources ?? {}),
            ...Object.keys(customSources),
          ]);
          for (const layer of _prev.layers || []) {
            if (next.layers?.some((l) => l.id === layer.id)) continue;
            const src = (layer as { source?: string }).source;
            if (src && !mergedSourceIds.has(src)) continue;
            customLayers.push(layer);
          }
        }
        return {
          ...next,
          sources: { ...next.sources, ...customSources },
          layers: [...next.layers, ...customLayers],
        } as StyleSpecification;
      },
    });
  }, [activeBasemap]);

  const [minx, miny, maxx, maxy] = hasBbox ? bbox : [0, 0, 0, 0];

  const bboxGeojson = useMemo(
    () =>
      hasBbox
        ? {
            type: 'FeatureCollection' as const,
            features: [
              {
                type: 'Feature' as const,
                properties: {},
                geometry: {
                  type: 'Polygon' as const,
                  coordinates: [
                    [
                      [minx, miny],
                      [maxx, miny],
                      [maxx, maxy],
                      [minx, maxy],
                      [minx, miny],
                    ],
                  ],
                },
              },
            ],
          }
        : null,
    [hasBbox, minx, miny, maxx, maxy],
  );

  const handleLoad = useCallback(
    (e: MapLibreEvent) => {
      const map = e.target;
      mapRef.current = map;
      setMapInstance(map);

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

      // Suppress missing-image warnings from basemap sprites (e.g. circle-11, circle_11_black)
      // by providing a transparent 1x1 pixel fallback for any missing icon
      map.on('styleimagemissing', ({ id }: { id: string }) => {
        if (!map.hasImage(id)) {
          map.addImage(id, { width: 1, height: 1, data: new Uint8Array(4) });
        }
      });

      // fix(#430 V-13): data-tiles-loaded signal, re-armed on every camera move
      // (see ViewerMap.tsx / BuilderMap.tsx for the mirrored viewer/builder fix).
      tilesIdleMovestartHandlerRef.current = () => setTilesIdle(false);
      tilesIdleIdleHandlerRef.current = () => setTilesIdle(true);
      map.on('movestart', tilesIdleMovestartHandlerRef.current);
      map.on('idle', tilesIdleIdleHandlerRef.current);

      if (recordType === 'raster_dataset' || recordType === 'vrt_dataset') {
        // Fresh mount: detach any stale listeners and reset the fire-once guards.
        if (rasterListenersRef.current.error) {
          map.off('error', rasterListenersRef.current.error);
        }
        if (rasterListenersRef.current.sourcedata) {
          map.off('sourcedata', rasterListenersRef.current.sourcedata);
        }
        readyFiredRef.current = false;
        readyConfirmedRef.current = false;
        errorFiredRef.current = false;

        addRasterLayers(map);
        const tileStats = { total: 0, failed: 0 };

        // Fire heroState transitions at most once per mount so repeated
        // sourcedata/error events don't churn setState (freeze).
        // `confirmed` marks a real source load (isSourceLoaded). A 204-only ready
        // is "soft": it resolves the loading skeleton for a sparse remote COG but
        // must NOT make success terminal — a later error threshold can override it.
        const fireReadyOnce = (confirmed: boolean) => {
          if (confirmed) readyConfirmedRef.current = true;
          if (readyFiredRef.current || errorFiredRef.current) return;
          readyFiredRef.current = true;
          onMapReady?.();
        };
        const fireErrorOnce = () => {
          // A confirmed load wins over sporadic tile errors; a soft 204-only
          // ready does NOT block the error/retry overlay.
          if (errorFiredRef.current || readyConfirmedRef.current) return;
          errorFiredRef.current = true;
          onTileError?.();
        };

        const handleRasterError = (e: { error: { message?: string; status?: number } }) => {
          const status = (e.error as { status?: number })?.status;
          // HTTP 204 = tile present but empty (no data in this cell). That's a
          // SUCCESS for a sparse remote COG, not a failure — don't count it
          // toward the error threshold, and treat it as the source being usable
          // so heroState resolves deterministically instead of sitting in
          // 'loading'. (#13)
          if (status === 204) {
            tileStats.total++;
            fireReadyOnce(false);
            return;
          }
          if (e.error?.message?.includes('raster-tile-source') ||
              e.error?.message?.includes('Error: HTTP') ||
              status === 404 ||
              status === 500) {
            tileStats.failed++;
            tileStats.total++;
            if (tileStats.failed >= 3 ||
                (tileStats.total >= 4 && tileStats.failed / tileStats.total > 0.5)) {
              fireErrorOnce();
            }
          }
        };
        const handleRasterSourceData = (e: { sourceId?: string; isSourceLoaded?: boolean }) => {
          if (e.sourceId === 'raster-tile-source' && e.isSourceLoaded) {
            tileStats.total++;
            fireReadyOnce(true);
          }
        };

        map.on('error', handleRasterError);
        map.on('sourcedata', handleRasterSourceData);
        rasterListenersRef.current = {
          error: handleRasterError,
          sourcedata: handleRasterSourceData,
        };
      } else {
        addVectorLayers(map);
        addOverlaySource(map);
        onMapReady?.();
      }
    },
    [recordType, addRasterLayers, addVectorLayers, addOverlaySource, onMapReady, onTileError],
  );

  const finishDrawingSession = useCallback(() => {
    if (useDrawingStore.getState().selectedFeature) {
      performDeselect();
    }
    // Always clear hide filters in case a delete left one behind
    const map = mapRef.current;
    if (map) showAllFeaturesInTiles(map);
    clear();
    tdSetMode('select');
    setPendingGeometry(null);
    setEditingAttributes(false);
    clearDrawing();
  }, [clear, clearDrawing, performDeselect, tdSetMode]);

  // Handle close / stop drawing
  const handleCloseDrawing = useCallback(() => {
    const hasDirtyFeatureEdit = Boolean(useDrawingStore.getState().selectedFeature) &&
      useDrawingStore.getState().isEditDirty;
    const hasSketchInProgress = canUndo && activeMode !== null && activeMode !== 'select';

    if (hasDirtyFeatureEdit || hasSketchInProgress) {
      requestDiscardConfirmation(finishDrawingSession);
      return;
    }

    finishDrawingSession();
  }, [activeMode, canUndo, finishDrawingSession, requestDiscardConfirmation]);

  const handleModeChange = useCallback(
    (nextMode: string) => {
      if (nextMode === activeMode) return;

      const sf = useDrawingStore.getState().selectedFeature;
      const hasDirtyFeatureEdit = Boolean(sf) && useDrawingStore.getState().isEditDirty;
      const hasSketchInProgress = canUndo && activeMode !== null && activeMode !== 'select';

      if (sf && nextMode !== 'select') {
        const switchMode = () => {
          performDeselect();
          setMode(nextMode);
        };

        if (hasDirtyFeatureEdit) {
          requestDiscardConfirmation(switchMode);
          return;
        }

        switchMode();
        return;
      }

      if (hasSketchInProgress) {
        requestDiscardConfirmation(() => {
          clear();
          setMode(nextMode);
        });
        return;
      }

      setMode(nextMode);
    },
    [activeMode, canUndo, clear, performDeselect, requestDiscardConfirmation, setMode],
  );

  // Attribute form handlers (new feature creation)
  const handleAttributeSubmit = useCallback(
    (properties: Record<string, unknown>) => {
      if (pendingGeometry) {
        saveAndRefresh(pendingGeometry, properties);
      }
      setPendingGeometry(null);
    },
    [pendingGeometry, saveAndRefresh],
  );

  const handleAttributeCancel = useCallback(() => {
    setPendingGeometry(null);
  }, []);

  // If no bbox and no tableName, nothing to show
  if (!hasBbox && !tableName) {
    return (
      <div className="flex items-center justify-center h-[500px] bg-muted rounded-md text-muted-foreground text-sm">
        {t('page.noSpatialExtent')}
      </div>
    );
  }

  const bounds: LngLatBoundsLike | undefined = hasBbox
    ? [minx, miny, maxx, maxy]
    : undefined;

  let initialViewState;
  if (!bounds) {
    initialViewState = {
      longitude: mapDefaults?.center_lng ?? 0,
      latitude: mapDefaults?.center_lat ?? 20,
      zoom: mapDefaults?.zoom ?? 2,
      ...(elevationColumn ? { pitch: 45 } : {}),
    };
  } else if (hasBbox && isLargeExtent(bbox!)) {
    const { center, zoom } = computeLargeExtentView(bbox!);
    initialViewState = { longitude: center[0], latitude: center[1], zoom, ...(elevationColumn ? { pitch: 45 } : {}) };
  } else {
    initialViewState = { bounds, fitBoundsOptions: { padding: 60 }, ...(elevationColumn ? { pitch: 45 } : {}) };
  }

  // Determine cursor: select mode -> pointer, drawing mode -> crosshair, else default
  const cursor = isDrawing
    ? activeMode === 'select'
      ? 'pointer'
      : 'crosshair'
    : undefined;


  return (
    <div
      className="relative h-full"
      role="region"
      aria-label={t('map.ariaLabel', { defaultValue: 'Dataset map' })}
      data-map-interactive={isDrawing ? 'true' : 'false'}
      data-testid="dataset-map-shell"
      // fix(#430 V-13): "map fully rendered" signal — false during tile loads
      // after a camera move, true at idle. Was previously absent entirely.
      data-tiles-loaded={tilesIdle ? 'true' : 'false'}
    >
      <MapGL
        initialViewState={initialViewState}
        mapStyle={initialBasemapStyle.current ?? ''}
        style={{ width: '100%', height: '100%' }}
        cursor={cursor}
        interactive
        scrollZoom={isFullscreen}
        onLoad={handleLoad}
      >
        <NavigationControl position="top-right" />

        {/* Bbox overlay for spatial context */}
        {bboxGeojson && (
          <Source id="bbox-source" type="geojson" data={bboxGeojson}>
            <Layer
              id="bbox-fill"
              type="fill"
              paint={{
                'fill-color': MAP_COLORS.default.fill,
                'fill-opacity': 0.1,
              }}
            />
            <Layer
              id="bbox-line"
              type="line"
              paint={{
                'line-color': MAP_COLORS.default.fill,
                'line-width': 2,
                'line-dasharray': [2, 2],
              }}
            />
          </Source>
        )}
      </MapGL>

      {canEdit && !isDrawing && datasetId && tableName && drawGeometryType && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="shadow-lg"
            onClick={() => setDrawing(datasetId, tableName, drawGeometryType)}
            data-testid="dataset-map-edit-trigger"
            aria-label={t('actions.editGeometry')}
          >
            <PenLine className="h-4 w-4" />
            {t('actions.editGeometry')}
          </Button>
        </div>
      )}

      {/* Basemap toggle */}
      <BasemapToggle
        value={activeBasemap?.id ?? ''}
        onChange={setUserBasemapId}
        title={t('map.changeBasemap')}
        className="absolute bottom-3 left-3 z-10"
      />

      {/* Zoom-to-extent and fullscreen controls */}
      <div className="absolute z-10 flex flex-col gap-1 right-[10px] top-[120px]">
        {hasBbox && (
          <button
            type="button"
            onClick={handleZoomToExtent}
            className="bg-background border rounded-sm shadow-sm p-1.5 hover:bg-accent"
            title={t('map.zoomToExtent')}
            aria-label={t('map.zoomToExtent')}
          >
            <Focus className="h-4 w-4" />
          </button>
        )}
        {containerRef && (
          <button
            type="button"
            onClick={handleToggleFullscreen}
            className="bg-background border rounded-sm shadow-sm p-1.5 hover:bg-accent"
            title={isFullscreen ? t('map.exitFullscreen') : t('map.fullscreen')}
            aria-label={isFullscreen ? t('map.exitFullscreen') : t('map.fullscreen')}
          >
            {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
        )}
      </div>

      {/* Drawing toolbar overlay */}
      {isDrawing && (
        <DrawingToolbar
          geometryType={drawGeometryType}
          onClose={handleCloseDrawing}
          onModeChange={handleModeChange}
          onSaveEdit={handleSaveEdit}
          onCancelEdit={handleDeselect}
          onEditAttributes={() => setEditingAttributes(true)}
          onDeleteFeature={() => setDeleteConfirmOpen(true)}
          onUndo={undo}
          canUndo={canUndo}
        />
      )}

      {/* Attribute form dialog (new feature creation) */}
      <AttributeForm
        open={pendingGeometry !== null}
        onOpenChange={(open) => {
          if (!open) setPendingGeometry(null);
        }}
        columns={columnInfo ?? []}
        onSubmit={handleAttributeSubmit}
        onCancel={handleAttributeCancel}
      />

      {/* Attribute form dialog (edit existing feature) */}
      <AttributeForm
        open={editingAttributes}
        onOpenChange={(open) => {
          if (!open) setEditingAttributes(false);
        }}
        columns={columnInfo ?? []}
        onSubmit={async (properties) => {
          await handleEditAttributeSubmit(properties);
          setEditingAttributes(false);
        }}
        onCancel={() => setEditingAttributes(false)}
        initialValues={selectedFeature?.properties}
      />

      {/* Delete confirmation dialog */}
      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('map.deleteFeatureTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('map.deleteFeatureDescription')}
              {selectedFeature?.gid != null && (
                <span className="block mt-1 text-xs text-muted-foreground">
                  Feature ID: {selectedFeature.gid}
                </span>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                handleDeleteFeature();
                setDeleteConfirmOpen(false);
              }}
            >
              {t('common:delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={discardConfirmOpen} onOpenChange={setDiscardConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('map.discardChangesTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('map.discardChangesDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => { discardActionRef.current = null; }}>
              {t('common:cancel')}
            </AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={handleConfirmDiscard}>
              {t('map.discardChangesAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {contextLost && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80">
          <div className="text-center space-y-2">
            <p className="text-sm text-muted-foreground">{t('common:errors.mapMessage')}</p>
            <button onClick={reload} className="text-sm underline text-primary">{t('common:reload')}</button>
          </div>
        </div>
      )}
    </div>
  );
});
