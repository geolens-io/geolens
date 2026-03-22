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
import type { Feature } from 'geojson';
import { MAP_COLORS } from '@/lib/map-colors';

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
export function extractSingleGeometry(geometry: Record<string, unknown>): Record<string, unknown> {
  const type = geometry.type as string;
  const coords = geometry.coordinates as unknown[];
  if (type === 'MultiPoint' && Array.isArray(coords) && coords.length > 0) {
    return { type: 'Point', coordinates: coords[0] };
  }
  if (type === 'MultiLineString' && Array.isArray(coords) && coords.length > 0) {
    return { type: 'LineString', coordinates: coords[0] };
  }
  if (type === 'MultiPolygon' && Array.isArray(coords) && coords.length > 0) {
    return { type: 'Polygon', coordinates: coords[0] };
  }
  return geometry;
}

/**
 * Returns true if the geometry has multiple parts (e.g., MultiPolygon with 2+ polygons).
 * Single-part Multi* geometries (coordinates.length === 1) return false -- they are safe to edit.
 */
export function isMultiPartGeometry(geometry: Record<string, unknown>): boolean {
  const type = geometry.type as string;
  const coords = geometry.coordinates as unknown[];
  if (!Array.isArray(coords)) return false;
  if (type === 'MultiPoint' || type === 'MultiLineString' || type === 'MultiPolygon') {
    return coords.length > 1;
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
 * @returns setMode, stop, isReady, and feature manipulation methods
 */
export function useTerraDraw(
  map: MaplibreMap | null,
  onFinish: (feature: Feature) => void,
  onEditFinish: ((tdId: string, feature: Feature) => void) | null = null,
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
} {
  // Use refs to avoid stale closures in event listeners
  const onFinishRef = useRef(onFinish);
  onFinishRef.current = onFinish;

  const onEditFinishRef = useRef(onEditFinish);
  onEditFinishRef.current = onEditFinish;

  // Track the current Terra Draw instance
  const drawRef = useRef<TerraDraw | null>(null);

  // Undo history state
  const historyRef = useRef<GeoJSONStoreFeatures<GeoJSONStoreGeometries>[][]>([]);
  const isRestoringRef = useRef(false);
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
      modes: [
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
      ],
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
      } else if (
        context.action === 'dragFeature' ||
        context.action === 'dragCoordinate' ||
        context.action === 'dragCoordinateResize'
      ) {
        // Existing feature edited — pass to onEditFinish, keep on canvas
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
      if (isRestoringRef.current) return;

      const snapshot = draw.getSnapshot().filter(
        (f) => !['select', 'static'].includes(f.properties?.mode as string),
      );
      historyRef.current.push(snapshot);
      setCanUndo(historyRef.current.length > 1);
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
      draw.selectFeature(id);
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
    if (!draw?.enabled || historyRef.current.length <= 1) return;

    // Pop the current state
    historyRef.current.pop();

    // Get the previous state
    const prev = historyRef.current[historyRef.current.length - 1];

    isRestoringRef.current = true;
    draw.clear();
    if (prev && prev.length > 0) {
      draw.addFeatures(prev);
    }
    // Defer flag reset so any synchronous or microtask change events are still suppressed
    queueMicrotask(() => {
      isRestoringRef.current = false;
    });

    setCanUndo(historyRef.current.length > 1);
  }, [draw]);

  const clear = useCallback(() => {
    if (!draw?.enabled) return;
    draw.clear();
    historyRef.current = [];
    setCanUndo(false);
  }, [draw]);

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
  };
}
