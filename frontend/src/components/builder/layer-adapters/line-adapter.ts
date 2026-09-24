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
import { addDescribedLayer, writeDescribedLayer, writeDescribedVisibility } from '../layer-writer';
import { labelLayerId, withLabelCompanion } from '../label-layer-utils';
// builder-audit #338 DRY-06: arrow render-mode defaults come from the single builder-defaults
// source of truth (shared with renderAs + backend mirror) instead of bare 14/80 literals.
import { DEFAULT_ARROW_SIZE, DEFAULT_ARROW_SPACING, DEFAULT_LINE_PAINT } from './builder-defaults';

const ARROW_IMAGE_ID = 'geolens-line-arrow';
/** SVG base pixel size at which icon-size renders 1:1 — NOT the default arrow size
 *  (that is DEFAULT_ARROW_SIZE); kept local since it is intrinsic to arrowImageData. */
const ARROW_BASE_SIZE = 14;
export const LINE_OWNED_LAYOUT_PROPERTIES = [
  'line-cap',
  'line-join',
] as const;

// Exported for the mixed adapter's line-family sublayer (ADAPT-03 reuse).
export const LINE_OWNED_PAINT_PROPERTIES = [
  'line-color',
  'line-width',
  'line-gap-width',
  'line-offset',
  'line-blur',
  'line-opacity',
  'line-layer-opacity',
  'line-gradient',
  'line-dasharray',
  'line-pattern',
  'line-translate',
  'line-translate-anchor',
] as const;
export const ARROW_OWNED_PAINT_PROPERTIES = ['icon-color', 'icon-opacity'] as const;
export const ARROW_OWNED_LAYOUT_PROPERTIES = [
  'symbol-placement',
  'symbol-spacing',
  'icon-image',
  'icon-size',
  'icon-allow-overlap',
  'icon-ignore-placement',
  'icon-rotation-alignment',
  'visibility',
] as const;

function arrowLayerId(layerId: string) {
  return `${layerId}-arrow`;
}

function arrowImageData() {
  const size = 24;
  const data = new Uint8ClampedArray(size * size * 4);
  const setPixel = (x: number, y: number, alpha: number) => {
    const index = (y * size + x) * 4;
    data[index] = 255;
    data[index + 1] = 255;
    data[index + 2] = 255;
    data[index + 3] = alpha;
  };

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const inStem = x >= 3 && x <= 13 && y >= 9 && y <= 14;
      const headWidth = Math.max(0, 20 - x);
      const inHead = x >= 10 && x <= 21 && Math.abs(y - 11.5) <= headWidth * 0.55;
      if (inStem || inHead) setPixel(x, y, 255);
    }
  }

  return { width: size, height: size, data };
}

const ARROW_IMAGE: ImageSpec = {
  kind: 'image',
  id: ARROW_IMAGE_ID,
  data: arrowImageData,
  options: { sdf: true, pixelRatio: 1 },
};

function arrowConfig(input: AdapterLayerInput) {
  const builder = getBuilderStyleConfig(input);
  const lineColor = typeof input.paint['line-color'] === 'string'
    ? input.paint['line-color']
    : MAP_COLORS.default.fill;
  return {
    color: typeof builder.arrowColor === 'string' ? builder.arrowColor : lineColor,
    size: typeof builder.arrowSize === 'number' ? builder.arrowSize : DEFAULT_ARROW_SIZE,
    spacing: typeof builder.arrowSpacing === 'number' ? builder.arrowSpacing : DEFAULT_ARROW_SPACING,
  };
}

function isArrowMode(input: AdapterLayerInput) {
  return input.style_config?.render_mode === 'arrow';
}

function arrowSpec(input: AdapterLayerInput): LayerSpec {
  const config = arrowConfig(input);
  return {
    layer: {
      id: arrowLayerId(input.layerId),
      type: 'symbol',
      source: input.sourceId,
      ...sourceLayerSpec(input),
      ...filterSpec(input.filter),
      layout: {
        'symbol-placement': 'line',
        'symbol-spacing': config.spacing,
        'icon-image': ARROW_IMAGE_ID,
        'icon-size': config.size / ARROW_BASE_SIZE,
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
        'icon-rotation-alignment': 'map',
        visibility: input.visible ? 'visible' : 'none',
      },
      paint: {
        'icon-color': config.color,
        'icon-opacity': input.opacity ?? 1,
      },
    },
    ownedPaint: ARROW_OWNED_PAINT_PROPERTIES,
    ownedLayout: ARROW_OWNED_LAYOUT_PROPERTIES,
  };
}

/** The line paint the adapter adds: the stored line keys, or the default line paint when none are stored. */
export function resolveLinePaint(paint: Record<string, unknown>): Record<string, unknown> {
  const linePaint = filterPaintForLayerType(paint, 'line');
  return Object.keys(linePaint).length > 0 ? linePaint : { ...DEFAULT_LINE_PAINT };
}

/**
 * The line paint a line layer draws: the stored line keys with their scalar
 * fallbacks, or the default line paint when none survive, then each stored
 * expression. Master opacity rides on `line-layer-opacity`, its own tier in
 * maplibre-gl v6, leaving the per-feature `line-opacity` unmultiplied.
 *
 * line-gradient REQUIRES an expression that consumes ['line-progress'] — there is no
 * valid scalar fallback, so it is excluded from the "is paint empty" check the same
 * way the legacy add path did. The writer's EXPRESSION_ONLY_PAINT keeps a real
 * gradient expression out of the initial addLayer call; reconcilePaint installs it.
 */
function linePaint(input: AdapterLayerInput): Record<string, unknown> {
  const rawPaint = input.paint;
  const hasExpressions = Object.entries(rawPaint).some(
    ([key, value]) => key !== 'line-dasharray' && Array.isArray(value),
  );
  const basePaint = hasExpressions ? simplifyPaint(rawPaint) : rawPaint;
  const { 'line-gradient': _gradientFallback, ...basePaintWithoutGradient } = basePaint;
  const resolved = resolveLinePaint(
    hasExpressions && Array.isArray(rawPaint['line-gradient']) ? basePaintWithoutGradient : basePaint,
  );
  // Legacy maps may still carry line-dasharray in layout; MapLibre expects it in paint.
  const legacyDasharray = (input.layout as Record<string, unknown> | undefined)?.['line-dasharray'];
  if (legacyDasharray != null && resolved['line-dasharray'] == null) {
    resolved['line-dasharray'] = legacyDasharray;
  }
  const expressions = Object.entries(filterPaintForLayerType(rawPaint, 'line')).filter(([, v]) => Array.isArray(v));
  return {
    ...resolved,
    ...Object.fromEntries(expressions),
    'line-opacity': getFeatureOpacity(rawPaint, 'line'),
    'line-layer-opacity': input.opacity ?? 1,
  };
}

function lineLayout(input: AdapterLayerInput): Record<string, unknown> {
  const { 'line-dasharray': _legacyDasharray, ...restLayout } = (input.layout ?? {}) as Record<string, unknown>;
  return {
    'line-cap': 'round',
    'line-join': 'round',
    ...restLayout,
    visibility: input.visible ? 'visible' : 'none',
  };
}

function lineSpec(input: AdapterLayerInput): LayerSpec {
  return {
    layer: {
      id: input.layerId,
      type: 'line',
      source: input.sourceId,
      ...sourceLayerSpec(input),
      ...filterSpec(input.filter),
      layout: lineLayout(input),
      paint: linePaint(input),
    },
    ownedPaint: LINE_OWNED_PAINT_PROPERTIES,
    ownedLayout: LINE_OWNED_LAYOUT_PROPERTIES,
  };
}

function describeLine(input: AdapterLayerInput): LayerDrawing {
  const drawing = isArrowMode(input)
    ? { specs: [lineSpec(input), arrowSpec(input)], images: [ARROW_IMAGE] }
    : { specs: [lineSpec(input)], images: [] };
  return withLabelCompanion(input, drawing);
}

export const lineAdapter: LayerAdapter = {
  type: 'line',
  describe: describeLine,

  addLayers(map, input) {
    addDescribedLayer(map, describeLine(input));
  },

  syncPaint(map, input) {
    if (!map.getLayer(input.layerId)) return;
    // The writer never removes layers (it only adds and updates); a mode that
    // stops being 'arrow' has to drop the companion by hand.
    if (!isArrowMode(input) && map.getLayer(arrowLayerId(input.layerId))) {
      map.removeLayer(arrowLayerId(input.layerId));
    }
    writeDescribedLayer(map, describeLine(input));
  },

  syncVisibility(map, input) {
    writeDescribedVisibility(map, describeLine(input));
  },

  getLayerIds(layerId: string): string[] {
    return [layerId, arrowLayerId(layerId), labelLayerId(layerId)];
  },
};
