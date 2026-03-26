import { useMemo, useEffect, useRef, useCallback, useState, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { Map as MapGL, Source, Layer, NavigationControl } from '@vis.gl/react-maplibre';
import { useTheme } from '@/components/theme-provider';
import { useBasemaps, useMapDefaults, useTileConfig } from '@/hooks/use-settings';
import { getThemeBasemap, toMaplibreStyle } from '@/lib/basemap-utils';
import { useDrawingStore } from '@/stores/drawing-store';
import { useTerraDraw } from '@/hooks/use-terra-draw';
import { useFeatureEditing, showAllFeaturesInTiles } from '@/hooks/use-feature-editing';
import { DrawingToolbar } from '@/components/drawing/DrawingToolbar';
import { AttributeForm } from '@/components/drawing/AttributeForm';
import { useTileToken } from '@/hooks/use-tile-token';
import { useMapLayers, getSourceLayerName } from '@/hooks/use-map-layers';
import { computeLargeExtentView, isLargeExtent } from '@/lib/map-extent';
import { useAuthStore } from '@/stores/auth-store';
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
import { cn } from '@/lib/utils';
import { Focus, Maximize2, Minimize2, PenLine } from 'lucide-react';
import { toast } from 'sonner';
import maplibregl from 'maplibre-gl';
import type { LngLatBoundsLike, MapLibreEvent, StyleSpecification } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { Feature, Geometry, GeoJsonProperties } from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';

/** System columns excluded from the attribute form */
const SYSTEM_COLUMNS = new Set(['gid', 'geom', 'geom_4326']);

interface DatasetMapProps {
  bbox: [number, number, number, number] | null;
  tableName: string | null;
  geometryType: string | null;
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

export function DatasetMap({
  bbox,
  tableName,
  geometryType,
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
  const { t } = useTranslation('dataset');
  const { resolvedTheme } = useTheme();
  const { data: basemaps } = useBasemaps();
  const { data: mapDefaults } = useMapDefaults();
  const { data: tileConfig } = useTileConfig();
  const { data: tileToken } = useTileToken(datasetId);
  const themeBasemap = getThemeBasemap(basemaps ?? [], resolvedTheme);
  const basemapStyle = themeBasemap
    ? toMaplibreStyle(themeBasemap.url, themeBasemap.attribution)
    : toMaplibreStyle(
        resolvedTheme === 'dark'
          ? 'https://tiles.openfreemap.org/styles/dark'
          : 'https://tiles.openfreemap.org/styles/positron',
      );

  const hasBbox = bbox && bbox.length >= 4;
  const mapRef = useRef<MaplibreMap | null>(null);
  const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);

  const { addVectorLayers, addRasterLayers, addOverlaySource } = useMapLayers({
    tableName,
    geometryType,
    rasterTileUrl,
    tileVersion,
    tileToken: tileToken ?? null,
    tileConfigCdnBaseUrl: tileConfig?.cdn_base_url,
    mapRef,
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
    reloadTiles,
    cleanupOverlayListener,
  } = useFeatureEditing({
    mapRef,
    datasetId,
    tableName,
    tileConfig,
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
      map.flyTo({ center, zoom });
    } else {
      map.fitBounds(bbox!, { padding: 60 });
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

  // --- Theme-aware basemap switching ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const newBasemap = getThemeBasemap(basemaps ?? [], resolvedTheme);
    if (!newBasemap) return;
    const newStyle = toMaplibreStyle(newBasemap.url, newBasemap.attribution);
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
  }, [resolvedTheme, basemaps]);

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

      if (recordType === 'raster_dataset' || recordType === 'vrt_dataset') {
        addRasterLayers(map);
        const tileStats = { total: 0, failed: 0 };
        map.on('error', (e: { error: { message: string; status?: number } }) => {
          if (e.error?.message?.includes('raster-tile-source') ||
              e.error?.message?.includes('Error: HTTP') ||
              (e.error as { status?: number })?.status === 404 ||
              (e.error as { status?: number })?.status === 500) {
            tileStats.failed++;
            tileStats.total++;
            if (tileStats.failed >= 3 ||
                (tileStats.total >= 4 && tileStats.failed / tileStats.total > 0.5)) {
              onTileError?.();
            }
          }
        });
        map.on('sourcedata', (e: { sourceId?: string; isSourceLoaded?: boolean }) => {
          if (e.sourceId === 'raster-tile-source' && e.isSourceLoaded) {
            tileStats.total++;
            onMapReady?.();
          }
        });
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
    };
  } else if (hasBbox && isLargeExtent(bbox!)) {
    const { center, zoom } = computeLargeExtentView(bbox!);
    initialViewState = { longitude: center[0], latitude: center[1], zoom };
  } else {
    initialViewState = { bounds, fitBoundsOptions: { padding: 60 } };
  }

  // Determine cursor: select mode -> pointer, drawing mode -> crosshair, else default
  const cursor = isDrawing
    ? activeMode === 'select'
      ? 'pointer'
      : 'crosshair'
    : undefined;

  const showNavControl = true;

  return (
    <div
      className="relative h-full"
      role="region"
      aria-label={t('map.ariaLabel', { defaultValue: 'Dataset map' })}
      data-map-interactive={isDrawing ? 'true' : 'false'}
      data-testid="dataset-map-shell"
    >
      <MapGL
        initialViewState={initialViewState}
        mapStyle={basemapStyle as string}
        style={{ width: '100%', height: '100%' }}
        cursor={cursor}
        interactive={showNavControl}
        scrollZoom={isFullscreen}
        onLoad={handleLoad}
      >
        {showNavControl && <NavigationControl position="top-right" />}

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

      {canEdit && !isDrawing && datasetId && tableName && geometryType && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="shadow-lg"
            onClick={() => setDrawing(datasetId, tableName, geometryType)}
            data-testid="dataset-map-edit-trigger"
            aria-label={t('actions.editGeometry')}
          >
            <PenLine className="h-4 w-4" />
            {t('actions.editGeometry')}
          </Button>
        </div>
      )}

      {/* Zoom-to-extent and fullscreen controls */}
      <div className={cn("absolute z-10 flex flex-col gap-1 right-[10px]", showNavControl ? "top-[120px]" : "top-3")}>
        {hasBbox && (
          <button
            type="button"
            onClick={handleZoomToExtent}
            className="bg-background border rounded shadow-sm p-1.5 hover:bg-accent"
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
            className="bg-background border rounded shadow-sm p-1.5 hover:bg-accent"
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
          geometryType={geometryType}
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
    </div>
  );
}

