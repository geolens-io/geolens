import type { StyleConfig } from '@/types/api';
import { getColorProperty, getSizeProperty } from './color-ramps';
import { inferGeometryType } from './geo-utils';

/**
 * Extract breaks and values from a MapLibre "step" or "interpolate" expression.
 *
 * Step format:        ["step", input, initial, stop1, val1, stop2, val2, ...]
 * Interpolate format: ["interpolate", ["linear"], input, stop0, val0, stop1, val1, ...]
 *
 * Returns: { values: [val0, val1, ...], breaks: [stop1, stop2, ...] }
 *   For step: breaks separate the value ranges (N values, N-1 breaks)
 *   For interpolate: all stops become breaks, all values returned
 */
export function parseStepOrInterpolate(expr: unknown): { values: unknown[]; breaks: number[] } | null {
  if (!Array.isArray(expr) || expr.length < 4) return null;

  if (expr[0] === 'step') {
    const initial = expr[2];
    const values: unknown[] = [initial];
    const breaks: number[] = [];
    for (let i = 3; i < expr.length; i += 2) {
      if (typeof expr[i] === 'number') breaks.push(expr[i]);
      else break; // malformed — stop positions must be numbers
      if (i + 1 < expr.length) values.push(expr[i + 1]);
    }
    return { values, breaks };
  }

  if (expr[0] === 'interpolate') {
    // ["interpolate", interpolation, input, stop0, val0, stop1, val1, ...]
    const values: unknown[] = [];
    const allStops: number[] = [];
    for (let i = 3; i < expr.length; i += 2) {
      if (typeof expr[i] === 'number') allStops.push(expr[i]);
      else break;
      if (i + 1 < expr.length) values.push(expr[i + 1]);
    }
    // Convert to step-style breaks: drop the first stop (it's the "< X" bucket)
    const breaks = allStops.slice(1);
    return { values, breaks };
  }

  return null;
}

export interface NormalizedLayerStyleState {
  style_config: StyleConfig | null;
  paint: Record<string, unknown>;
}

const LEGACY_BUILDER_PAINT_KEYS = new Set([
  '_outline-width',
  '_outline-color',
  'outline-width',
  'outline-color',
  '_fill-disabled',
  '_stroke-disabled',
  '_fill-opacity-saved',
  '_outline-width-saved',
  '_heatmap-ramp',
  '_heatmap-weight-column',
  '_height_column',
]);

const LEGACY_BUILDER_KEY_ALIASES: Record<string, string> = {
  fill_disabled: 'fillDisabled',
  stroke_disabled: 'strokeDisabled',
  fill_opacity_saved: 'fillOpacitySaved',
  outline_width_saved: 'outlineWidthSaved',
  outline_color: 'outlineColor',
  outline_width: 'outlineWidth',
  heatmap_ramp: 'heatmapRamp',
  heatmap_weight_column: 'heatmapWeightColumn',
  height_column: 'heightColumn',
  height_scale: 'heightScale',
  extrusion_min_zoom: 'extrusionMinZoom',
  extrusion_opacity: 'extrusionOpacity',
};

function compactRecord<T extends Record<string, unknown>>(record: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(record).filter(([, value]) => value !== undefined),
  ) as Partial<T>;
}

export function stripLegacyBuilderPaint(paint: Record<string, unknown> | null | undefined): Record<string, unknown> {
  if (!paint) return {};
  return Object.fromEntries(
    Object.entries(paint).filter(([key]) => !LEGACY_BUILDER_PAINT_KEYS.has(key)),
  );
}

function normalizeBuilderStyleConfig(
  raw: Record<string, unknown> | null | undefined,
  paint: Record<string, unknown> | null | undefined,
): StyleConfig['builder'] | undefined {
  const rawBuilder = raw?.builder && typeof raw.builder === 'object' && !Array.isArray(raw.builder)
    ? raw.builder as Record<string, unknown>
    : {};
  const normalizedRawBuilder = Object.entries(rawBuilder).reduce<Record<string, unknown>>((acc, [key, value]) => {
    const aliasKey = LEGACY_BUILDER_KEY_ALIASES[key];
    const canonicalKey = aliasKey ?? key;
    if (!aliasKey || acc[canonicalKey] === undefined) acc[canonicalKey] = value;
    return acc;
  }, {});

  const fillDisabled = typeof paint?.['_fill-disabled'] === 'boolean'
    ? paint['_fill-disabled'] as boolean
    : normalizedRawBuilder.fillDisabled as boolean | undefined;
  const strokeDisabled = typeof paint?.['_stroke-disabled'] === 'boolean'
    ? paint['_stroke-disabled'] as boolean
    : normalizedRawBuilder.strokeDisabled as boolean | undefined;
  const fillOpacitySaved = typeof paint?.['_fill-opacity-saved'] === 'number'
    ? paint['_fill-opacity-saved'] as number
    : normalizedRawBuilder.fillOpacitySaved as number | undefined;
  const outlineWidthSaved = typeof paint?.['_outline-width-saved'] === 'number'
    ? paint['_outline-width-saved'] as number
    : normalizedRawBuilder.outlineWidthSaved as number | undefined;
  const outlineColor = typeof paint?.['_outline-color'] === 'string'
    ? paint['_outline-color'] as string
    : typeof paint?.['outline-color'] === 'string'
      ? paint['outline-color'] as string
      : normalizedRawBuilder.outlineColor as string | undefined;
  const outlineWidth = typeof paint?.['_outline-width'] === 'number'
    ? paint['_outline-width'] as number
    : typeof paint?.['outline-width'] === 'number'
      ? paint['outline-width'] as number
      : normalizedRawBuilder.outlineWidth as number | undefined;
  const heatmapRamp = typeof paint?.['_heatmap-ramp'] === 'string'
    ? paint['_heatmap-ramp'] as string
    : typeof raw?.ramp === 'string' && raw.render_mode === 'heatmap'
      ? raw.ramp as string
      : normalizedRawBuilder.heatmapRamp as string | undefined;
  const heatmapWeightColumn = typeof paint?.['_heatmap-weight-column'] === 'string'
    ? paint['_heatmap-weight-column'] as string
    : typeof raw?.weight_column === 'string'
      ? raw.weight_column as string
      : normalizedRawBuilder.heatmapWeightColumn as string | undefined;
  const heightColumn = typeof paint?.['_height_column'] === 'string'
    ? paint['_height_column'] as string
    : normalizedRawBuilder.heightColumn as string | undefined;

  const builder = compactRecord({
    ...normalizedRawBuilder,
    fillDisabled,
    strokeDisabled,
    fillOpacitySaved,
    outlineWidthSaved,
    outlineColor,
    outlineWidth,
    heatmapRamp,
    heatmapWeightColumn,
    heightColumn,
  });

  return Object.keys(builder).length > 0 ? builder : undefined;
}

/**
 * Normalize a style_config that may use legacy field names (from demo fixtures,
 * AI-generated maps, or older API versions) into the canonical frontend schema.
 *
 * Also fills in missing colors/breaks/sizes from paint step expressions,
 * even for canonical configs (the DataDrivenStyleEditor omits `colors`
 * when target is radius/width).
 */
export function normalizeStyleConfig(
  raw: Record<string, unknown> | null | undefined,
  paint: Record<string, unknown> | null | undefined,
  geometryType: string | null,
): StyleConfig | null {
  const builder = normalizeBuilderStyleConfig(raw, paint);
  if (!raw) return builder ? ({ builder } as StyleConfig) : null;

  // Heatmap configs use a different schema (render_mode/ramp/weight_column)
  // that doesn't fit the graduated/classified pattern — preserve as-is.
  if (raw.render_mode === 'heatmap') {
    return {
      mode: 'graduated',
      column: '',
      ramp: (raw.ramp ?? builder?.heatmapRamp ?? 'YlOrRd') as string,
      render_mode: 'heatmap',
      ...(builder ? { builder } : {}),
    } as StyleConfig;
  }

  // Detect legacy schema
  const isLegacy =
    raw.type === 'classified' ||
    raw.type === 'choropleth' ||
    (raw.column_name && !raw.column) ||
    (raw.value_field && !raw.column);

  // Start from canonical schema or map legacy field names
  const normalized: StyleConfig | null = isLegacy
    ? {
        mode: 'graduated',
        column: (raw.column_name ?? raw.value_field ?? '') as string,
        target: (raw.target as StyleConfig['target']) ?? 'color',
        ramp: (raw.ramp ?? raw.colormap ?? raw.color_scheme ?? 'YlOrRd') as string,
        classCount: (raw.classCount ?? raw.num_classes ?? raw.n_classes ?? 5) as number,
        method: (raw.method ?? raw.classification_method ?? raw.classification ?? 'quantile') as StyleConfig['method'],
        ...(raw.render_mode ? { render_mode: raw.render_mode as StyleConfig['render_mode'] } : {}),
      }
    : (typeof raw.mode === 'string' && typeof raw.column === 'string'
        ? { ...(raw as unknown as StyleConfig) }
        : builder
          ? ({ ...(raw as unknown as StyleConfig), builder } as StyleConfig)
          : null);
  if (!normalized) return null;
  if (builder) normalized.builder = builder;

  // Coerce JSON nulls to undefined for optional array fields
  if (normalized.breaks === null) normalized.breaks = undefined;
  if (normalized.colors === null) normalized.colors = undefined;
  if (normalized.sizes === null) normalized.sizes = undefined;

  // Early exit if all fields are already populated — no paint extraction needed
  if (normalized.colors && normalized.breaks) {
    if (normalized.target === 'color' || (normalized.sizes && normalized.sizes.length > 0)) {
      return normalized;
    }
  }

  // Extract colors/breaks/sizes from paint expressions if missing
  if (paint && normalized.column) {
    const effectiveGeom = inferGeometryType(paint, geometryType);
    const colorProp = getColorProperty(effectiveGeom);
    const sizeProp = getSizeProperty(effectiveGeom, normalized.target ?? 'color');

    const isSizeTarget = normalized.target === 'radius' || normalized.target === 'width';

    // Extract colors from color step expression
    if (!normalized.colors) {
      const parsed = parseStepOrInterpolate(paint[colorProp]);
      if (parsed && parsed.values.every((v) => typeof v === 'string')) {
        normalized.colors = parsed.values as string[];
        // Use color breaks only when target is color (legend iterates over colors)
        if (!normalized.breaks && !isSizeTarget) normalized.breaks = parsed.breaks;
      }
    }

    // Extract sizes + breaks from size step expression
    if (!normalized.sizes && sizeProp) {
      const parsed = parseStepOrInterpolate(paint[sizeProp]);
      if (parsed && parsed.values.every((v) => typeof v === 'number')) {
        normalized.sizes = parsed.values as number[];
        // For size targets, breaks MUST match sizes (legend iterates over sizes)
        if (isSizeTarget) normalized.breaks = parsed.breaks;
        else if (!normalized.breaks) normalized.breaks = parsed.breaks;
      }
    }
  }

  return normalized;
}

export function normalizeLayerStyleState(
  raw: Record<string, unknown> | null | undefined,
  paint: Record<string, unknown> | null | undefined,
  geometryType: string | null,
): NormalizedLayerStyleState {
  return {
    style_config: normalizeStyleConfig(raw, paint, geometryType),
    paint: stripLegacyBuilderPaint(paint),
  };
}
