import type { FillExtrusionLayerSpecification } from 'maplibre-gl';
import type { StyleConfig } from '@/types/api';
import type { AdapterLayerInput, ImageSpec, LayerAdapter, LayerDrawing, LayerSpec } from './types';
import {
  simplifyPaint,
  filterPaintForLayerType,
  filterSpec,
  getBuilderStyleConfig,
  getFeatureOpacity,
  sourceLayerSpec,
} from './shared';
import { MAP_COLORS } from '@/lib/map-colors';
import { FILL_PATTERN_IMAGES, tintedFillPattern } from './fill-pattern-images';
import { fillPatternTint } from '@/lib/fill-pattern-preview';
import { addDescribedLayer, writeDescribedLayer, writeDescribedVisibility } from '../layer-writer';
// builder-audit #338 DRY-06: extrusion min-zoom (14) and opacity cap (0.85) come from the
// single builder-defaults source of truth (shared with renderAs + backend mirror).
import { DEFAULT_EXTRUSION_MIN_ZOOM, DEFAULT_EXTRUSION_OPACITY_CAP, FULL_ZOOM_RANGE } from './builder-defaults';

// Exported for the mixed adapter's fill and outline sublayers. The master opacity
// slider rides on `fill-layer-opacity`, so a write keeps it in step too.
export const FILL_OWNED_PAINT_PROPERTIES = [
  'fill-color',
  'fill-opacity',
  'fill-outline-color',
  'fill-antialias',
  'fill-pattern',
  'fill-translate',
  'fill-translate-anchor',
  'fill-layer-opacity',
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
export const EXTRUSION_OWNED_PAINT_PROPERTIES = [
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
 * The paint with a built-in `fill-pattern` swapped for its variant in the layer's
 * fill colour, and the image that variant needs, so the pattern does not draw in
 * the fixed grey. Saved paint keeps the plain id.
 */
export function tintFillPattern(
  paint: Record<string, unknown>,
  rawPaint: Record<string, unknown>,
  builder: { fillColorSaved?: string },
): { paint: Record<string, unknown>; images: ImageSpec[] } {
  const id = paint['fill-pattern'];
  const tinted = typeof id === 'string' ? tintedFillPattern(id, fillPatternTint(rawPaint, builder)) : null;
  return tinted ? { paint: { ...paint, 'fill-pattern': tinted.id }, images: [tinted] } : { paint, images: [] };
}

/** The column a polygon layer extrudes by: the builder's, else the legacy paint key. */
export function resolveHeightColumn(
  builder: { heightColumn?: string },
  paint: Record<string, unknown>,
): string | undefined {
  const column = builder.heightColumn ?? paint['_height_column'];
  return typeof column === 'string' && column ? column : undefined;
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

/** The fill paint the adapter adds: the stored fill keys, or the default fill when none are stored. */
export function resolveFillPaint(paint: Record<string, unknown>): Record<string, unknown> {
  const fillPaint = filterPaintForLayerType(paint, 'fill');
  return Object.keys(fillPaint).length > 0
    ? fillPaint
    : { 'fill-color': MAP_COLORS.default.fill, 'fill-opacity': MAP_COLORS.default.fillOpacity };
}

export interface PolygonStroke {
  disabled: boolean;
  /** The outline colour the style sets, if any. */
  authoredColor: string | undefined;
  /** The colour the outline layer draws: the authored colour, else the default stroke. */
  color: string;
  width: number;
}

/**
 * The outline a polygon layer draws with its line companion. Builder state wins
 * over the paint mirrors, so an explicit `strokeDisabled: false` beats a stale
 * `_stroke-disabled`.
 */
export function resolvePolygonStroke(
  paint: Record<string, unknown>,
  builder: NonNullable<StyleConfig['builder']>,
): PolygonStroke {
  const color = builder.outlineColor ?? paint['_outline-color'] ?? paint['outline-color'];
  const width = builder.outlineWidth ?? paint['_outline-width'] ?? paint['outline-width'];
  const authoredColor = typeof color === 'string' ? color : undefined;
  return {
    disabled: builder.strokeDisabled ?? !!paint['_stroke-disabled'],
    authoredColor,
    color: authoredColor ?? MAP_COLORS.default.stroke,
    width: typeof width === 'number' ? width : 1,
  };
}

/**
 * The stored fill keys, or the default fill when no scalar survives, with each
 * stored expression and the opacity keys. The native outline takes the authored
 * outline colour or none, since the outline layer draws the stroke.
 */
function fillPaint(input: AdapterLayerInput, stroke: PolygonStroke): Record<string, unknown> {
  const { paint } = input;
  const hasExpressions = Object.values(paint).some(Array.isArray);
  const expressions = Object.entries(filterPaintForLayerType(paint, 'fill')).filter(([, value]) => Array.isArray(value));
  return {
    ...resolveFillPaint(hasExpressions ? simplifyPaint(paint) : paint),
    ...Object.fromEntries(expressions),
    'fill-opacity': getFeatureOpacity(paint, 'fill'),
    'fill-layer-opacity': input.opacity ?? 1,
    'fill-outline-color': stroke.disabled ? MAP_COLORS.transparent : (stroke.authoredColor ?? MAP_COLORS.transparent),
  };
}

function extrusionSpec(
  input: AdapterLayerInput,
  heightColumn: string,
  base: Pick<LayerSpec['layer'], 'source' | 'source-layer' | 'filter' | 'layout'>,
): LayerSpec {
  const builder = getBuilderStyleConfig(input);
  const { heightScale, extrusionMinZoom, extrusionOpacity } = getExtrusionOptions(input);
  const zoom = input.zoom ?? FULL_ZOOM_RANGE;
  // Only the zooms both the layer's range and the extrusion minimum allow. An
  // empty overlap collapses to minzoom === maxzoom, which draws nothing.
  const minzoom = Math.max(zoom.minzoom, extrusionMinZoom);
  return {
    layer: {
      id: `${input.layerId}-extrusion`,
      type: 'fill-extrusion',
      ...base,
      minzoom,
      maxzoom: Math.max(zoom.maxzoom, minzoom),
      paint: {
        'fill-extrusion-height': buildHeightExpression(heightColumn, heightScale),
        'fill-extrusion-base': 0,
        'fill-extrusion-color': resolveExtrusionFillColor(input.paint, builder),
        'fill-extrusion-opacity': extrusionOpacity,
        'fill-extrusion-vertical-gradient': true,
      },
    },
    ownedPaint: EXTRUSION_OWNED_PAINT_PROPERTIES,
    ownedLayout: [],
  };
}

function describeFill(input: AdapterLayerInput): LayerDrawing {
  const builder = getBuilderStyleConfig(input);
  const stroke = resolvePolygonStroke(input.paint, builder);
  const fill = tintFillPattern(fillPaint(input, stroke), input.paint, builder);
  const visibility = input.visible ? 'visible' : 'none';
  const shared = { source: input.sourceId, ...sourceLayerSpec(input), ...filterSpec(input.filter) };
  const specs: LayerSpec[] = [
    {
      layer: { id: input.layerId, type: 'fill', ...shared, layout: { ...input.layout, visibility }, paint: fill.paint },
      ownedPaint: FILL_OWNED_PAINT_PROPERTIES,
      ownedLayout: [],
    },
    {
      layer: {
        id: `${input.layerId}-outline`,
        type: 'line',
        ...shared,
        // A disabled stroke keeps the outline hidden whatever the layer's visibility.
        layout: { visibility: input.visible && !stroke.disabled ? 'visible' : 'none' },
        paint: { 'line-color': stroke.color, 'line-width': stroke.width, 'line-layer-opacity': input.opacity ?? 1 },
      },
      ownedPaint: OUTLINE_OWNED_PAINT_PROPERTIES,
      ownedLayout: ['visibility'],
    },
  ];
  const heightColumn = resolveHeightColumn(builder, input.paint);
  if (heightColumn) specs.push(extrusionSpec(input, heightColumn, { ...shared, layout: { visibility } }));
  return { specs, images: [...FILL_PATTERN_IMAGES, ...fill.images] };
}

export const fillAdapter: LayerAdapter = {
  type: 'fill',
  describe: describeFill,

  addLayers(map, input) {
    addDescribedLayer(map, describeFill(input));
  },

  // Updates only the layers already on the map, and removes the extrusion once
  // the layer has no height column.
  syncPaint(map, input) {
    const drawing = describeFill(input);
    writeDescribedLayer(map, { ...drawing, specs: drawing.specs.filter(({ layer }) => map.getLayer(layer.id)) });
    const extrusionId = `${input.layerId}-extrusion`;
    if (!map.getLayer(extrusionId)) return;
    if (!drawing.specs.some(({ layer }) => layer.id === extrusionId)) {
      map.removeLayer(extrusionId);
      return;
    }
    // Workaround MapLibre v5 bug: setPaintProperty only applies every other call with terrain active
    try { map.triggerRepaint(); } catch (e) { if (import.meta.env.DEV) console.debug('[map-sync] triggerRepaint not available:', e); }
  },

  syncVisibility(map, input) {
    writeDescribedVisibility(map, describeFill(input));
  },

  getLayerIds(layerId: string): string[] {
    return [layerId, `${layerId}-outline`, `${layerId}-extrusion`];
  },
};
