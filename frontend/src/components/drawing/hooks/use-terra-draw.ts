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

// fix(#1778): bound the undo ring so a long drag/freehand trace (one full
// store snapshot per `change` event, with no prior cap) cannot grow memory
// without limit for the duration of a single editing session.
const MAX_UNDO_HISTORY = 50;

/**
 * fix(round3 #1795): the single filtered-snapshot reader shared by the
 * `change` handler (ring entries) and the baseline capture points below —
 * 'select'/'static' entries are select-mode's own UI decoration (selection
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
 * fix(round3 #1795): whether a further undo step exists. Normally true
 * while the ring holds more than one entry; once only the ring's OLDEST
 * entry remains, a further step exists only if a true pre-edit baseline was
 * captured to fall back to — otherwise this is as far back as we can go.
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
export const GEOMETRY_TYPE_TO_MODES: Record<string, string[]> = {
  POINT: ['point'],
  MULTIPOINT: ['point'],
  LINESTRING: ['linestring'],
  MULTILINESTRING: ['linestring'],
  POLYGON: ['polygon', 'rectangle', 'circle', 'freehand'],
  MULTIPOLYGON: ['polygon', 'rectangle', 'circle', 'freehand'],
  // fix(#430 codex r11): empty created datasets carry the generic 'GEOMETRY'
  // sentinel (BA-32) and their column accepts ANY subtype, so expose every
  // mode — with no entry the toolbar rendered zero draw buttons and the first
  // feature could never be added. GEOMETRYCOLLECTION stays unmapped on
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
 * @param onHistoryBaseline - fix(round2 #1795): callback invoked when undo()
 *   pops the ring back down to its earliest recorded snapshot (canUndo
 *   transitions to false AS A RESULT OF an undo() call, not of a
 *   draw/setMode/clear/resetHistory reset). The editing layer uses this to
 *   clear isEditDirty — undoing all the way back means the displayed
 *   geometry is once again whatever was there when the ring started, so
 *   there is nothing pending to confirm away on Cancel/Done/mode-switch. A
 *   subsequent edit re-dirties normally via onEditFinish.
 * @param onSelectionLost - fix(round4 #1795): callback invoked when undo()
 *   restores a snapshot that no longer contains the feature that was
 *   selected before the undo (the rebuilt canvas has nothing left to
 *   re-select). The editing layer uses this to clear its own selection
 *   state, so it does not keep showing a feature as selected that Terra
 *   Draw no longer has.
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
  /** fix(round1 #1795): reset the undo ring without touching the canvas —
   *  callers own WHEN a pending edit's history should be discarded (save,
   *  cancel, deselection), not this hook (see resetHistory below). */
  resetHistory: () => void;
} {
  // Use refs to avoid stale closures in event listeners
  const onFinishRef = useRef(onFinish);
  onFinishRef.current = onFinish;

  const onEditFinishRef = useRef(onEditFinish);
  onEditFinishRef.current = onEditFinish;

  const onHistoryBaselineRef = useRef(onHistoryBaseline);
  onHistoryBaselineRef.current = onHistoryBaseline;

  const onSelectionLostRef = useRef(onSelectionLost);
  onSelectionLostRef.current = onSelectionLost;

  // Track the current Terra Draw instance
  const drawRef = useRef<TerraDraw | null>(null);

  // Undo history state
  const historyRef = useRef<GeoJSONStoreFeatures<GeoJSONStoreGeometries>[][]>([]);
  // fix(round3 #1795): the TRUE pre-edit snapshot, held OUTSIDE the bounded
  // ring so it survives eviction once a long drag pushes past
  // MAX_UNDO_HISTORY change events. null means "no baseline captured for
  // this session" — undo() must never report reaching baseline in that
  // case (see undo() below).
  const baselineRef = useRef<GeoJSONStoreFeatures<GeoJSONStoreGeometries>[] | null>(null);
  // fix(round4 #1795): the id of whatever feature the app most recently
  // selected via selectFeature() below. Restoring a snapshot in undo()
  // calls draw.clear() first, which drops Terra Draw's own select-mode
  // state and edit handles — this ref is how undo() knows what to
  // re-select afterward. null means "nothing selected for this session."
  const selectedFeatureIdRef = useRef<string | number | null>(null);
  const isRestoringRef = useRef(false);
  // fix(round5 #1795): on the real selection path, addFeatures() and
  // draw.selectFeature() synchronously emit `change` events — without this
  // guard, the ring already holds those seed snapshots by the time
  // selectFeature() below captures the session's baseline, so Undo reads as
  // available (and isEditDirty stays set) right after just selecting a
  // feature, before any actual edit happened.
  const isSeedingSessionRef = useRef(false);
  const [canUndo, setCanUndo] = useState(false);

  // State to trigger re-render when draw instance is ready
  const [draw, setDraw] = useState<TerraDraw | null>(null);

  // Initialize Terra Draw via useEffect tied to map instance.
  // React strict mode will: create td1 → stop td1 → create td2 (survives).
  useEffect(() => {
    if (!map) return;

    // Clean up any stale terra-draw sources/layers from previous mount
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

  // Register finish event listener
  useEffect(() => {
    if (!draw) return;

    const handler = (id: string | number, context: { action: string; mode: string }) => {
      const feature = draw.getSnapshotFeature(id);
      if (!feature) return;

      if (context.action === 'draw') {
        // New feature drawn — pass to onFinish and remove from canvas
        onFinishRef.current(feature as Feature);
        draw.removeFeatures([id]);
        // Reset undo history — the feature was committed, not an in-progress sketch
        historyRef.current = [];
        setCanUndo(false);
        // fix(round3 #1795): the committed feature's session is over — its
        // baseline snapshot is no longer meaningful.
        baselineRef.current = null;
        // fix(round4 #1795): a fresh-draw session has no "selected existing
        // feature" concept in the first place, but clear defensively.
        selectedFeatureIdRef.current = null;
      } else if (
        context.action === 'dragFeature' ||
        context.action === 'dragCoordinate' ||
        context.action === 'dragCoordinateResize'
      ) {
        // Existing feature edited — pass to onEditFinish, keep on canvas.
        // fix(round1 #1795): do NOT reset history here. A drag/vertex edit
        // only marks the edit dirty (use-feature-editing's handleEditFinish)
        // — it is not persisted until Save, so Undo must still be able to
        // revert it. History resets when the pending edit actually settles:
        // on save (handleSaveEdit) or on cancel/deselection (performDeselect),
        // both of which call the resetHistory() this hook now exposes.
        onEditFinishRef.current?.(String(id), feature as Feature);
      }
    };

    draw.on('finish', handler);

    return () => {
      draw.off('finish', handler);
    };
  }, [draw]);

  // Register change event listener for undo history
  useEffect(() => {
    if (!draw) return;

    const handler = () => {
      if (isRestoringRef.current || isSeedingSessionRef.current) return;

      const snapshot = filteredSnapshot(draw);
      historyRef.current.push(snapshot);
      // fix(#1778): drop the oldest entry once the ring exceeds its cap —
      // still enough undo depth for normal use, without unbounded growth.
      // fix(round3 #1795): the true pre-edit baseline lives in baselineRef,
      // OUTSIDE this ring, so eviction here never loses it.
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
      // Reset undo history on mode change to prevent cross-mode undo
      historyRef.current = [];
      setCanUndo(false);
      // fix(round3 #1795): a mode switch starts a fresh edit/draw session —
      // capture its baseline (the canvas as setMode left it) OUTSIDE the
      // bounded ring so it survives eviction later in this session.
      baselineRef.current = filteredSnapshot(draw);
      // fix(round4 #1795): a mode switch ends whatever selection preceded it.
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
      // terra-draw addFeatures expects GeoJSONStoreFeatures with properties.mode set
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
      // fix(round5 #1795): draw.selectFeature() synchronously emits its own
      // `change` event (select-mode entering/decorating the feature) —
      // suppress the ring listener for it so this seed event is never
      // recorded at all.
      isSeedingSessionRef.current = true;
      draw.selectFeature(id);
      isSeedingSessionRef.current = false;
      // fix(round3 #1795): selecting an existing feature starts its edit
      // session — capture the TRUE pre-edit snapshot now, outside the
      // bounded ring, so a long drag that later evicts the ring's oldest
      // entries can still undo all the way back to it.
      baselineRef.current = filteredSnapshot(draw);
      // fix(round4 #1795): remember what's selected so undo()'s restoring
      // draw.clear() (which drops Terra Draw's select-mode state and edit
      // handles) can re-select it afterward.
      selectedFeatureIdRef.current = id;
      // fix(round5 #1795): unconditionally clear the ring here too — on the
      // REAL selection path, the app calls addFeatures() (to load the
      // existing feature onto the canvas) BEFORE calling this selectFeature(),
      // and that addFeatures() call ALSO synchronously emits `change`,
      // outside the guard above since it runs before this function does.
      // Clearing here retroactively wipes out any such seed snapshots, so
      // an edit session starts with Undo disabled and an empty ring, not
      // "already dirty" from events that happened before anything was
      // actually edited.
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

    // Pop the current (top) state off the ring.
    historyRef.current.pop();

    // fix(round3 #1795): what we restore. If the ring still holds an
    // entry, that's the previous intermediate state, same as before. If
    // popping just emptied the ring, the ring's own oldest entry may
    // already have been evicted by the MAX_UNDO_HISTORY cap — so the
    // correct "one step further back" state is the TRUE pre-edit baseline
    // captured outside the ring, not an assumption that the ring's start
    // IS the baseline. Both the ring-internal step and this baseline
    // fallback flow through the SAME restoration below, so the re-select
    // fix(round4 #1795) just below covers both.
    const prev = historyRef.current.length > 0
      ? historyRef.current[historyRef.current.length - 1]
      : baselineRef.current;

    // fix(round4 #1795): preserve the selected feature's id BEFORE
    // draw.clear() below drops Terra Draw's select-mode state and edit
    // handles — otherwise the app's own selection store still shows the
    // feature selected, but Terra Draw no longer has it selected and the
    // user has to click the geometry again before dragging or editing
    // vertices.
    const selectedId = selectedFeatureIdRef.current;

    isRestoringRef.current = true;
    draw.clear();
    if (prev && prev.length > 0) {
      draw.addFeatures(prev);
    }
    // fix(round4 #1795): re-select only if that id is still present in the
    // restored features. Call draw.selectFeature() directly (not this
    // hook's own selectFeature() wrapper above) — that wrapper also
    // captures a NEW baseline and would overwrite the one this undo just
    // fell back to.
    if (selectedId != null && prev?.some((f) => f.id === selectedId)) {
      draw.selectFeature(selectedId);
    } else if (selectedId != null) {
      // The previously selected feature no longer exists in the restored
      // snapshot — clear our own record and tell the editing layer so its
      // selection store agrees with what Terra Draw actually has.
      selectedFeatureIdRef.current = null;
      onSelectionLostRef.current?.(selectedId);
    }
    // Defer flag reset so any synchronous or microtask change events are still suppressed
    queueMicrotask(() => {
      isRestoringRef.current = false;
    });

    // fix(round3 #1795): we are AT the true baseline only when the ring is
    // now empty AND a baseline was actually captured for this session — a
    // ring merely reaching length 0 with no captured baseline (or, before
    // this fix, just reaching length <= 1) is NOT a verified return to the
    // original pre-edit geometry, so it must never report baseline.
    const atTrueBaseline = historyRef.current.length === 0 && hasBaseline;
    setCanUndo(canUndoFrom(historyRef.current.length, hasBaseline));
    // fix(round2 #1795): signal a verified return to the true pre-edit
    // snapshot — the editing layer uses this to clear isEditDirty, since
    // the displayed geometry is once again whatever was there before this
    // edit session started.
    if (atTrueBaseline) {
      onHistoryBaselineRef.current?.();
    }
  }, [draw]);

  const clear = useCallback(() => {
    if (!draw?.enabled) return;
    draw.clear();
    historyRef.current = [];
    setCanUndo(false);
    // fix(round3 #1795): the session this baseline belonged to is over.
    baselineRef.current = null;
    // fix(round4 #1795): draw.clear() above already removed it from the canvas.
    selectedFeatureIdRef.current = null;
  }, [draw]);

  // fix(round1 #1795): the undo ring reset a caller asks for WITHOUT
  // touching the drawn canvas — clear() above removes features too, which
  // save/cancel/deselection do themselves (via removeFeatures) before or
  // instead of calling this.
  const resetHistory = useCallback(() => {
    historyRef.current = [];
    setCanUndo(false);
    // fix(round3 #1795): the session this baseline belonged to has settled
    // (save/cancel/deselection) — clear it alongside the ring.
    baselineRef.current = null;
    // fix(round4 #1795): the caller (save/cancel/deselection) already owns
    // clearing its own selection store — this just keeps our own record in
    // sync so a stale id never survives into a later session.
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
