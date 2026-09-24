import type { StyleConfig } from '@/types/api';
import type { AdapterLayerInput, LayerAdapter, LayerDrawing } from './types';
import { filterSpec, getBuilderStyleConfig, sourceLayerSpec } from './shared';
import { addDescribedLayer, writeDescribedLayer, writeDescribedVisibility } from '../layer-writer';
// builder-audit #338 ADAPT-05: the radius/weight/intensity/opacity defaults come from the
// single builder-defaults source of truth (radius 30 / weight 1) instead of the magic
// literals that previously diverged from renderAs's heatmap default (radius 18 / weight 0.5).
import { DEFAULT_HEATMAP_PAINT as HEATMAP_PAINT_DEFAULTS } from './builder-defaults';
import { getRampColors } from '@/lib/color-ramps';
import { MAP_COLORS } from '@/lib/map-colors';

/** builder-audit #338 ADAPT-11: typed coercion so an out-of-range / string / expression
 *  heatmap-opacity cannot flow through a bare `as number` cast into NaN math
 *  (storedHeatmapOpacity * masterOpacity). Mirrors fill-adapter's finiteNumber. */
function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** Build the default heatmap-color interpolation expression using a named ramp.
 *  The expression has transparent (rgba 0,0,0,0) at density 0 so low-density
 *  areas are fully transparent. */
export function buildHeatmapColorExpression(rampName: string, reversed = false): unknown[] {
  const colors = getRampColors(rampName, 5, reversed);
  return [
    'interpolate', ['linear'], ['heatmap-density'],
    0,   MAP_COLORS.transparent,
    0.2, colors[0],
    0.4, colors[1],
    0.6, colors[2],
    0.8, colors[3],
    1.0, colors[4],
  ];
}

const DEFAULT_RAMP = 'YlOrRd';
export const HEATMAP_OWNED_PAINT_PROPERTIES = [
  'heatmap-radius',
  'heatmap-weight',
  'heatmap-intensity',
  'heatmap-color',
  'heatmap-opacity',
] as const;

/** Default paint properties for a new heatmap layer. The numeric defaults are the
 *  shared builder-defaults (radius/weight/intensity/opacity); only the ramp-derived
 *  heatmap-color is layered on here (it lives in this module to avoid a builder-defaults
 *  -> color-ramps circular import). */
export const DEFAULT_HEATMAP_PAINT: Record<string, unknown> = {
  ...HEATMAP_PAINT_DEFAULTS,
  'heatmap-color': buildHeatmapColorExpression(DEFAULT_RAMP),
};

export interface HeatmapColor {
  /** The heatmap-color expression the layer draws. */
  expression: unknown;
  /** The named ramp the expression is built from; null for a stored expression. */
  ramp: { name: string; reversed: boolean } | null;
}

/**
 * The heatmap-color a heatmap layer draws: a stored expression, else one built
 * from the builder ramp and direction, else YlOrRd forward.
 */
export function resolveHeatmapColor(
  paint: Record<string, unknown>,
  builder: NonNullable<StyleConfig['builder']>,
): HeatmapColor {
  const stored = paint['heatmap-color'];
  if (stored != null) return { expression: stored, ramp: null };
  const ramp = { name: builder.heatmapRamp ?? DEFAULT_RAMP, reversed: builder.heatmapReversed ?? false };
  return { expression: buildHeatmapColorExpression(ramp.name, ramp.reversed), ramp };
}

/**
 * The heatmap paint: the stored keys over the shared defaults, and the builder
 * ramp when no colour expression is stored. Radius, weight and intensity may be
 * zoom expressions, so only a missing one falls back; the stored opacity must be
 * a number, since the master slider multiplies it.
 */
function heatmapPaint(input: AdapterLayerInput): Record<string, unknown> {
  const { paint } = input;
  const builder = getBuilderStyleConfig(input);
  const storedOpacity = finiteNumber(paint['heatmap-opacity']) ?? HEATMAP_PAINT_DEFAULTS['heatmap-opacity'];
  return {
    'heatmap-radius': paint['heatmap-radius'] ?? HEATMAP_PAINT_DEFAULTS['heatmap-radius'],
    'heatmap-weight': paint['heatmap-weight'] ?? HEATMAP_PAINT_DEFAULTS['heatmap-weight'],
    'heatmap-intensity': paint['heatmap-intensity'] ?? HEATMAP_PAINT_DEFAULTS['heatmap-intensity'],
    'heatmap-color': resolveHeatmapColor(paint, builder).expression,
    'heatmap-opacity': storedOpacity * (input.opacity ?? 1),
  };
}

function describeHeatmap(input: AdapterLayerInput): LayerDrawing {
  return {
    specs: [{
      layer: {
        id: input.layerId,
        type: 'heatmap',
        source: input.sourceId,
        ...sourceLayerSpec(input),
        ...filterSpec(input.filter),
        layout: { visibility: input.visible ? 'visible' : 'none' },
        paint: heatmapPaint(input),
      },
      ownedPaint: HEATMAP_OWNED_PAINT_PROPERTIES,
      ownedLayout: [],
    }],
    images: [],
  };
}

export const heatmapAdapter: LayerAdapter = {
  type: 'heatmap',
  describe: describeHeatmap,

  addLayers(map, input) {
    addDescribedLayer(map, describeHeatmap(input));
  },

  syncPaint(map, input) {
    if (!map.getLayer(input.layerId)) return;
    writeDescribedLayer(map, describeHeatmap(input));
  },

  syncVisibility(map, input) {
    writeDescribedVisibility(map, describeHeatmap(input));
  },

  getLayerIds(layerId: string): string[] {
    return [layerId];
  },
};
