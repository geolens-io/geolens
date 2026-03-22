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
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { useTileToken } from '@/hooks/use-tile-token';
import { getEnvConfig } from '@/lib/env';
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
import type { LngLatBoundsLike, MapLibreEvent, StyleSpecification } from 'maplibre-gl';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { Feature, Geometry, GeoJsonProperties } from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';

/** System columns excluded from the attribute form */
const SYSTEM_COLUMNS = new Set(['gid', 'geom', 'geom_4326']);

/** Empty GeoJSON FeatureCollection */
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

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
}

function getSourceLayerName(tableName: string): string {
  return `data.${tableName}`;
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
}: DatasetMapProps) {
  const { t } = useTranslation('dataset');
  const { resolvedTheme } = useTheme();
  const { data: basemaps } = useBasemaps();
  const { data: mapDefaults } = useMapDefaults();
  const { data: tileConfig } = useTileConfig();
  const { data: tileToken } = useTileToken(datasetId);
  const themeBasemap = getThemeBasemap(basemaps ?? [], resolvedTheme);
  const basemapStyle = themeBasemap
    ? toMaplibreStyle(themeBasemap.url)
    : toMaplibreStyle(
        resolvedTheme === 'dark'
          ? 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
          : 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
      );

  const hasBbox = bbox && bbox.length >= 4;
  const mapRef = useRef<MaplibreMap | null>(null);
  const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);
  const vectorLayersAdded = useRef(false);
  const rasterLayersAdded = useRef(false);

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
  useEffect(() => {
    const map = mapRef.current;
    if (!map || activeMode !== 'select') return;

    const handleMapClick = (e: maplibregl.MapMouseEvent) => {
      selectFeatureFromMap(map, e.point);
    };

    map.on('click', handleMapClick);
    return () => {
      map.off('click', handleMapClick);
    };
  }, [activeMode, mapInstance, selectFeatureFromMap]);

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
    const [bMinx, bMiny, bMaxx, bMaxy] = bbox!;
    const extentIsLarge = (bMaxx - bMinx > 90 || bMaxy - bMiny > 60);
    if (extentIsLarge) {
      const lonSpan = bMaxx - bMinx;
      const latSpan = bMaxy - bMiny;
      const zoomForLon = Math.log2(360 / Math.max(lonSpan, 1));
      const zoomForLat = Math.log2(170 / Math.max(latSpan, 1));
      const zoom = Math.max(1, Math.round(Math.min(zoomForLon, zoomForLat)));
      map.flyTo({
        center: [(bMinx + bMaxx) / 2, Math.max(-60, Math.min(60, (bMiny + bMaxy) / 2))],
        zoom,
      });
    } else {
      map.fitBounds([bMinx, bMiny, bMaxx, bMaxy], { padding: 60 });
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
    const newStyle = toMaplibreStyle(newBasemap.url);
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

  // Add vector tile source + layers imperatively after map loads
  const addVectorLayers = useCallback(
    (map: MaplibreMap) => {
      if (!tableName || vectorLayersAdded.current) return;
      if (map.getSource('vector-tile-source')) return;

      try {
        const sourceLayer = getSourceLayerName(tableName);
        const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url;

        map.addSource('vector-tile-source', {
          type: 'vector',
          tiles: [buildSignedTileUrl(tableName, tileToken ?? null, tileBaseUrl, tileVersion)],
          minzoom: 1,
          maxzoom: 22,
        });

        const isPoint = geometryType?.toUpperCase().includes('POINT') ?? false;
        const isLine = geometryType?.toUpperCase().includes('LINE') ?? false;

        if (isPoint) {
          map.addLayer({
            id: 'vector-points',
            type: 'circle',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            paint: {
              'circle-radius': 4,
              'circle-color': MAP_COLORS.default.fill,
              'circle-stroke-color': MAP_COLORS.default.stroke,
              'circle-stroke-width': 1,
            },
          });
        } else if (isLine) {
          map.addLayer({
            id: 'vector-lines',
            type: 'line',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            paint: {
              'line-color': MAP_COLORS.default.fill,
              'line-width': 2,
            },
          });
        } else {
          map.addLayer({
            id: 'vector-fill',
            type: 'fill',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            paint: {
              'fill-color': MAP_COLORS.default.fill,
              'fill-opacity': MAP_COLORS.default.fillOpacity,
            },
          });
          map.addLayer({
            id: 'vector-outline',
            type: 'line',
            source: 'vector-tile-source',
            'source-layer': sourceLayer,
            paint: {
              'line-color': MAP_COLORS.default.stroke,
              'line-width': 1,
            },
          });
        }

        vectorLayersAdded.current = true;
      } catch (e) {
        console.warn('addVectorLayers: failed to add sources/layers', e);
      }
    },
    [tableName, geometryType, tileConfig?.cdn_base_url, tileToken],
  );

  // Add raster XYZ tile source + layer imperatively after map loads
  const addRasterLayers = useCallback(
    (map: MaplibreMap) => {
      if (!rasterTileUrl || rasterLayersAdded.current) return;
      if (map.getSource('raster-tile-source')) return;
      try {
        map.addSource('raster-tile-source', {
          type: 'raster',
          tiles: [`${window.location.origin}${rasterTileUrl}`],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 22,
        });
        map.addLayer({
          id: 'raster-layer',
          type: 'raster',
          source: 'raster-tile-source',
          paint: { 'raster-opacity': 1 },
        });
        rasterLayersAdded.current = true;
      } catch (e) {
        console.warn('addRasterLayers: failed', e);
      }
    },
    [rasterTileUrl],
  );

  /** Add drawn-overlay GeoJSON source for instant feature visibility */
  const addOverlaySource = useCallback((map: MaplibreMap) => {
    if (map.getSource('drawn-overlay')) return;

    try {
      map.addSource('drawn-overlay', {
        type: 'geojson',
        data: EMPTY_FC,
      });

      // Point overlay
      map.addLayer({
        id: 'drawn-overlay-points',
        type: 'circle',
        source: 'drawn-overlay',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-radius': 6,
          'circle-color': MAP_COLORS.drawing.fill,
          'circle-stroke-color': MAP_COLORS.drawing.stroke,
          'circle-stroke-width': 2,
        },
      });

      // Line overlay
      map.addLayer({
        id: 'drawn-overlay-lines',
        type: 'line',
        source: 'drawn-overlay',
        filter: ['==', ['geometry-type'], 'LineString'],
        paint: {
          'line-color': MAP_COLORS.drawing.fill,
          'line-width': 3,
        },
      });

      // Polygon fill overlay
      map.addLayer({
        id: 'drawn-overlay-fill',
        type: 'fill',
        source: 'drawn-overlay',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: {
          'fill-color': MAP_COLORS.drawing.fill,
          'fill-opacity': MAP_COLORS.drawing.fillOpacity,
        },
      });

      // Polygon outline overlay
      map.addLayer({
        id: 'drawn-overlay-outline',
        type: 'line',
        source: 'drawn-overlay',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: {
          'line-color': MAP_COLORS.drawing.stroke,
          'line-width': 2,
        },
      });
    } catch (e) {
      console.warn('addOverlaySource: failed to add sources/layers', e);
    }
  }, []);

  // Clean up vector layers on unmount or prop change
  useEffect(() => {
    return () => {
      vectorLayersAdded.current = false;
    };
  }, [tableName]);

  // Clean up raster layers on unmount or tile URL change
  useEffect(() => {
    return () => {
      rasterLayersAdded.current = false;
    };
  }, [rasterTileUrl]);

  // Update tile URLs in-place when token refreshes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !tileToken || !tableName) return;
    const source = map.getSource('vector-tile-source');
    if (source && 'setTiles' in source) {
      const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url;
      const newUrl = buildSignedTileUrl(tableName, tileToken, tileBaseUrl, tileVersion);
      (source as maplibregl.VectorTileSource).setTiles([newUrl]);
    }
  }, [tileToken, tableName, tileConfig?.cdn_base_url, tileVersion]);

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

  // For large extents, use center+zoom instead of fitBounds because low-zoom
  // tiles (z0/z1) often fail with ST_AsMVT for complex geometries.
  // For smaller extents, fitBounds zooms in close enough that tiles work fine.
  const isLargeExtent = hasBbox && (maxx - minx > 90 || maxy - miny > 60);

  let initialViewState;
  if (!bounds) {
    initialViewState = {
      longitude: mapDefaults?.center_lng ?? 0,
      latitude: mapDefaults?.center_lat ?? 20,
      zoom: mapDefaults?.zoom ?? 2,
    };
  } else if (isLargeExtent) {
    // Compute zoom from extent span — clamp to minimum 1 to avoid z0 tile errors
    const lonSpan = maxx - minx;
    const latSpan = maxy - miny;
    const zoomForLon = Math.log2(360 / Math.max(lonSpan, 1));
    const zoomForLat = Math.log2(170 / Math.max(latSpan, 1));
    const zoom = Math.max(1, Math.round(Math.min(zoomForLon, zoomForLat)));
    initialViewState = {
      longitude: (minx + maxx) / 2,
      latitude: Math.max(-60, Math.min(60, (miny + maxy) / 2)),
      zoom,
    };
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
        attributionControl={false}
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
        onSubmit={handleEditAttributeSubmit}
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

