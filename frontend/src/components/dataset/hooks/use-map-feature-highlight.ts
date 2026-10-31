import { useCallback, useEffect, useRef, useState } from 'react';
import type { ExpressionSpecification, Map as MaplibreMap, PaddingOptions } from 'maplibre-gl';
import { geometryBounds, toFitBounds, type Bbox } from '@/lib/bbox';
import { MAP_COLORS } from '@/lib/map-colors';

/**
 * What a row click highlights: a fetched geometry, drawn from a source of its
 * own, or a feature already on the map, drawn from the layer's own source by
 * its feature id (tiles carry each row's `gid` as the id) and fitted to `bbox`.
 */
export type HighlightTarget =
  | { geometry: GeoJSON.Geometry | null }
  | { bbox: Bbox; source: string; sourceLayer?: string };

interface PaintedTarget {
  gid: number;
  target: HighlightTarget;
}

// The source and filters of the two highlight layers: the geometry's own
// source, or the layer's source narrowed to the feature id.
function highlightLayerParts({ gid, target }: PaintedTarget) {
  const source = 'source' in target
    ? { source: target.source, ...(target.sourceLayer ? { 'source-layer': target.sourceLayer } : {}) }
    : { source: HIGHLIGHT_SOURCE };
  const points: ExpressionSpecification = ['in', ['geometry-type'], ['literal', ['Point', 'MultiPoint']]];
  const byId: ExpressionSpecification[] = 'source' in target ? [['==', ['id'], gid]] : [];
  const line: ExpressionSpecification = ['all', ...byId, ['!', points]];
  const point: ExpressionSpecification = ['all', ...byId, points];
  return { source, line, point };
}

// Own source and layer ids, cleared on deactivation, reset-key change, and
// unmount: never the ephemeral preview's overlay, which has its own lifecycle
// and owner.
const HIGHLIGHT_SOURCE = 'attribute-table-highlight';
const HIGHLIGHT_LINE_LAYER = 'attribute-table-highlight-line';
const HIGHLIGHT_POINT_LAYER = 'attribute-table-highlight-point';

// A point, or a feature about a metre across, fits at street level rather
// than the deepest zoom.
const TINY_SPAN_DEGREES = 1e-5;
function fitMaxZoom([west, south, east, north]: Bbox): number {
  return Math.abs(east - west) < TINY_SPAN_DEGREES && Math.abs(north - south) < TINY_SPAN_DEGREES ? 16 : 18;
}

// A parsed style accepts mutations even while its sources are still loading,
// which isStyleLoaded() alone does not report.
function styleReady(map: MaplibreMap): boolean {
  return map.isStyleLoaded() || map.getStyle() !== undefined;
}

interface UseMapFeatureHighlightOptions {
  mapRef: React.RefObject<MaplibreMap | null>;
  /** Highlight state is kept only while active; it clears when this turns false. */
  active: boolean;
  /** A new key (the table's layer) clears the highlight and the selection. */
  resetKey: string;
  /** Resolves what to highlight for a feature id; omitted, or resolving null, a row click does nothing. */
  loadFeature?: (gid: number) => Promise<HighlightTarget | null>;
  /** Padding for the fit, read at fit time so it follows the table's height. */
  getFitPadding: () => number | PaddingOptions;
}

/**
 * Highlights one feature on the map by id, fits the camera to it, and tracks
 * which feature that is so a table can mark its row selected.
 */
export function useMapFeatureHighlight({
  mapRef,
  active,
  resetKey,
  loadFeature,
  getFitPadding,
}: UseMapFeatureHighlightOptions) {
  const getFitPaddingRef = useRef(getFitPadding);
  getFitPaddingRef.current = getFitPadding;

  const clearHighlight = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const id of [HIGHLIGHT_LINE_LAYER, HIGHLIGHT_POINT_LAYER] as const) {
      if (map.getLayer(id)) map.removeLayer(id);
    }
    if (map.getSource(HIGHLIGHT_SOURCE)) map.removeSource(HIGHLIGHT_SOURCE);
  }, [mapRef]);

  // The feature the highlight currently paints, kept so a style replacement
  // can repaint it: a style.load drops every imperatively added source/layer,
  // and the analysis mask re-adds its overlay the same way.
  const highlightFeatureRef = useRef<PaintedTarget | null>(null);

  // Re-add the highlight layers (and the geometry's own source) for a
  // feature, with no fit — the row-click path adds its fit after painting.
  // A layer source that a style swap has not re-added yet paints nothing.
  const paintHighlight = useCallback(
    (painted: PaintedTarget) => {
      const map = mapRef.current;
      if (!map || map.getLayer(HIGHLIGHT_LINE_LAYER)) return;
      const { target } = painted;
      if ('source' in target) {
        if (!map.getSource(target.source)) return;
      } else {
        if (map.getSource(HIGHLIGHT_SOURCE)) return;
        if (!target.geometry) return;
        map.addSource(HIGHLIGHT_SOURCE, {
          type: 'geojson',
          data: { type: 'Feature', geometry: target.geometry, properties: {} },
        });
      }
      const parts = highlightLayerParts(painted);
      map.addLayer({
        id: HIGHLIGHT_LINE_LAYER,
        type: 'line',
        ...parts.source,
        filter: parts.line,
        paint: {
          'line-color': MAP_COLORS.selection.stroke,
          'line-width': 3,
        },
      });
      map.addLayer({
        id: HIGHLIGHT_POINT_LAYER,
        type: 'circle',
        ...parts.source,
        filter: parts.point,
        paint: {
          'circle-radius': 8,
          'circle-color': MAP_COLORS.selection.fill,
          'circle-stroke-color': MAP_COLORS.selection.stroke,
          'circle-stroke-width': 2,
        },
      });
    },
    [mapRef],
  );

  // Monotonic token for the row-click request: bumped at every click start
  // below, and again in the cleanup (layer change and unmount), so neither an
  // older click on the same layer nor a response from the previous layer can
  // repaint the map.
  const rowRequestSeqRef = useRef(0);
  const pendingRowPaintCleanupRef = useRef<(() => void) | null>(null);

  // Invalidates any in-flight row request and a paint waiting on a style.
  const cancelPending = useCallback(() => {
    rowRequestSeqRef.current += 1;
    pendingRowPaintCleanupRef.current?.();
    pendingRowPaintCleanupRef.current = null;
  }, []);

  const reset = useCallback(() => {
    cancelPending();
    highlightFeatureRef.current = null;
    clearHighlight();
  }, [cancelPending, clearHighlight]);

  // Clear on deactivation, on key change, and on unmount (the cleanup of the
  // previous effect run), so a replaced table never leaves the previous
  // layer's highlight on the map.
  useEffect(() => {
    if (!active) return;
    return reset;
  }, [active, resetKey, reset]);

  // A style replacement repaints the kept feature's highlight, exactly as long
  // as it can come back: the subscription ends with the deactivation, the key
  // change, and the unmount, whose cleanup above drops the kept feature, so
  // nothing repaints after either. Redraw only — never a fit, never a camera
  // move; the stale-request token still rules any in-flight row response.
  // Keyed on the map instance, which can be replaced under the stable ref (a
  // Retry after a crash builds a new map).
  const map = mapRef.current;
  useEffect(() => {
    if (!active || !map) return;
    const repaint = () => {
      const feature = highlightFeatureRef.current;
      if (feature) paintHighlight(feature);
    };
    map.on('style.load', repaint);
    if (styleReady(map)) repaint();
    return () => {
      map.off('style.load', repaint);
    };
  }, [active, map, paintHighlight]);

  // The selected row mirrors the map highlight: set where the highlight
  // paints (a click without usable geometry leaves it), cleared when the key
  // changes and with the table itself.
  const [selectedGid, setSelectedGid] = useState<number | null>(null);
  const [selectionScope, setSelectionScope] = useState(resetKey);
  if (selectionScope !== resetKey) {
    setSelectionScope(resetKey);
    setSelectedGid(null);
  }

  // Highlight and fit a feature (a table row click), from `resolved` when the
  // caller already knows the target, else through `loadFeature`.
  const highlightFeature = useCallback(
    async (gid: number, resolved?: HighlightTarget | null) => {
      if (resolved === undefined && !loadFeature) return;
      cancelPending();
      const seq = rowRequestSeqRef.current;
      let target = resolved ?? null;
      if (resolved === undefined) {
        try {
          target = await loadFeature!(gid);
        } catch {
          // A deleted row (404) or a lost request: leave the table usable and
          // the map untouched.
          return;
        }
      }
      if (seq !== rowRequestSeqRef.current || !target) return;
      const map = mapRef.current;
      if (!map) return;
      // Bounds before paint: without usable geometry the map stays exactly as
      // it was — the previous highlight included.
      const bbox = 'source' in target ? target.bbox : geometryBounds(target.geometry);
      if (!bbox) return;
      const painted = { gid, target };
      const paintAndFit = () => {
        if (seq !== rowRequestSeqRef.current || mapRef.current !== map) return;
        pendingRowPaintCleanupRef.current = null;
        try {
          setSelectedGid(gid);
          clearHighlight();
          highlightFeatureRef.current = painted;
          paintHighlight(painted);
          map.fitBounds(toFitBounds(bbox), { padding: getFitPaddingRef.current(), maxZoom: fitMaxZoom(bbox) });
        } catch {
          // Style changes or out-of-range coordinates leave the table usable.
        }
      };
      if (styleReady(map)) paintAndFit();
      else {
        pendingRowPaintCleanupRef.current = () => map.off('style.load', paintAndFit);
        map.once('style.load', paintAndFit);
      }
    },
    [loadFeature, mapRef, cancelPending, clearHighlight, paintHighlight],
  );

  // Mark a feature selected without moving the camera or painting (a map
  // click, which opens its own popup). Drops an older row highlight and any
  // in-flight row request so they cannot contradict the selection.
  const selectFeature = useCallback(
    (gid: number) => {
      reset();
      setSelectedGid(gid);
    },
    [reset],
  );

  return { selectedGid, highlightFeature, selectFeature };
}
