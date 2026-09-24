import type { AdapterLayerInput, LayerAdapter, LayerDrawing } from './types';
import {
  simplifyPaint,
  filterPaintForLayerType,
  filterSpec,
  getExpressionSafeOpacity,
  sourceLayerSpec,
} from './shared';
import { DEFAULT_CIRCLE_PAINT } from './builder-defaults';
import { addDescribedLayer, writeDescribedLayer, writeDescribedVisibility } from '../layer-writer';
import { labelLayerId, removeLabelCompanionIfCleared, withLabelCompanion } from '../label-layer-utils';

// builder-audit #338 ADAPT-03: exported so cluster-adapter's unclustered point reuses
// this exact owned set (was a byte-identical UNCLUSTERED_OWNED_PAINT_PROPERTIES copy).
// builder-audit #338 SPEC-06: 'circle-stroke-blur' removed — it is not a MapLibre GL paint
// property (the spec has circle-blur + circle-stroke-{width,color,opacity}, no stroke-blur);
// it was a silent no-op swallowed by setPaintProperty's try/catch.
export const CIRCLE_OWNED_PAINT_PROPERTIES = [
  'circle-radius',
  'circle-color',
  'circle-blur',
  'circle-opacity',
  'circle-translate',
  'circle-translate-anchor',
  'circle-pitch-scale',
  'circle-pitch-alignment',
  'circle-stroke-width',
  'circle-stroke-color',
  'circle-stroke-opacity',
] as const;

/** The circle paint the adapter adds: the stored circle keys, or the default circle paint when none are stored. */
export function resolveCirclePaint(paint: Record<string, unknown>): Record<string, unknown> {
  const circlePaint = filterPaintForLayerType(paint, 'circle');
  return Object.keys(circlePaint).length > 0 ? circlePaint : { ...DEFAULT_CIRCLE_PAINT };
}

/**
 * The ring a point layer draws, from the circle paint it adds with expressions at
 * their add-time values: null at a zero or unset width, MapLibre's default. Circle
 * paint applies as stored, so builder state and `_stroke-disabled` play no part.
 */
export function resolvePointStroke(paint: Record<string, unknown>): { color: string; width: number } | null {
  const circlePaint = resolveCirclePaint(simplifyPaint(paint));
  const width = circlePaint['circle-stroke-width'];
  if (typeof width !== 'number' || width <= 0) return null;
  const color = circlePaint['circle-stroke-color'];
  // MapLibre's default circle-stroke-color.
  return { color: typeof color === 'string' ? color : '#000000', width };
}

/**
 * The circle paint a point layer draws: the stored circle keys with their scalar
 * fallbacks, or the default circle paint when none survive, then each stored
 * expression, with the master opacity multiplied into `circle-opacity`.
 */
function circlePaint(paint: Record<string, unknown>, opacity: number): Record<string, unknown> {
  const hasExpressions = Object.values(paint).some(Array.isArray);
  const expressions = Object.entries(filterPaintForLayerType(paint, 'circle')).filter(([, value]) => Array.isArray(value));
  return {
    ...resolveCirclePaint(hasExpressions ? simplifyPaint(paint) : paint),
    ...Object.fromEntries(expressions),
    'circle-opacity': getExpressionSafeOpacity(paint, 'circle', opacity),
  };
}

function describeCircle(input: AdapterLayerInput): LayerDrawing {
  return withLabelCompanion(input, {
    specs: [{
      layer: {
        id: input.layerId,
        type: 'circle',
        source: input.sourceId,
        ...sourceLayerSpec(input),
        ...filterSpec(input.filter),
        layout: { ...input.layout, visibility: input.visible ? 'visible' : 'none' },
        paint: circlePaint(input.paint, input.opacity ?? 1),
      },
      ownedPaint: CIRCLE_OWNED_PAINT_PROPERTIES,
      ownedLayout: [],
    }],
    images: [],
  });
}

export const circleAdapter: LayerAdapter = {
  type: 'circle',
  describe: describeCircle,

  addLayers(map, input) {
    addDescribedLayer(map, describeCircle(input));
  },

  syncPaint(map, input) {
    if (!map.getLayer(input.layerId)) return;
    removeLabelCompanionIfCleared(map, input);
    writeDescribedLayer(map, describeCircle(input));
  },

  syncVisibility(map, input) {
    writeDescribedVisibility(map, describeCircle(input));
  },

  getLayerIds(layerId: string): string[] {
    return [layerId, labelLayerId(layerId)];
  },
};
