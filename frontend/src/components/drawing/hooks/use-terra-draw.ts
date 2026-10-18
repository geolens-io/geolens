import { useEffect, useCallback, useRef, useState } from 'react';
import {
  TerraDraw,
  TerraDrawPointMode,
  TerraDrawLineStringMode,
  TerraDrawPolygonMode,
  TerraDrawRectangleMode,
  TerraDrawCircleMode,
  TerraDrawFreehandMode,
  TerraDrawSelectMode,
} from 'terra-draw';
import type { GeoJSONStoreFeatures, GeoJSONStoreGeometries } from 'terra-draw';
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { Feature, Geometry } from 'geojson';
import { MAP_COLORS } from '@/lib/map-colors';

// Bounds the undo ring: a long drag or freehand trace adds one full store
// snapshot per `change` event.
const MAX_UNDO_HISTORY = 50;

/**
 * Snapshot reader shared by the `change` handler and the baseline captures.
 * 'select'/'static' entries are select-mode's own decoration (selection
 * handles), not the geometry being edited.
 */
function filteredSnapshot(
  draw: TerraDraw,
): GeoJSONStoreFeatures<GeoJSONStoreGeometries>[] {
  return draw.getSnapshot().filter(
    (f) => !['select', 'static'].includes(f.properties?.mode as string),
  );
}

/**
 * Whether a further undo step exists: true while the ring holds more than one
 * entry; with only the OLDEST left, only if a pre-edit baseline was captured.
 */
function canUndoFrom(ringLength: number, hasBaseline: boolean): boolean {
  return ringLength > 1 || (ringLength === 1 && hasBaseline);
}

/**
 * Create fresh Terra Draw mode instances. Must be called per-mount because
 * TerraDraw internally registers modes on construction — reusing mode objects
 * across mounts (e.g. after error boundary recovery) causes
 * "Can not register unless mode is unregistered".
 */
function createTerraDrawModes() {
  return [
  new TerraDrawPointMode({
    styles: {
      pointColor: MAP_COLORS.default.fill,
      pointWidth: 6,
      pointOutlineColor: MAP_COLORS.default.stroke,
      pointOutlineWidth: 2,
    },
  }),
  new TerraDrawLineStringMode({
    snapping: { toCoordinate: true, toLine: true },
    styles: {
      lineStringColor: MAP_COLORS.default.fill,
      lineStringWidth: 2,
      closingPointColor: MAP_COLORS.closing.point,
      closingPointWidth: 6,
      closingPointOutlineColor: MAP_COLORS.closing.pointOutline,
      closingPointOutlineWidth: 2,
    },
  }),
  new TerraDrawPolygonMode({
    snapping: { toCoordinate: true, toLine: true },
    styles: {
      fillColor: MAP_COLORS.default.fill,
      fillOpacity: 0.15,
      outlineColor: MAP_COLORS.default.stroke,
      outlineWidth: 2,
      closingPointColor: MAP_COLORS.closing.point,
      closingPointWidth: 6,
      closingPointOutlineColor: MAP_COLORS.closing.pointOutline,
      closingPointOutlineWidth: 2,
    },
  }),
  new TerraDrawRectangleMode({
    styles: {
      fillColor: MAP_COLORS.default.fill,
      fillOpacity: 0.15,
      outlineColor: MAP_COLORS.default.stroke,
      outlineWidth: 2,
    },
  }),
  new TerraDrawCircleMode({
    styles: {
      fillColor: MAP_COLORS.default.fill,
      fillOpacity: 0.15,
      outlineColor: MAP_COLORS.default.stroke,
      outlineWidth: 2,
    },
  }),
  new TerraDrawFreehandMode({
    styles: {
      fillColor: MAP_COLORS.default.fill,
      fillOpacity: 0.15,
      outlineColor: MAP_COLORS.default.stroke,
      outlineWidth: 2,
    },
  }),
  new TerraDrawSelectMode({
    allowManualDeselection: true,
    flags: {
      point: {
        feature: { draggable: true },
      },
      linestring: {
        feature: {
          draggable: true,
          coordinates: { midpoints: true, draggable: true, deletable: true },
        },
      },
      polygon: {
        feature: {
          draggable: true,
          coordinates: { midpoints: true, draggable: true, deletable: true },
        },
      },
      freehand: {
        feature: {
          draggable: true,
          coordinates: { midpoints: true, draggable: true },
        },
      },
      circle: {
        feature: {
          draggable: true,
          coordinates: { midpoints: true, draggable: true },
        },
      },
      rectangle: {
        feature: {
          draggable: true,
          coordinates: { midpoints: true, draggable: true },
        },
      },
    },
    styles: {
      selectedPolygonColor: MAP_COLORS.selection.fill,
      selectedPolygonFillOpacity: MAP_COLORS.selection.fillOpacity,
      selectedPolygonOutlineColor: MAP_COLORS.selection.stroke,
      selectedPolygonOutlineWidth: 3,
      selectedLineStringColor: MAP_COLORS.selection.fill,
      selectedLineStringWidth: 3,
      selectedPointColor: MAP_COLORS.selection.fill,
      selectedPointWidth: 8,
      selectedPointOutlineColor: MAP_COLORS.selection.stroke,
      selectedPointOutlineWidth: 2,
      selectionPointColor: MAP_COLORS.handle.point,
      selectionPointWidth: 7,
      selectionPointOutlineColor: MAP_COLORS.handle.pointOutline,
      selectionPointOutlineWidth: 2,
      midPointColor: MAP_COLORS.handle.midpoint,
      midPointWidth: 5,
      midPointOutlineColor: MAP_COLORS.handle.midpointOutline,
      midPointOutlineWidth: 1,
    },
  }),
  ];
}

/**
 * Mapping from PostGIS/dataset geometry type to compatible Terra Draw modes.
 * Used by DrawingToolbar to filter visible mode buttons.
 */
const GEOMETRY_TYPE_TO_MODES: Record<string, string[]> = {
  POINT: ['point'],
  MULTIPOINT: ['point'],
  LINESTRING: ['linestring'],
  MULTILINESTRING: ['linestring'],
  POLYGON: ['polygon', 'rectangle', 'circle', 'freehand'],
  MULTIPOLYGON: ['polygon', 'rectangle', 'circle', 'freehand'],
  // Empty created datasets carry the generic 'GEOMETRY' sentinel and accept
  // ANY subtype, so expose every mode. GEOMETRYCOLLECTION stays unmapped on
  // purpose: a typed GC column rejects subtype inserts (GEOJSON_TYPE_MAP).
  GEOMETRY: ['point', 'linestring', 'polygon', 'rectangle', 'circle', 'freehand'],
};

/**
 * Returns the drawing modes available for a given geometry type.
 */
export function getAvailableModes(geometryType: string | null): string[] {
  if (!geometryType) return [];
  return GEOMETRY_TYPE_TO_MODES[geometryType.toUpperCase()] ?? [];
}

/**
 * Maps GeoJSON geometry type names to Terra Draw mode names.
 * Multi-geometries map to their single counterpart (decompose multi to single).
 */
export function getModeName(geometryType: string): string {
  const mapping: Record<string, string> = {
    Point: 'point',
    LineString: 'linestring',
    Polygon: 'polygon',
    MultiPoint: 'point',
    MultiLineString: 'linestring',
    MultiPolygon: 'polygon',
  };
  return mapping[geometryType] ?? 'polygon';
}

/**
 * Extract a single-part geometry from a potentially Multi-type geometry.
 * Terra Draw operates on single geometries, so we decompose Multi to single.
 */
export function extractSingleGeometry(geometry: Geometry): Geometry {
  if (geometry.type === 'MultiPoint' && geometry.coordinates.length > 0) {
    return { type: 'Point', coordinates: geometry.coordinates[0] };
  }
  if (geometry.type === 'MultiLineString' && geometry.coordinates.length > 0) {
    return { type: 'LineString', coordinates: geometry.coordinates[0] };
  }
  if (geometry.type === 'MultiPolygon' && geometry.coordinates.length > 0) {
    return { type: 'Polygon', coordinates: geometry.coordinates[0] };
  }
  return geometry;
}

/**
 * Returns true if the geometry has multiple parts (e.g., MultiPolygon with 2+ polygons).
 * Single-part Multi* geometries (coordinates.length === 1) return false -- they are safe to edit.
 */
export function isMultiPartGeometry(geometry: Geometry): boolean {
  if (geometry.type === 'MultiPoint' || geometry.type === 'MultiLineString' || geometry.type === 'MultiPolygon') {
    return Array.isArray(geometry.coordinates) && geometry.coordinates.length > 1;
  }
  return false;
}

/**
 * Core Terra Draw lifecycle hook.
 *
 * Initializes Terra Draw with all 6 drawing modes + select mode when a
 * MapLibre map instance is provided. Uses useEffect with [map] deps so
 * React strict mode's mount-unmount-remount cycle correctly creates a
 * fresh instance on the final mount.
 *
 * @param map - MapLibre map instance (null until map loads)
 * @param onFinish - callback invoked with the completed GeoJSON Feature after draw
 * @param onEditFinish - callback invoked with tdId and feature after edit (drag/vertex), null when not in editing context
 * @param onHistoryBaseline - callback invoked when undo() pops the ring back to
 *   its earliest snapshot (canUndo goes false because of an undo(), not a
 *   draw/setMode/clear/resetHistory reset). The editing layer clears
 *   isEditDirty then, since nothing is left to confirm away; a later edit
 *   re-dirties via onEditFinish.
 * @param onSelectionLost - callback invoked when undo() restores a snapshot
 *   without the previously selected feature, so the editing layer can clear
 *   its own selection state.
 * @returns setMode, stop, isReady, and feature manipulation methods
 */
export function useTerraDraw(
  map: MaplibreMap | null,
  onFinish: (feature: Feature) => void,
  onEditFinish: ((tdId: string, feature: Feature) => void) | null = null,
  onHistoryBaseline?: () => void,
  onSelectionLost?: (id: string | number) => void,
): {
  setMode: (mode: string) => void;
  stop: () => void;
  isReady: boolean;
  addFeatures: (features: Feature[]) => { id?: string | number; valid: boolean; reason?: string }[];
  removeFeatures: (ids: (string | number)[]) => void;
  selectFeature: (id: string) => void;
  getSnapshotFeature: (id: string | number) => Feature | undefined;
  clear: () => void;
  undo: () => void;
  canUndo: boolean;
  /** Reset the undo ring without touching the canvas; callers decide when a
   *  pending edit's history is discarded (save, cancel, deselection). */
  resetHistory: () => void;
} {
  // Refs avoid stale closures in event listeners.
  const onFinishRef = useRef(onFinish);
  onFinishRef.current = onFinish;

  const onEditFinishRef = useRef(onEditFinish);
  onEditFinishRef.current = onEditFinish;

  const onHistoryBaselineRef = useRef(onHistoryBaseline);
  onHistoryBaselineRef.current = onHistoryBaseline;

  const onSelectionLostRef = useRef(onSelectionLost);
  onSelectionLostRef.current = onSelectionLost;

  const drawRef = useRef<TerraDraw | null>(null);

  const historyRef = useRef<GeoJSONStoreFeatures<GeoJSONStoreGeometries>[][]>([]);
  // The TRUE pre-edit snapshot, held outside the bounded ring so it survives
  // eviction past MAX_UNDO_HISTORY events. null means no baseline was captured
  // this session, and undo() must never report reaching baseline then.
  const baselineRef = useRef<GeoJSONStoreFeatures<GeoJSONStoreGeometries>[] | null>(null);
  // The feature most recently selected via selectFeature(). undo() restores a
  // snapshot after draw.clear(), which drops select-mode state and edit
  // handles, and uses this to re-select afterward.
  const selectedFeatureIdRef = useRef<string | number | null>(null);
  const isRestoringRef = useRef(false);
  // addFeatures() and draw.selectFeature() synchronously emit `change` events;
  // without this guard the ring would already hold those seed snapshots when
  // selectFeature() captures the baseline, so Undo would read as available
  // (and isEditDirty stay set) before any actual edit.
  const isSeedingSessionRef = useRef(false);
  const [canUndo, setCanUndo] = useState(false);

  const [draw, setDraw] = useState<TerraDraw | null>(null);

  // Strict mode runs create td1 → stop td1 → create td2, and td2 survives.
  useEffect(() => {
    if (!map) return;

    // Remove sources and layers left by a previous mount.
    const style = map.getStyle();
    if (style?.layers) {
      for (const layer of style.layers) {
        if (layer.id.startsWith('td-')) {
          map.removeLayer(layer.id);
        }
      }
    }
    if (style?.sources) {
      for (const sourceId of Object.keys(style.sources)) {
        if (sourceId.startsWith('td-')) {
          map.removeSource(sourceId);
        }
      }
    }

    const td = new TerraDraw({
      adapter: new TerraDrawMapLibreGLAdapter({ map }),
      modes: createTerraDrawModes(),
    });

    td.start();
    drawRef.current = td;
    setDraw(td);

    return () => {
      try {
        td.stop();
      } catch {
        // Already stopped
      }
      drawRef.current = null;
      setDraw(null);
    };
  }, [map]);

  useEffect(() => {
    if (!draw) return;

    const handler = (id: string | number, context: { action: string; mode: string }) => {
      const feature = draw.getSnapshotFeature(id);
      if (!feature) return;

      if (context.action === 'draw') {
        onFinishRef.current(feature as Feature);
        draw.removeFeatures([id]);
        // The feature was committed, so the session's history and baseline no
        // longer apply.
        historyRef.current = [];
        setCanUndo(false);
        baselineRef.current = null;
        selectedFeatureIdRef.current = null;
      } else if (
        context.action === 'dragFeature' ||
        context.action === 'dragCoordinate' ||
        context.action === 'dragCoordinateResize'
      ) {
        // History is NOT reset here: a drag/vertex edit only marks the edit
        // dirty and persists on Save, so Undo must still revert it. History
        // resets via resetHistory() when the edit settles (save, cancel or
        // deselection).
        onEditFinishRef.current?.(String(id), feature as Feature);
      }
    };

    draw.on('finish', handler);

    return () => {
      draw.off('finish', handler);
    };
  }, [draw]);

  useEffect(() => {
    if (!draw) return;

    const handler = () => {
      if (isRestoringRef.current || isSeedingSessionRef.current) return;

      const snapshot = filteredSnapshot(draw);
      historyRef.current.push(snapshot);
      // Evicting the oldest entry never loses the true pre-edit baseline,
      // which lives in baselineRef outside the ring.
      if (historyRef.current.length > MAX_UNDO_HISTORY) {
        historyRef.current.shift();
      }
      setCanUndo(canUndoFrom(historyRef.current.length, baselineRef.current !== null));
    };

    draw.on('change', handler);
    return () => {
      draw.off('change', handler);
    };
  }, [draw]);

  const setMode = useCallback(
    (mode: string) => {
      if (!draw?.enabled) return;
      draw.setMode(mode);
      // A mode switch starts a fresh session: no cross-mode undo, a new
      // baseline (the canvas as setMode left it), and no selection.
      historyRef.current = [];
      setCanUndo(false);
      baselineRef.current = filteredSnapshot(draw);
      selectedFeatureIdRef.current = null;
    },
    [draw],
  );

  const stop = useCallback(() => {
    draw?.stop();
  }, [draw]);

  const addFeatures = useCallback(
    (features: Feature[]): { id?: string | number; valid: boolean; reason?: string }[] => {
      if (!draw?.enabled) return [];
      // terra-draw expects GeoJSONStoreFeatures with properties.mode set.
      return draw.addFeatures(features as Parameters<TerraDraw['addFeatures']>[0]);
    },
    [draw],
  );

  const removeFeatures = useCallback(
    (ids: (string | number)[]) => {
      if (!draw?.enabled) return;
      draw.removeFeatures(ids);
    },
    [draw],
  );

  const selectFeature = useCallback(
    (id: string) => {
      if (!draw?.enabled) return;
      // draw.selectFeature emits its own `change` event synchronously;
      // suppress the ring listener so that seed event is never recorded.
      isSeedingSessionRef.current = true;
      draw.selectFeature(id);
      isSeedingSessionRef.current = false;
      // Selecting an existing feature starts its edit session: capture the
      // TRUE pre-edit snapshot outside the ring so a long drag that evicts
      // old entries can still undo back to it.
      baselineRef.current = filteredSnapshot(draw);
      selectedFeatureIdRef.current = id;
      // The app calls addFeatures() before selectFeature(), and that also
      // emits `change` outside the guard above. Clearing the ring wipes those
      // seed snapshots so the session starts with Undo disabled.
      historyRef.current = [];
      setCanUndo(false);
    },
    [draw],
  );

  const getSnapshotFeature = useCallback(
    (id: string | number): Feature | undefined => {
      return draw?.getSnapshotFeature(id) as Feature | undefined;
    },
    [draw],
  );

  const undo = useCallback(() => {
    if (!draw?.enabled) return;
    const hasBaseline = baselineRef.current !== null;
    if (!canUndoFrom(historyRef.current.length, hasBaseline)) return;

    historyRef.current.pop();

    // With the ring empty, its oldest entry may already have been evicted by
    // the MAX_UNDO_HISTORY cap, so the step further back is the TRUE pre-edit
    // baseline, not the ring's start.
    const prev = historyRef.current.length > 0
      ? historyRef.current[historyRef.current.length - 1]
      : baselineRef.current;

    // Read before draw.clear() drops select-mode state; otherwise the app's
    // selection store would still show the feature selected while Terra Draw
    // has lost it, and the user would have to click it again before editing.
    const selectedId = selectedFeatureIdRef.current;

    isRestoringRef.current = true;
    draw.clear();
    if (prev && prev.length > 0) {
      draw.addFeatures(prev);
    }
    // Calls draw.selectFeature() directly, not the selectFeature() wrapper,
    // which would capture a NEW baseline over the one undo just fell back to.
    if (selectedId != null && prev?.some((f) => f.id === selectedId)) {
      draw.selectFeature(selectedId);
    } else if (selectedId != null) {
      // The restored snapshot lacks the selected feature; tell the editing
      // layer so its selection store matches Terra Draw.
      selectedFeatureIdRef.current = null;
      onSelectionLostRef.current?.(selectedId);
    }
    // Deferred so synchronous and microtask change events stay suppressed.
    queueMicrotask(() => {
      isRestoringRef.current = false;
    });

    // At the true baseline only when the ring is empty AND a baseline was
    // captured; an empty ring without one is not a verified return to the
    // pre-edit geometry.
    const atTrueBaseline = historyRef.current.length === 0 && hasBaseline;
    setCanUndo(canUndoFrom(historyRef.current.length, hasBaseline));
    if (atTrueBaseline) {
      onHistoryBaselineRef.current?.();
    }
  }, [draw]);

  const clear = useCallback(() => {
    if (!draw?.enabled) return;
    draw.clear();
    historyRef.current = [];
    setCanUndo(false);
    baselineRef.current = null;
    selectedFeatureIdRef.current = null;
  }, [draw]);

  // Unlike clear(), leaves the canvas alone: save, cancel and deselection
  // remove features themselves via removeFeatures.
  const resetHistory = useCallback(() => {
    historyRef.current = [];
    setCanUndo(false);
    baselineRef.current = null;
    // Keeps our record in step with the caller's selection store so a stale id
    // never survives into a later session.
    selectedFeatureIdRef.current = null;
  }, []);

  return {
    setMode,
    stop,
    isReady: !!draw?.enabled,
    addFeatures,
    removeFeatures,
    selectFeature,
    getSnapshotFeature,
    clear,
    undo,
    canUndo,
    resetHistory,
  };
}
