import type { FillExtrusionLayerSpecification, Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import {
  simplifyPaint,
  filterPaintForLayerType,
  finalizeLayer,
  applyMasterOpacity,
  getBuilderStyleConfig,
  syncLayerFilter,
  setLayerProperty,
  syncOwnedPaintProperties,
} from './shared';
import { MAP_COLORS } from '@/lib/map-colors';
import { ensureFillPatternImages, ensureTintedFillPatternImage } from './fill-pattern-images';
import { fillPatternTint } from '@/lib/fill-pattern-preview';
// builder-audit #338 DRY-06: extrusion min-zoom (14) and opacity cap (0.85) come from the
// single builder-defaults source of truth (shared with renderAs + backend mirror).
import { DEFAULT_EXTRUSION_MIN_ZOOM, DEFAULT_EXTRUSION_OPACITY_CAP } from './builder-defaults';

// Exported for the mixed adapter's fill/outline sublayers (ADAPT-03 reuse).
export const FILL_OWNED_PAINT_PROPERTIES = [
  'fill-color',
  'fill-opacity',
  'fill-outline-color',
  'fill-antialias',
  'fill-pattern',
  'fill-translate',
  'fill-translate-anchor',
] as const;
// fix(#1625): the outline is a line layer with no per-feature opacity of its own, so
// the master slider rides on `line-layer-opacity` here too — shared polygon edges
// are drawn once per polygon and double-darkened under `line-opacity`. Registered
// here because `syncOwnedPaintProperties` only reconciles keys in this set: an
// unregistered key is written once by addLayers and never updated again.
export const OUTLINE_OWNED_PAINT_PROPERTIES = ['line-color', 'line-width', 'line-layer-opacity'] as const;
// builder-audit #338 SPEC-11: 3D extrusion authoring is a DELIBERATE single-purpose subset
// (column height only). fill-extrusion-base is intentionally fixed to 0 and
// fill-extrusion-pattern / -translate / -translate-anchor are intentionally NOT authored;
// this is column-height extrusion, not a general fill-extrusion editor.
const EXTRUSION_OWNED_PAINT_PROPERTIES = [
  'fill-extrusion-height',
  'fill-extrusion-base',
  'fill-extrusion-color',
  'fill-extrusion-opacity',
  'fill-extrusion-vertical-gradient',
] as const;
type FillExtrusionHeight = NonNullable<FillExtrusionLayerSpecification['paint']>['fill-extrusion-height'];
type FillExtrusionColor = NonNullable<FillExtrusionLayerSpecification['paint']>['fill-extrusion-color'];

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function buildHeightExpression(heightColumn: string, heightScale: number): FillExtrusionHeight {
  const baseExpression = ['coalesce', ['to-number', ['get', heightColumn], 0], 0];
  return (heightScale === 1 ? baseExpression : ['*', baseExpression, heightScale]) as FillExtrusionHeight;
}

/**
 * fix(#910, codex P2): the colour the extrusion companion draws in.
 *
 * The companion has no pattern of its own (SPEC-11) and colours from `fill-color`,
 * which is absent while a pattern owns the fill — so it falls back to the stash, or
 * it silently reverts to default blue.
 *
 * Both inputs are untrusted. `style_config` is an open dict that gets serialized-size
 * validation only and `getBuilderStyleConfig` merely casts, so an API-authored or
 * imported layer can hold a number or object in `fillColorSaved`. MapLibre rejects a
 * non-string colour outright and `addLayers`'s catch then swallows it, leaving no 3D
 * companion at all — worse than the wrong colour. An EXPRESSION is valid here and has
 * to pass through, which is why paint takes string-or-array while the stash takes a
 * string: only a solid colour is ever stashable.
 */
function resolveExtrusionFillColor(
  rawPaint: Record<string, unknown>,
  builder: { fillColorSaved?: string },
): FillExtrusionColor {
  const painted = rawPaint['fill-color'];
  // The single cast lives here, after the check, replacing the two `as string`
  // assertions the call sites used to make on values that were never checked at all.
  if (typeof painted === 'string' || Array.isArray(painted)) return painted as FillExtrusionColor;
  return typeof builder.fillColorSaved === 'string'
    ? builder.fillColorSaved
    : MAP_COLORS.default.fill;
}

/**
 * fix(#914): swap a built-in `fill-pattern` for its tinted variant on the way into
 * MapLibre, so the pattern draws in the layer's fill colour instead of a fixed grey.
 * Returns a copy; `rawPaint` (and therefore saved paint, the wire format and
 * exported style.json) keeps the plain id.
 */
export function withTintedFillPattern(
  map: MaplibreMap,
  rawPaint: Record<string, unknown>,
  builder: { fillColorSaved?: string },
  paint: Record<string, unknown>,
): Record<string, unknown> {
  const id = paint['fill-pattern'];
  if (typeof id !== 'string') return paint;
  const tinted = ensureTintedFillPatternImage(map, id, fillPatternTint(rawPaint, builder));
  return tinted === id ? paint : { ...paint, 'fill-pattern': tinted };
}

function getExtrusionOptions(input: AdapterLayerInput) {
  const builder = getBuilderStyleConfig(input);
  const heightScale = finiteNumber(builder.heightScale) ?? 1;
  const extrusionMinZoom = finiteNumber(builder.extrusionMinZoom) ?? DEFAULT_EXTRUSION_MIN_ZOOM;
  const configuredOpacity = finiteNumber(builder.extrusionOpacity);
  return {
    heightScale,
    extrusionMinZoom,
    extrusionOpacity: configuredOpacity == null
      ? Math.min(input.opacity ?? 1, DEFAULT_EXTRUSION_OPACITY_CAP)
      : clamp(configuredOpacity, 0, 1),
  };
}

export const fillAdapter: LayerAdapter = {
  type: 'fill',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, sourceLayer, paint: rawPaint, layout, opacity, filter, visible } = input;
    const builder = getBuilderStyleConfig(input);
    ensureFillPatternImages(map);
    const outlineId = `${input.layerId}-outline`;
    const heightColumn = builder.heightColumn ?? (rawPaint['_height_column'] as string | undefined);
    const hasExpressions = Object.values(rawPaint).some(Array.isArray);
    try {
      const basePaint = hasExpressions ? simplifyPaint(rawPaint) : rawPaint;
      const fillPaint = filterPaintForLayerType(basePaint, 'fill');
      const strokeDisabled = builder.strokeDisabled ?? !!(rawPaint['_stroke-disabled']);
      const effectiveFillPaint: Record<string, unknown> = Object.keys(fillPaint).length
        ? { ...fillPaint }
        : {
            'fill-color': MAP_COLORS.default.fill,
            'fill-opacity': MAP_COLORS.default.fillOpacity,
          };
      // Suppress native 1px fill outline when stroke is disabled
      if (strokeDisabled) {
        effectiveFillPaint['fill-outline-color'] = MAP_COLORS.transparent;
      }
      const tintedFillPaint = withTintedFillPattern(map, rawPaint, builder, effectiveFillPaint);
      // BUG-01: honor input.visible at initial add so callers that don't
      // immediately follow up with syncVisibility (e.g. swapLayerOnMap for
      // render-mode switches, the raster re-add branch in
      // handleStyleConfigChange) still produce a layer in the correct visual
      // state. Without this, a hidden layer becomes inadvertently visible on
      // the map after re-add, which the user perceives as the eye toggle
      // being a no-op (the next click flips React state but the map was
      // already at the new visibility — no observable change).
      const initialLayout = visible === false
        ? { ...layout, visibility: 'none' as const }
        : layout;
      map.addLayer({
        id: layerId,
        type: 'fill',
        source: sourceId,
        ...(input.sourceType !== 'geojson' && { 'source-layer': sourceLayer }),
        paint: tintedFillPaint,
        layout: initialLayout,
      });
      finalizeLayer(map, layerId, rawPaint, 'fill', opacity ?? 1, filter, hasExpressions);

      const outlineColor =
        builder.outlineColor
        ?? (rawPaint['_outline-color'] as string | undefined)
        ?? (rawPaint['outline-color'] as string | undefined);
      const outlineWidth =
        builder.outlineWidth
        ?? (rawPaint['_outline-width'] as number | undefined)
        ?? (rawPaint['outline-width'] as number | undefined);
      map.addLayer({
        id: outlineId,
        type: 'line',
        source: sourceId,
        ...(input.sourceType !== 'geojson' && { 'source-layer': sourceLayer }),
        paint: {
          'line-color': (typeof outlineColor === 'string' ? outlineColor : null) ?? MAP_COLORS.default.stroke,
          'line-width': outlineWidth ?? 1,
        },
        ...(visible === false ? { layout: { visibility: 'none' as const } } : {}),
      });
      map.setPaintProperty(outlineId, 'line-layer-opacity', opacity ?? 1);
      // strokeDisabled hides the outline regardless of layer visibility.
      // When the layer is hidden we leave the outline hidden too (it cannot be
      // visible while its parent is none); when the layer is visible, we
      // restore the outline to follow the stroke-disabled rule.
      if (strokeDisabled) {
        map.setLayoutProperty(outlineId, 'visibility', 'none');
      }
      syncLayerFilter(map, outlineId, filter);

      // Companion fill-extrusion layer: only when a builder height column is set
      if (heightColumn) {
        const extrusionId = `${layerId}-extrusion`;
        const { heightScale, extrusionMinZoom, extrusionOpacity } = getExtrusionOptions(input);
        const fillColor = resolveExtrusionFillColor(rawPaint, builder);
        map.addLayer({
          id: extrusionId,
          type: 'fill-extrusion',
          source: sourceId,
          ...(input.sourceType !== 'geojson' && { 'source-layer': sourceLayer }),
          minzoom: extrusionMinZoom,
          paint: {
            'fill-extrusion-height': buildHeightExpression(heightColumn, heightScale),
            'fill-extrusion-base': 0,
            'fill-extrusion-color': fillColor,
            'fill-extrusion-opacity': extrusionOpacity,
            'fill-extrusion-vertical-gradient': true,
          },
        });
        syncLayerFilter(map, extrusionId, filter);
      }
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] addLayer failed for ${layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, opacity, filter } = input;
    const builder = getBuilderStyleConfig(input);
    ensureFillPatternImages(map);
    const outlineId = `${input.layerId}-outline`;
    if (map.getLayer(layerId)) {
      syncOwnedPaintProperties(map, layerId, withTintedFillPattern(map, rawPaint, builder, rawPaint), {
        geomType: 'fill',
        ownedProperties: FILL_OWNED_PAINT_PROPERTIES,
      });
      applyMasterOpacity(map, layerId, rawPaint, 'fill', opacity ?? 1);
      syncLayerFilter(map, layerId, filter);
      const strokeDisabled = builder.strokeDisabled ?? !!rawPaint['_stroke-disabled'];
      const outlineColor = (builder.outlineColor ?? rawPaint['_outline-color'] ?? rawPaint['outline-color']) as string | undefined;
      setLayerProperty(map, layerId, 'fill-outline-color', strokeDisabled ? MAP_COLORS.transparent : (outlineColor ?? MAP_COLORS.transparent));
    }
    // Sync outline companion layer
    if (map.getLayer(outlineId)) {
      const outlineStrokeDisabled = builder.strokeDisabled ?? !!rawPaint['_stroke-disabled'];
      const outlineColor = builder.outlineColor ?? rawPaint['_outline-color'] ?? rawPaint['outline-color'];
      const outlineWidth = builder.outlineWidth ?? rawPaint['_outline-width'] ?? rawPaint['outline-width'];
      syncOwnedPaintProperties(map, outlineId, {
        'line-color': typeof outlineColor === 'string' ? outlineColor : MAP_COLORS.default.stroke,
        'line-width': typeof outlineWidth === 'number' ? outlineWidth : 1,
        'line-layer-opacity': opacity ?? 1,
      }, {
        geomType: 'line',
        ownedProperties: OUTLINE_OWNED_PAINT_PROPERTIES,
      });
      map.setLayoutProperty(outlineId, 'visibility', outlineStrokeDisabled ? 'none' : 'visible');
      syncLayerFilter(map, outlineId, filter);
    }
    // Sync fill-extrusion companion layer
    const extrusionId = `${layerId}-extrusion`;
    if (map.getLayer(extrusionId)) {
      const heightColumn = builder.heightColumn ?? (rawPaint['_height_column'] as string | undefined);
      if (!heightColumn) {
        map.removeLayer(extrusionId);
        return;
      }
      const { heightScale, extrusionMinZoom, extrusionOpacity } = getExtrusionOptions(input);
      const fillColor = resolveExtrusionFillColor(rawPaint, builder);
      syncOwnedPaintProperties(map, extrusionId, {
        'fill-extrusion-height': buildHeightExpression(heightColumn, heightScale),
        'fill-extrusion-base': 0,
        'fill-extrusion-color': fillColor,
        'fill-extrusion-opacity': extrusionOpacity,
        'fill-extrusion-vertical-gradient': true,
      }, { ownedProperties: EXTRUSION_OWNED_PAINT_PROPERTIES });
      try {
        map.setLayerZoomRange(extrusionId, extrusionMinZoom, 22);
      } catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set extrusion zoom range:`, e); }
      syncLayerFilter(map, extrusionId, filter);
      // Workaround MapLibre v5 bug: setPaintProperty only applies every other call with terrain active
      try { map.triggerRepaint(); } catch (e) { if (import.meta.env.DEV) console.debug('[map-sync] triggerRepaint not available:', e); }
    }
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, visible, paint: rawPaint } = input;
    const builder = getBuilderStyleConfig(input);
    const outlineId = `${input.layerId}-outline`;
    const extrusionId = `${input.layerId}-extrusion`;
    const vis = visible ? 'visible' : 'none';
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, 'visibility', vis);
    }
    if (map.getLayer(outlineId)) {
      // BUG-036: the outline carries the stroke-disabled state as its layout
      // visibility (see addLayers/syncPaint). Restoring it on the raw `vis`
      // here resurrects a 1px outline that the user disabled (render-as 'Fill
      // only' sets strokeDisabled without zeroing outlineWidth). Gate it on the
      // same strokeDisabled flag syncPaint reads so the map stays in sync.
      const strokeDisabled = builder.strokeDisabled ?? !!rawPaint['_stroke-disabled'];
      map.setLayoutProperty(outlineId, 'visibility', visible && !strokeDisabled ? 'visible' : 'none');
    }
    if (map.getLayer(extrusionId)) {
      map.setLayoutProperty(extrusionId, 'visibility', vis);
    }
  },

  getLayerIds(layerId: string): string[] {
    return [layerId, `${layerId}-outline`, `${layerId}-extrusion`];
  },
};
