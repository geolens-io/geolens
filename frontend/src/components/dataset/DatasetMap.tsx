import { lazy, memo, Suspense, useMemo, useEffect, useRef, useCallback, useState, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { Map as MapGL, Source, Layer, NavigationControl } from '@vis.gl/react-maplibre';
import { useTheme } from '@/components/theme-provider';
import { useBasemaps, useMapDefaults, useTileConfig } from '@/hooks/use-settings';
import { useMapLocale } from '@/hooks/use-map-locale';
import {
  getThemeBasemap,
  makeStyleImageMissingResolver,
  toMaplibreStyle,
  findBasemapById,
  FALLBACK_BASEMAP_STYLE_URL,
  FALLBACK_BASEMAP_STYLE_URL_DARK,
} from '@/lib/basemap-utils';
import { BasemapToggle } from '@/components/map/BasemapToggle';
import { useDrawingStore } from '@/stores/drawing-store';
import { useTerraDraw } from '@/components/drawing/hooks/use-terra-draw';
import { useFeatureEditing, showAllFeaturesInTiles, renderedFeatureGid } from '@/components/dataset/hooks/use-feature-editing';
import { DrawingToolbar } from '@/components/drawing/DrawingToolbar';
import { AttributeForm } from '@/components/drawing/AttributeForm';
import { useTileToken, useInvalidateTileTokens } from '@/hooks/use-tile-token';
import { isSessionRenewalPending, useTileAuthRecovery, useVisibleTileTokenRefresh } from '@/hooks/use-tile-auth-recovery';
import { useMapLayers, getSourceLayerName, previewSourceId } from '@/components/maps/hooks/use-map-layers';
import { computeLargeExtentView, isLargeExtent, isWorldSpanningExtent } from '@/lib/map-extent';
import { splitBbox, toFitBounds } from '@/lib/bbox';
import { findElevationColumn } from '@/lib/geo-utils';
import { useWebGLRecovery } from '@/hooks/use-webgl-recovery';
import { MAP_COLORS } from '@/lib/map-colors';
import { recordTypeCapabilities } from '@/lib/record-types';
import { toMapLibreAttribution } from '@/lib/attribution-safety';
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
import { Point } from 'maplibre-gl';
import type { LngLatBoundsLike, MapLibreEvent, MapMouseEvent, StyleSpecification } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { Feature, Geometry, GeoJsonProperties } from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';
import { motionDuration } from '@/lib/reduced-motion';
import { buildTileTransformRequest, isMvtSourceLayerConfigReady, refreshRasterTileSources } from '@/lib/tile-utils';
import { isRasterTileAuthError, isRefreshableRasterAuthError, logUnhandledMapError } from '@/lib/map-error-log';
import { reportTileTokenRemint } from '@/lib/report';
// Wires maplibre v6's worker URL. Side-effect import, kept out of
// main.tsx so map-vendor stays out of the eager entry graph.
import '@/lib/maplibre-worker';

import type { Viewer3DSource } from '@/components/dataset/viewer3d/viewer-support';

const EMPTY_FEATURES = { type: 'FeatureCollection' as const, features: [] };

const Dataset3DOverlay = lazy(() => import('@/components/dataset/viewer3d/Dataset3DOverlay'));

/** System columns excluded from the attribute form */
const SYSTEM_COLUMNS = new Set(['gid', 'geom', 'geom_4326']);

// Sources this component (and its hooks) add on top of the basemap. The
// basemap-switch transformStyle carries over only these: vector styles use
// provider source ids, so excluding just a source named `basemap` would stack
// the old vector basemap on top of the new one.
const APP_SOURCE_IDS = new Set([
  'raster-tile-source', // use-map-layers addRasterLayers
  'drawn-overlay', // use-map-layers addOverlaySource
  'bbox-source', // declarative <Source> below
]);

/** True for a source id owned by this app (incl. TerraDraw's `td-*` sources and the preview's vector source). */
function isAppSourceId(id: string, vectorSourceId: string | null): boolean {
  return APP_SOURCE_IDS.has(id) || id.startsWith('td-') || id === vectorSourceId;
}

/**
 * Whether the drawing store's session belongs to THIS map's dataset. Gates the
 * toolbar and the teardown of an inherited session on mount.
 * `targetDatasetId === null` (nothing adopted a target) is not a mismatch.
 */
function targetsDataset(targetDatasetId: string | null, datasetId: string | undefined): boolean {
  return targetDatasetId === null || targetDatasetId === (datasetId ?? null);
}

/**
 * True when a document-level keyboard shortcut should defer to the target's
 * native handling. A hidden drawing session keeps this map's document
 * listeners attached while the Data tab's table has focus.
 */
function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

/** Stands in for Save when this map can't save an unsaved edit, so the only way out is an explicit discard. */
function UnsavedEditNotice({ message, onDiscard, disabled }: { message: string; onDiscard: () => void; disabled: boolean }) {
  const { t } = useTranslation('dataset');
  return (
    <div role="alert" className="max-w-md rounded-lg shadow-lg border bg-background p-2 flex items-center gap-2">
      <p className="text-sm">{message}</p>
      <Button type="button" variant="destructive" size="sm" onClick={onDiscard} disabled={disabled}>
        {t('map.discardChangesAction')}
      </Button>
    </div>
  );
}

/**
 * Dataset detail map preview.
 *
 * Renders a single dataset's vector tiles with the active basemap, supports
 * drawing/editing features (with edit permission) and a fullscreen toggle.
 * `setTransformRequest` is applied imperatively in `onLoad` because
 * @vis.gl/react-maplibre v8 silently ignores the declarative prop.
 *
 * Declarative (<Source>/<Layer>) rather than the adapter core the
 * builder/viewer use: one dataset's tiles with light interaction needs no
 * incremental paint diffing.
 */

interface DatasetMapProps {
  bbox: [number, number, number, number] | null;
  tableName: string | null;
  geometryType: string | null;
  /** Generic created datasets accept any subtype. Switches draw-mode gating
   * and rendering to the GEOMETRY sentinel, for which use-map-layers installs
   * all-family renderers. */
  hasGenericGeometry?: boolean;
  datasetId?: string;
  columnInfo?: { name: string; type: string }[] | null;
  containerRef?: RefObject<HTMLDivElement | null>;
  canEdit?: boolean;
  recordType?: string;
  /** The 3D Tiles tileset or COPC point cloud to draw over the map, when the viewer can draw it. */
  viewer3d?: Viewer3DSource | null;
  rasterTileUrl?: string | null;
  isDem?: boolean;
  /** ISO timestamp or version string appended to tile URLs to bust browser cache after mutations */
  tileVersion?: string | null;
  onMapReady?: () => void;
  onTileError?: () => void;
  /** Callback for read-only (non-editing) feature clicks, receives the gid */
  onFeatureClick?: (gid: number) => void;
  /** The dataset's required credit line, shown in the attribution control. */
  attribution?: string | null;
  /** False while kept mounted but hidden (DatasetPage's isDataTabExpanded
   *  gate); its document-level Ctrl/Meta+Z and Escape handlers must then not
   *  act on geometry the user can't see, even from a target isEditableTarget
   *  misses (e.g. a focused button in the table). */
  shortcutsEnabled?: boolean;
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
  viewer3d = null,
  rasterTileUrl,
  isDem,
  tileVersion,
  onMapReady,
  onTileError,
  onFeatureClick,
  attribution,
  shortcutsEnabled = true,
}: DatasetMapProps) {
  const { t } = useTranslation(['dataset', 'common']);
  const mapLocale = useMapLocale();
  const { resolvedTheme } = useTheme();
  const { data: basemaps } = useBasemaps();
  const { data: mapDefaults } = useMapDefaults();
  const { data: tileConfig } = useTileConfig();
  const tileConfigReady = isMvtSourceLayerConfigReady(tileConfig);
  // Ref so the transformRequest installed once in handleLoad reads the current
  // tile config without re-registering.
  const tileConfigRef = useRef(tileConfig);
  tileConfigRef.current = tileConfig;
  const tileKind = recordTypeCapabilities(recordType).tileToken;
  const { data: rawTileToken } = useTileToken(tileKind ? datasetId : undefined);
  // Raster tokens are a separate payload (preformatted tile_url) consumed via
  // the rasterTileUrl prop; the hooks downstream expect the vector shape.
  const tileToken = rawTileToken?.kind === 'vector' ? rawTileToken : null;
  const vectorSourceId = tileKind === 'vector' && tableName ? previewSourceId(tableName) : null;
  const [userBasemapId, setUserBasemapId] = useState<string | null>(null);
  const themeBasemap = getThemeBasemap(basemaps ?? [], resolvedTheme);
  const activeBasemap = useMemo(
    () => userBasemapId
      ? findBasemapById(basemaps ?? [], userBasemapId) ?? themeBasemap
      : themeBasemap,
    [userBasemapId, basemaps, themeBasemap],
  );
  // Initial style only; later basemap changes are applied imperatively below.
  const initialBasemapStyle = useRef<string | import('maplibre-gl').StyleSpecification | null>(null);
  if (initialBasemapStyle.current === null) {
    const bm = themeBasemap;
    initialBasemapStyle.current = bm
      ? toMaplibreStyle(bm.url, bm.attribution)
      : toMaplibreStyle(
          resolvedTheme === 'dark' ? FALLBACK_BASEMAP_STYLE_URL_DARK : FALLBACK_BASEMAP_STYLE_URL,
        );
  }

  const hasBbox = bbox && bbox.length >= 4;
  const mapRef = useRef<MaplibreMap | null>(null);
  const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);
  const invalidateTileTokens = useInvalidateTileTokens();
  const { contextLost, reload } = useWebGLRecovery(mapRef, !!mapInstance, invalidateTileTokens);
  // Shared tile-auth recovery: a tile 401/403 kicks one throttled token
  // re-mint, and the refreshed token re-renders the <Source> with a fresh URL.
  // Suppressed mints are reported so a tab-return recovery still leaves a trace.
  const recoverTileAuth = useTileAuthRecovery(invalidateTileTokens, (trigger) =>
    reportTileTokenRemint('dataset-preview', trigger),
  );
  // A tab backgrounded past the 900 s sig boundary returns with stale tokens,
  // so resumed fetches 403 before the error handler can heal them; kick the
  // same throttled re-mint on the visible edge.
  useVisibleTileTokenRefresh(() => [rawTileToken], recoverTileAuth, () =>
    refreshRasterTileSources(mapRef.current),
  );
  // `url` tells a raster/DEM auth failure (unrecoverable) from a vector one
  // (re-mintable). `message` is declared because v6 narrowed the `error`
  // payload to `ErrorLike`, and a handler type with no property in common trips
  // TS's weak-type check; `status`/`url` are still populated at runtime.
  const tileAuthErrorHandlerRef = useRef<((e: { error?: { message?: string; status?: number; url?: string } }) => void) | null>(null);
  // Data-tiles-loaded signal like ViewerMap/BuilderMap: false while a camera
  // move is in flight, true once idle.
  const [tilesIdle, setTilesIdle] = useState(false);
  const tilesIdleMovestartHandlerRef = useRef<(() => void) | null>(null);
  const tilesIdleIdleHandlerRef = useRef<(() => void) | null>(null);

  // onMapReady / onTileError fire at most once per map mount, and the
  // imperatively-attached ``sourcedata``/``error`` listeners are removed on
  // teardown so a ``key={mapKey}`` remount can't stack listeners (which churned
  // setState and could freeze the tab when titiler is cold). Refs are reset
  // when handleLoad runs for a new map. The vector branch uses the same
  // machinery.
  const readyFiredRef = useRef(false);
  // Tracks a *confirmed* raster load (isSourceLoaded) vs a soft 204-only ready,
  // so a sparse-COG 204 doesn't permanently block the error/retry overlay.
  const readyConfirmedRef = useRef(false);
  const errorFiredRef = useRef(false);
  const tileListenersRef = useRef<{
    error?: (e: { error: { message?: string; status?: number } }) => void;
    sourcedata?: (e: { sourceId?: string; isSourceLoaded?: boolean }) => void;
  }>({});

  const elevationColumn = useMemo(
    () => geometryType?.toUpperCase().includes('POLYGON') ? findElevationColumn(columnInfo) : null,
    [geometryType, columnInfo],
  );

  // Generic datasets use the GEOMETRY sentinel for both drawing and rendering
  // (use-map-layers installs all-family renderers), so a point-only generic
  // sketch still renders a line drawn in the same visit. elevationColumn stays
  // keyed on the concrete display type: extrusion never applies to generic.
  const drawGeometryType = hasGenericGeometry ? 'GEOMETRY' : geometryType;

  const { addVectorLayers, addRasterLayers, addOverlaySource } = useMapLayers({
    datasetId,
    // The hook also adds the vector source after load, once the tile config
    // settles, so only a type with vector tiles hands it a table.
    tableName: tileKind === 'vector' ? tableName : null,
    geometryType: drawGeometryType,
    rasterTileUrl,
    isDem,
    bounds: bbox,
    tileVersion,
    tileToken,
    tileConfigCdnBaseUrl: tileConfig?.cdn_base_url ?? undefined,
    mvtSourceLayerPrefix: tileConfig?.mvt_source_layer_prefix,
    mvtSourceLayerReady: tileConfigReady,
    mapRef,
    elevationColumn,
    attribution,
  });

  const [isFullscreen, setIsFullscreen] = useState(false);
  const [pendingGeometry, setPendingGeometry] = useState<Geometry | null>(null);
  const [autoSavingGeometry, setAutoSavingGeometry] = useState<Geometry | null>(null);
  // A ref, because a finish event can land before the render that applies the
  // state above.
  const autoSaveInFlightRef = useRef<Geometry | null>(null);
  const [editingAttributes, setEditingAttributes] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  const discardActionRef = useRef<(() => void) | null>(null);

  const isDrawing = useDrawingStore((s) => s.isDrawing);
  const drawingTargetDatasetId = useDrawingStore((s) => s.targetDatasetId);
  const activeMode = useDrawingStore((s) => s.activeMode);
  const setDrawing = useDrawingStore((s) => s.setDrawing);
  const setMode = useDrawingStore((s) => s.setMode);
  const clearDrawing = useDrawingStore((s) => s.clearDrawing);
  const selectedFeature = useDrawingStore((s) => s.selectedFeature);
  const isEditDirty = useDrawingStore((s) => s.isEditDirty);
  const setHasUnsavedMapWork = useDrawingStore((s) => s.setHasUnsavedMapWork);
  const canEditRef = useRef(canEdit);
  canEditRef.current = canEdit;
  const sessionEpoch = useDrawingStore((s) => s.sessionEpoch);
  // Whether the session belongs to THIS map's dataset; a render before the
  // stale-session effect runs must not show controls for another dataset.
  const isOwnDrawingSession = isDrawing && targetsDataset(drawingTargetDatasetId, datasetId);
  // The tdId of a dirty selection already present at first render, i.e.
  // inherited rather than made in this instance. Read during render because
  // the mount effect runs after first paint, so a ref it set would show Save
  // for one paint. `undefined` = not yet computed, `null` = none orphaned.
  const orphanedSelectionTdIdRef = useRef<string | null | undefined>(undefined);
  if (orphanedSelectionTdIdRef.current === undefined) {
    const initial = useDrawingStore.getState();
    orphanedSelectionTdIdRef.current =
      initial.isEditDirty && initial.selectedFeature ? initial.selectedFeature.tdId : null;
  }
  const requestScopeRef = useRef({ datasetId, sessionEpoch });
  if (
    requestScopeRef.current.datasetId !== datasetId
    || requestScopeRef.current.sessionEpoch !== sessionEpoch
  ) {
    requestScopeRef.current = { datasetId, sessionEpoch };
  }

  const editableColumns = useMemo(
    () => (columnInfo ?? []).filter((c) => !SYSTEM_COLUMNS.has(c.name)),
    [columnInfo],
  );

  // Refs to break circular dependency: handleDrawFinish needs saveAndRefresh,
  // and onEditFinish needs setEditDirty — both come from hooks that need TerraDraw.
  const saveAndRefreshRef = useRef<
    (g: Geometry, p: Record<string, unknown>) => Promise<{ saved: boolean; refused?: boolean }>
  >(async () => ({ saved: false }));
  const editFinishRef = useRef<(tdId: string, feature: Feature) => void>(() => {});
  const stableEditFinish = useCallback((tdId: string, feature: Feature) => {
    editFinishRef.current(tdId, feature);
  }, []);
  // Same circular-dep break as onEditFinish above.
  const historyBaselineRef = useRef<() => void>(() => {});
  const stableHistoryBaseline = useCallback(() => {
    historyBaselineRef.current();
  }, []);
  // Same circular-dep break as above.
  const selectionLostRef = useRef<(id: string | number) => void>(() => {});
  const stableSelectionLost = useCallback((id: string | number) => {
    selectionLostRef.current(id);
  }, []);

  const handleDrawFinish = useCallback(
    (feature: Feature<Geometry, GeoJsonProperties>) => {
      const geom = feature.geometry;
      if (!geom) return;
      // A sketch that finishes while an automatic save is in flight is dropped,
      // so the held shape can't be replaced before that save settles.
      if (autoSaveInFlightRef.current) {
        toast.info(t('map.sketchStillSaving'));
        return;
      }
      // TerraDraw drops the shape once it finishes, so it stays unsaved work
      // until a create succeeds. Without edit rights the save would be
      // refused, so it waits for Discard instead of being sent. With no
      // attributes to ask for, it saves at once, and a refusal leaves it held.
      setPendingGeometry(geom);
      if (editableColumns.length > 0 || !canEdit) return;
      autoSaveInFlightRef.current = geom;
      setAutoSavingGeometry(geom);
      void saveAndRefreshRef.current(geom, {})
        .then(({ refused }) => {
          if (!refused) setPendingGeometry((current) => (current === geom ? null : current));
        })
        .finally(() => {
          if (autoSaveInFlightRef.current === geom) autoSaveInFlightRef.current = null;
          setAutoSavingGeometry((current) => (current === geom ? null : current));
        });
    },
    [canEdit, editableColumns, t],
  );

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
    resetHistory,
  } = useTerraDraw(mapInstance, handleDrawFinish, stableEditFinish, stableHistoryBaseline, stableSelectionLost);

  const hasSketchInProgress = canUndo && activeMode !== null && activeMode !== 'select';
  // A drag in progress has undoable changes before its finish marks the edit dirty.
  const hasUnsavedWork = (selectedFeature !== null && (isEditDirty || canUndo))
    || hasSketchInProgress
    || pendingGeometry !== null
    || editingAttributes;

  useEffect(() => {
    setHasUnsavedMapWork(hasUnsavedWork);
  }, [hasUnsavedWork, setHasUnsavedMapWork]);
  // The sketch, pending geometry and attribute editor all die with this
  // instance, so a stale true must not keep blocking navigation.
  useEffect(() => () => setHasUnsavedMapWork(false), [setHasUnsavedMapWork]);

  const {
    saveAndRefresh,
    performDeselect,
    handleSaveEdit,
    handleDeleteFeature,
    handleEditFinish,
    handleHistoryBaseline,
    handleSelectionLost,
    handleEditAttributeSubmit,
    selectFeatureFromMap,
    cleanupOverlayListener,
    resetOverlay,
    isFeatureMutationPending,
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
    resetHistory,
  });

  // Keep refs current for callbacks that break circular deps
  saveAndRefreshRef.current = saveAndRefresh;
  editFinishRef.current = handleEditFinish;
  historyBaselineRef.current = handleHistoryBaseline;
  selectionLostRef.current = handleSelectionLost;

  useEffect(() => {
    return () => { cleanupOverlayListener(); };
  }, [cleanupOverlayListener]);

  // Detach the imperatively-attached tile listeners on unmount so a
  // key={mapKey} remount can't stack them.
  useEffect(() => {
    return () => {
      const map = mapRef.current;
      if (map) {
        if (tileListenersRef.current.error) {
          map.off('error', tileListenersRef.current.error);
        }
        if (tileListenersRef.current.sourcedata) {
          map.off('sourcedata', tileListenersRef.current.sourcedata);
        }
        if (tilesIdleMovestartHandlerRef.current) {
          map.off('movestart', tilesIdleMovestartHandlerRef.current);
        }
        if (tilesIdleIdleHandlerRef.current) {
          map.off('idle', tilesIdleIdleHandlerRef.current);
        }
        if (tileAuthErrorHandlerRef.current) {
          map.off('error', tileAuthErrorHandlerRef.current);
        }
      }
      tileListenersRef.current = {};
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

  // Sync activeMode from store to Terra Draw. A finished sketch that can't be
  // edited (the map lost edit rights) or is being saved stops drawing input,
  // so a second sketch can't replace it; switching earlier would drop the
  // unfinished sketch.
  const holdsFinishedSketch = pendingGeometry !== null
    && (!canEdit || pendingGeometry === autoSavingGeometry);
  useEffect(() => {
    if (isReady && activeMode) {
      tdSetMode(holdsFinishedSketch ? 'static' : activeMode);
    }
  }, [isReady, activeMode, holdsFinishedSketch, tdSetMode]);

  // Canvas click rather than map.on('click'): TerraDraw's adapter intercepts
  // pointer events and prevents MapLibre click events from firing.
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
      const point = new Point(e.clientX - rect.left, e.clientY - rect.top);
      selectFeatureFromMap(map, point);
    };

    canvas.addEventListener('pointerdown', handlePointerDown, { capture: true });
    canvas.addEventListener('pointerup', handlePointerUp, { capture: true });
    return () => {
      canvas.removeEventListener('pointerdown', handlePointerDown, { capture: true } as EventListenerOptions);
      canvas.removeEventListener('pointerup', handlePointerUp, { capture: true } as EventListenerOptions);
    };
  }, [activeMode, mapInstance, selectFeatureFromMap]);

  useEffect(() => {
    const map = mapInstance;
    if (!map || !onFeatureClick || !tableName || !tileConfigReady) return;
    // Only active when NOT in drawing/select mode
    if (activeMode) return;

    const handleReadOnlyClick = (e: MapMouseEvent) => {
      const sourceLayer = getSourceLayerName(
        tableName,
        tileConfig?.mvt_source_layer_prefix,
      );
      const features = map.queryRenderedFeatures(e.point, {
        layers: map.getStyle().layers
          ?.filter((l) => (l as Record<string, unknown>)['source-layer'] === sourceLayer)
          .map((l) => l.id) ?? [],
      });
      if (features.length > 0) {
        const gid = renderedFeatureGid(features[0]);
        if (gid != null) onFeatureClick(Number(gid));
      }
    };
    map.on('click', handleReadOnlyClick);
    return () => { map.off('click', handleReadOnlyClick); };
  }, [activeMode, mapInstance, onFeatureClick, tableName, tileConfigReady, tileConfig?.mvt_source_layer_prefix]);

  useEffect(() => {
    if (!selectedFeature && !(canUndo && activeMode && activeMode !== 'select')) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // shortcutsEnabled is false while hidden (isDataTabExpanded); focusable
        // elements in that table (e.g. a button) aren't caught by
        // isEditableTarget below.
        if (!shortcutsEnabled) return;
        // AttributeTable's cell editor also uses Escape (cancel) without
        // stopping propagation; without this check it would also deselect or
        // open a discard dialog for a feature the user can't see.
        if (isEditableTarget(e.target)) return;
        // Discarding now would end the session under the write in flight.
        if (isFeatureMutationPending) return;
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
  }, [activeMode, canUndo, clear, isFeatureMutationPending, performDeselect, requestDiscardConfirmation, selectedFeature, shortcutsEnabled, tdSetMode]);

  useEffect(() => {
    if (!isDrawing) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        // shortcutsEnabled is false while hidden (isDataTabExpanded); focusable
        // elements in that table aren't caught by isEditableTarget below.
        if (!shortcutsEnabled) return;
        // Don't hijack the input's native undo while typing.
        if (isEditableTarget(e.target)) return;
        if (isFeatureMutationPending) return;
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
  }, [isDrawing, isFeatureMutationPending, shortcutsEnabled, undo]);

  useEffect(() => {
    const el = containerRef?.current;
    if (!el) return;
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    el.addEventListener('fullscreenchange', handler);
    return () => el.removeEventListener('fullscreenchange', handler);
  }, [containerRef]);

  const handleZoomToExtent = useCallback(() => {
    const map = mapRef.current;
    if (!map || !hasBbox) return;
    if (isLargeExtent(bbox!)) {
      const { center, zoom } = computeLargeExtentView(bbox!);
      // Instant under prefers-reduced-motion.
      map.flyTo({ center, zoom, duration: motionDuration(1000) });
    } else {
      // An antimeridian-crossing extent has east run past 180; MapLibre
      // normalizes it, whereas the alternative fits the complementary 340°.
      map.fitBounds(toFitBounds(bbox!), { padding: 60, duration: motionDuration(1000) });
    }
  }, [hasBbox, bbox]);

  const handleToggleFullscreen = useCallback(() => {
    if (!containerRef?.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen();
    } else {
      document.exitFullscreen();
    }
  }, [containerRef]);

  // Basemap switch (theme or user selection): a single imperative path whose
  // transformStyle preserves custom sources/layers.
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
          // Allowlist app-owned sources/layers; see APP_SOURCE_IDS.
          for (const [id, src] of Object.entries(_prev.sources || {})) {
            if (!isAppSourceId(id, vectorSourceId) || next.sources?.[id]) continue;
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
            // App-owned = a TerraDraw layer or a layer drawing from an
            // app-owned source; every basemap layer fails both checks.
            if (!layer.id.startsWith('td-') && !(src && isAppSourceId(src, vectorSourceId))) continue;
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
  }, [activeBasemap, vectorSourceId]);

  const [minx, miny, maxx, maxy] = hasBbox ? bbox : [0, 0, 0, 0];

  // A planar ring built from a `west > east` pair would draw the complementary
  // 340° rectangle. Split the extent at the seam and draw a MultiPolygon; an
  // extent that doesn't cross yields one ring.
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
                  type: 'MultiPolygon' as const,
                  coordinates: splitBbox([minx, miny, maxx, maxy]).map(([w, s, e, n]) => [
                    [
                      [w, s],
                      [e, s],
                      [e, n],
                      [w, n],
                      [w, s],
                    ],
                  ]),
                },
              },
            ],
          }
        : null,
    [hasBbox, minx, miny, maxx, maxy],
  );
  const showsWorldExtent = hasBbox && isWorldSpanningExtent(bbox);
  // Only when there's no vector/raster source of this dataset's own to
  // carry it (tileKind null: tiles3d/pointcloud's footprint-only preview) —
  // otherwise that source already shows it, and this would duplicate it.
  const bboxAttribution = tileKind === null ? toMapLibreAttribution(attribution) : null;

  const handleLoad = useCallback(
    (e: MapLibreEvent) => {
      const map = e.target;
      mapRef.current = map;
      setMapInstance(map);

      // MapLibre's compact attribution starts expanded and only folds on the
      // first drag; fold it now so it doesn't cover a narrow preview.
      const container = map.getContainer();
      if (container.clientWidth <= 640) {
        const attrib = container.querySelector('.maplibregl-ctrl-attrib');
        attrib?.classList.remove('maplibregl-compact-show');
        attrib?.removeAttribute('open');
      }

      // Absolutify URLs and attach the auth header for raster tile requests.
      // react-maplibre v8 ignores the transformRequest PROP after mount, so
      // each map wires it here in onLoad.
      map.setTransformRequest(buildTileTransformRequest({
        getTileConfig: () => tileConfigRef.current,
      }));

      // Suppress missing-image warnings from basemap sprites (e.g. circle-11)
      // with a transparent 1x1 fallback (knownImagesOnly: false keeps the
      // preview console clean).
      map.setMissingStyleImageResolver(makeStyleImageMissingResolver(map, { knownImagesOnly: false }));

      // data-tiles-loaded signal, re-armed on every camera move
      tilesIdleMovestartHandlerRef.current = () => setTilesIdle(false);
      tilesIdleIdleHandlerRef.current = () => setTilesIdle(true);
      map.on('movestart', tilesIdleMovestartHandlerRef.current);
      map.on('idle', tilesIdleIdleHandlerRef.current);

      // Fresh mount: detach any stale listeners and reset the fire-once guards.
      if (tileListenersRef.current.error) {
        map.off('error', tileListenersRef.current.error);
      }
      if (tileListenersRef.current.sourcedata) {
        map.off('sourcedata', tileListenersRef.current.sourcedata);
      }
      readyFiredRef.current = false;
      readyConfirmedRef.current = false;
      errorFiredRef.current = false;
      const tileStats = { total: 0, failed: 0 };

      // Fire heroState transitions at most once per mount so repeated
      // sourcedata/error events don't churn setState (freeze). `confirmed`
      // marks a real source load (isSourceLoaded); a 204-only ready is "soft":
      // it resolves the loading skeleton for a sparse remote COG but a later
      // error threshold can still override it.
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

      // Vector-tile 401/403: a stale sig kicks one throttled token re-mint, and
      // a dead session surfaces through the global signed-out handling via the
      // mint request. recoverTileAuth() returning false means a recent re-mint
      // didn't cure the error (revoked grant, expired embed token), so it falls
      // through to onTileError. Auth failures surface even after a confirmed
      // load because they break the whole tile surface.
      // A raster/DEM 401/403 is not cured by a fresh sig (raster auth rides the
      // Authorization header), so the re-mint would return true without
      // changing anything. Still kick it, since its apiFetch renews an expiring
      // JWT, but route a raster failure to the error path.
      tileAuthErrorHandlerRef.current = (e: { error?: { message?: string; status?: number; url?: string } }) => {
        const s = e.error?.status;
        if (s !== 401 && s !== 403) return;
        const reminting = recoverTileAuth();
        // A raster auth error counts as recovering while a session renewal is
        // in flight; its post-rotation reload retries the tiles.
        const recovering =
          reminting &&
          (!isRasterTileAuthError(e) ||
            (isRefreshableRasterAuthError(e) && isSessionRenewalPending()));
        if (!recovering && !errorFiredRef.current) {
          errorFiredRef.current = true;
          onTileError?.();
        }
      };
      map.on('error', tileAuthErrorHandlerRef.current);

      if (tileKind === 'raster') {
        addRasterLayers(map);

        const handleRasterError = (e: { error: { message?: string; status?: number } }) => {
          const status = (e.error as { status?: number })?.status;
          // HTTP 204 = tile present but empty: success for a sparse remote COG.
          // Don't count it toward the error threshold, and treat the source as
          // usable so heroState doesn't sit in 'loading'.
          if (status === 204) {
            tileStats.total++;
            fireReadyOnce(false);
            return;
          }
          // A 401/403 lost to the tab-return refresh race is not a broken
          // source: the post-rotation reload retries it, and this listener is
          // independent of the auth handler above, so without this check it
          // would latch the permanent error overlay the reload can't clear.
          if (status === 401 && isSessionRenewalPending()) return;
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
        tileListenersRef.current = {
          error: handleRasterError,
          sourcedata: handleRasterSourceData,
        };
      } else if (tileKind === 'vector') {
        addVectorLayers(map);
        addOverlaySource(map);

        // Mirror the raster machinery: a soft ready resolves immediately (a
        // bbox-only dataset has no tiles to confirm), sourcedata confirms a
        // real load, and repeated hard tile failures cross the same threshold
        // into onTileError. 4xx stays out of the count: 404 is an expected
        // no-data tile outside the extent, and 401/403 belong to the tile-auth
        // handler above.
        const handleVectorError = (e: { error: { message?: string; status?: number } }) => {
          const status = e.error?.status;
          if (status && status >= 400 && status < 500) return;
          if ((vectorSourceId && e.error?.message?.includes(vectorSourceId)) ||
              e.error?.message?.includes('Error: HTTP') ||
              (status && status >= 500)) {
            tileStats.failed++;
            tileStats.total++;
            if (tileStats.failed >= 3 ||
                (tileStats.total >= 4 && tileStats.failed / tileStats.total > 0.5)) {
              fireErrorOnce();
            }
          }
        };
        const handleVectorSourceData = (e: { sourceId?: string; isSourceLoaded?: boolean }) => {
          if (vectorSourceId && e.sourceId === vectorSourceId && e.isSourceLoaded) {
            tileStats.total++;
            fireReadyOnce(true);
          }
        };

        map.on('error', handleVectorError);
        map.on('sourcedata', handleVectorSourceData);
        tileListenersRef.current = {
          error: handleVectorError,
          sourcedata: handleVectorSourceData,
        };
        fireReadyOnce(false);
      } else {
        fireReadyOnce(false);
      }
    },
    [tileKind, vectorSourceId, addRasterLayers, addVectorLayers, addOverlaySource, onMapReady, onTileError, recoverTileAuth],
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
    // The save still in flight belongs to the session that just ended.
    autoSaveInFlightRef.current = null;
    setAutoSavingGeometry(null);
    setEditingAttributes(false);
    // The delete/discard confirmation dialogs reference a selectedFeature that
    // was just cleared; left open they would dangle (Delete is a no-op).
    setDeleteConfirmOpen(false);
    setDiscardConfirmOpen(false);
    discardActionRef.current = null;
    // A create in progress (saveAndRefresh) may have put a not-yet-committed
    // shape in the overlay ref/source; empty both, or it stays visible later.
    resetOverlay();
    clearDrawing();
  }, [clear, clearDrawing, performDeselect, resetOverlay, tdSetMode]);

  // lib/auth-cache-reset.ts only resets Zustand state; it can't reach Terra
  // Draw's drawn geometry, MapLibre's hidden-tile filters or this component's
  // dialog state (pendingGeometry/editingAttributes), which only
  // finishDrawingSession tears down. Run it whenever the session epoch moves
  // so the previous identity's sketch, hidden tiles and dialogs are gone.
  // Skipped on mount: running it then would reset a session someone is
  // resuming after a route change.
  const sessionEpochRef = useRef(sessionEpoch);
  useEffect(() => {
    if (sessionEpochRef.current === sessionEpoch) return;
    sessionEpochRef.current = sessionEpoch;
    finishDrawingSession();
  }, [sessionEpoch, finishDrawingSession]);

  // The drawing store is global but this component is remounted per dataset
  // (DatasetPage keys it on dataset id), so navigating away from an
  // in-progress edit with nothing dirty can land here with the store still
  // holding the previous dataset's session, even between two editable datasets
  // (no canEdit mismatch, no sessionEpoch bump). A map must not inherit
  // another dataset's session: end it so its mutation hooks, bound to this
  // dataset's id and table, never act on the old selection. A session of this
  // dataset that this map can't edit is left to the edit-rights effect below.
  const staleSessionCheckedRef = useRef(false);
  useEffect(() => {
    if (staleSessionCheckedRef.current) return;
    staleSessionCheckedRef.current = true;
    const state = useDrawingStore.getState();
    if (!state.isDrawing) return;
    if (!targetsDataset(state.targetDatasetId, datasetId)) {
      finishDrawingSession();
    } else if (canEdit && state.selectedFeature) {
      if (state.isEditDirty) {
        // A dirty selection is kept (see orphanedSelectionTdIdRef above) so
        // DatasetPage's unsaved-changes guard still warns. Its edited geometry
        // lives only in the TerraDraw instance that made it, so the toolbar
        // offers a discard in place of Save.
        return;
      }
      // Same route in, no map mounted in between, then back to this same
      // editable dataset: the session belongs here but this TerraDraw instance
      // never made the selection. performDeselect() drops it (and its
      // edit-dirty/undo state) and restores any tile filter hidden for its gid,
      // without touching isDrawing/activeMode/targetDatasetId.
      performDeselect();
    }
  }, [canEdit, datasetId, finishDrawingSession, performDeselect]);

  // Edit rights can go away mid-session: the editing flag is switched off,
  // or a refetch changes the user's permission. A clean session ends once
  // any feature write in flight has settled, since ending it first would
  // drop that write's result. One with unsaved work stays, with a discard
  // notice in place of the toolbar, so the unsaved-changes guard never
  // warns about an edit the page offers no way to resolve.
  useEffect(() => {
    if (canEdit || !isDrawing || hasUnsavedWork || isFeatureMutationPending) return;
    finishDrawingSession();
  }, [canEdit, isDrawing, hasUnsavedWork, isFeatureMutationPending, finishDrawingSession]);
  // A delete confirmed before rights were lost must not reappear if they return.
  useEffect(() => {
    if (!canEdit) setDeleteConfirmOpen(false);
  }, [canEdit]);

  const handleCloseDrawing = useCallback(() => {
    if (isFeatureMutationPending) return;
    const hasDirtyFeatureEdit = Boolean(useDrawingStore.getState().selectedFeature) &&
      useDrawingStore.getState().isEditDirty;
    const hasSketchInProgress = canUndo && activeMode !== null && activeMode !== 'select';

    if (hasDirtyFeatureEdit || hasSketchInProgress) {
      requestDiscardConfirmation(finishDrawingSession);
      return;
    }

    finishDrawingSession();
  }, [activeMode, canUndo, finishDrawingSession, isFeatureMutationPending, requestDiscardConfirmation]);

  const handleModeChange = useCallback(
    (nextMode: string) => {
      if (nextMode === activeMode || isFeatureMutationPending) return;

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
    [activeMode, canUndo, clear, isFeatureMutationPending, performDeselect, requestDiscardConfirmation, setMode],
  );

  const handleUndo = useCallback(() => {
    if (!isFeatureMutationPending) undo();
  }, [isFeatureMutationPending, undo]);

  const handleAttributeSubmit = useCallback(
    async (properties: Record<string, unknown>) => {
      if (pendingGeometry) {
        const submittedGeometry = pendingGeometry;
        const submittedScope = requestScopeRef.current;
        const { saved } = await saveAndRefresh(submittedGeometry, properties);
        if (saved && requestScopeRef.current === submittedScope) {
          setPendingGeometry((current) => current === submittedGeometry ? null : current);
        }
      }
    },
    [pendingGeometry, saveAndRefresh],
  );

  const handleAttributeCancel = useCallback(() => {
    setPendingGeometry(null);
  }, []);

  if (!hasBbox && !tableName && !viewer3d) {
    return (
      <div className="flex items-center justify-center h-[500px] bg-muted rounded-md text-muted-foreground text-sm">
        {t('page.noSpatialExtent')}
      </div>
    );
  }

  // Same seam handling as the zoom-to-extent path above.
  const bounds: LngLatBoundsLike | undefined = hasBbox
    ? toFitBounds([minx, miny, maxx, maxy])
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

  const cursor = isDrawing
    ? activeMode === 'select'
      ? 'pointer'
      : 'crosshair'
    : undefined;


  return (
    <div
      // The basemap thumbnail owns the bottom-left corner (12px inset + 64px
      // image + borders), so the attribution control stops short of it on a
      // phone-width map.
      className="relative h-full [&_.maplibregl-ctrl-bottom-right]:max-w-[calc(100%-5.5rem)]"
      role="region"
      aria-label={t('map.ariaLabel', { defaultValue: 'Dataset map' })}
      data-map-interactive={isDrawing ? 'true' : 'false'}
      data-testid="dataset-map-shell"
      // "Map fully rendered" signal: false while tiles load after a camera
      // move, true at idle.
      data-tiles-loaded={tilesIdle ? 'true' : 'false'}
    >
      <MapGL
        initialViewState={initialViewState}
        mapStyle={initialBasemapStyle.current ?? ''}
        style={{ width: '100%', height: '100%' }}
        cursor={cursor}
        locale={mapLocale}
        interactive
        scrollZoom={isFullscreen}
        onLoad={handleLoad}
        // Claim the wrapper's `error` fallback so a handled tile-auth 401/403
        // (re-minted in handleLoad) doesn't double-log a red AJAXError row.
        onError={logUnhandledMapError}
      >
        <NavigationControl position="top-right" />

        {viewer3d && mapInstance && datasetId && (
          <Suspense fallback={null}>
            <Dataset3DOverlay datasetId={datasetId} source={viewer3d} fitToData={!hasBbox} />
          </Suspense>
        )}

        {/* An extentless 3D dataset has no outline to hang the required credit line on. */}
        {!bboxGeojson && viewer3d && bboxAttribution && (
          <Source id="bbox-source" type="geojson" data={EMPTY_FEATURES} attribution={bboxAttribution}>
            {/* MapLibre lists a source's attribution only while a layer uses it. */}
            <Layer id="bbox-attribution" type="line" paint={{ 'line-opacity': 0 }} />
          </Source>
        )}

        {/* Bbox overlay for spatial context */}
        {bboxGeojson && (
          <Source id="bbox-source" type="geojson" data={bboxGeojson} attribution={bboxAttribution ?? undefined}>
            {/* Direct children: Source injects `source` into each, which a fragment would swallow. */}
            {!showsWorldExtent && (
              <Layer
                id="bbox-fill"
                type="fill"
                paint={{
                  'fill-color': MAP_COLORS.default.fill,
                  'fill-opacity': 0.1,
                }}
              />
            )}
            {!showsWorldExtent && (
              <Layer
                id="bbox-line"
                type="line"
                paint={{
                  'line-color': MAP_COLORS.default.fill,
                  'line-width': 2,
                  'line-dasharray': [2, 2],
                }}
              />
            )}
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

      {/* Drawing toolbar overlay. isOwnDrawingSession guards a session left
          by a DIFFERENT dataset (see the staleSessionCheckedRef effect
          above, which ends it). A map that can't edit shows only the
          discard notice, and only while there is unsaved work to resolve. */}
      {isOwnDrawingSession && (canEdit ? (
        <DrawingToolbar
          geometryType={drawGeometryType}
          onClose={handleCloseDrawing}
          onModeChange={handleModeChange}
          onSaveEdit={handleSaveEdit}
          onCancelEdit={handleDeselect}
          onEditAttributes={() => setEditingAttributes(true)}
          onDeleteFeature={() => setDeleteConfirmOpen(true)}
          onUndo={handleUndo}
          canUndo={canUndo}
          isMutating={isFeatureMutationPending}
          selectionNotice={selectedFeature != null && selectedFeature.tdId === orphanedSelectionTdIdRef.current ? (
            <UnsavedEditNotice
              message={t('map.editLostOnReloadNotice')}
              onDiscard={() => requestDiscardConfirmation(performDeselect)}
              disabled={isFeatureMutationPending}
            />
          ) : undefined}
        />
      ) : hasUnsavedWork && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10">
          <UnsavedEditNotice
            message={t('map.editAccessLostNotice')}
            onDiscard={() => requestDiscardConfirmation(finishDrawingSession)}
            disabled={isFeatureMutationPending}
          />
        </div>
      ))}

      {/* Attribute form dialog (new feature creation) */}
      <AttributeForm
        open={canEdit && pendingGeometry !== null && pendingGeometry !== autoSavingGeometry}
        onOpenChange={(open) => {
          if (!open) setPendingGeometry(null);
        }}
        columns={columnInfo ?? []}
        onSubmit={handleAttributeSubmit}
        onCancel={handleAttributeCancel}
      />

      {/* Attribute form dialog (edit existing feature) */}
      <AttributeForm
        open={canEdit && editingAttributes}
        onOpenChange={(open) => {
          if (!open) setEditingAttributes(false);
        }}
        columns={columnInfo ?? []}
        onSubmit={async (properties) => {
          // A stale result may belong to a different identity's own open
          // editor. A write refused after this map lost edit rights stays
          // open as unsaved work, to leave through the discard notice.
          const { applied, refused } = await handleEditAttributeSubmit(properties);
          if (applied && !(refused && !canEditRef.current)) setEditingAttributes(false);
        }}
        onCancel={() => setEditingAttributes(false)}
        initialValues={selectedFeature?.properties}
      />

      {/* Delete confirmation dialog */}
      <AlertDialog open={canEdit && deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('map.deleteFeatureTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('map.deleteFeatureDescription')}
              {selectedFeature?.gid != null && (
                <span className="block mt-1 text-xs text-muted-foreground">
                  {t('map.featureId', { id: selectedFeature.gid, defaultValue: 'Feature ID: {{id}}' })}
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
              {canEdit ? t('map.discardChangesDescription') : t('map.discardChangesAccessLostDescription')}
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
