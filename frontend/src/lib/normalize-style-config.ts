import type { StyleConfig } from '@/types/api';
import { getColorProperty, getSizeProperty } from './color-ramps';
import { inferGeometryType } from './geo-utils';
import { normalizeDemStyleConfig } from './dem-render-mode';
import { walkExpressionPairs } from './zoom-expressions';
import {
  CUSTOM_PAINT_PROPS,
  BUILDER_STYLE_KEY_ALIASES,
} from '@/components/builder/layer-adapters/shared';

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
    const values: unknown[] = [expr[2]];
    const breaks: number[] = [];
    // DRY-04: pair-walk via the shared low-level walker; stop at the first
    // non-number stop position (malformed tail).
    for (const { first, second, hasSecond } of walkExpressionPairs(expr, 3)) {
      if (typeof first !== 'number') break;
      breaks.push(first);
      if (hasSecond) values.push(second);
    }
    return { values, breaks };
  }

  if (expr[0] === 'interpolate') {
    // ["interpolate", interpolation, input, stop0, val0, stop1, val1, ...]
    // SPEC-05: only LINEAR interpolation yields uniform legend breaks. For
    // exponential / cubic-bezier (and interpolate-hcl / interpolate-lab, which use
    // a different operator and never match here) the stop positions are NOT uniform
    // breaks, so fall back to opaque (null) rather than mislabel the curve as linear.
    const interpolation = expr[1];
    if (!Array.isArray(interpolation) || interpolation[0] !== 'linear') return null;

    const values: unknown[] = [];
    const allStops: number[] = [];
    for (const { first, second, hasSecond } of walkExpressionPairs(expr, 3)) {
      if (typeof first !== 'number') break;
      allStops.push(first);
      if (hasSecond) values.push(second);
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

// builder-audit #338 SPEC-08 / DRY-01 (cross-cutting): the legacy builder-private
// paint-key set and the snake->camel builder-key alias map are now single-sourced
// from layer-adapters/shared.ts (CUSTOM_PAINT_PROPS / BUILDER_STYLE_KEY_ALIASES)
// so the two frontend copies can no longer drift. The raster re-hydration block in
// normalizeLayerStyleState still handles _colormap/_stretch/_pmin/_pmax/_sigma,
// which are deliberately NOT in the strip set.
const LEGACY_BUILDER_PAINT_KEYS = CUSTOM_PAINT_PROPS;
const LEGACY_BUILDER_KEY_ALIASES = BUILDER_STYLE_KEY_ALIASES;

export const RENDER_MODES = new Set(['heatmap', 'hillshade', 'symbol', 'arrow', 'cluster', 'terrain', 'image']);

// builder-audit #338 CPLX-01: data-driven table for the repetitive "read the first
// typed paint key, else fall back to the normalized builder value" chains.
type BuilderFieldType = 'string' | 'number' | 'boolean';

interface PaintFallbackField {
  /** Paint keys tried in order; first one matching `type` wins. */
  paintKeys: string[];
  /** Canonical (camelCase) builder key the value resolves to / falls back from. */
  builderKey: string;
  type: BuilderFieldType;
}

const PAINT_FALLBACK_FIELDS: PaintFallbackField[] = [
  { paintKeys: ['_fill-disabled'], builderKey: 'fillDisabled', type: 'boolean' },
  { paintKeys: ['_stroke-disabled'], builderKey: 'strokeDisabled', type: 'boolean' },
  { paintKeys: ['_fill-opacity-saved'], builderKey: 'fillOpacitySaved', type: 'number' },
  { paintKeys: ['_outline-width-saved'], builderKey: 'outlineWidthSaved', type: 'number' },
  { paintKeys: ['_outline-color', 'outline-color'], builderKey: 'outlineColor', type: 'string' },
  { paintKeys: ['_outline-width', 'outline-width'], builderKey: 'outlineWidth', type: 'number' },
  { paintKeys: ['_height_column'], builderKey: 'heightColumn', type: 'string' },
];

function resolvePaintFallback(
  spec: PaintFallbackField,
  paint: Record<string, unknown> | null | undefined,
  normalizedRawBuilder: Record<string, unknown>,
): unknown {
  for (const key of spec.paintKeys) {
    const value = paint?.[key];
    if (typeof value === spec.type) return value;
  }
  return normalizedRawBuilder[spec.builderKey];
}

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
  delete normalizedRawBuilder.render_mode;

  // builder-audit #338 CPLX-01: table-driven "typed paint key (try each in order),
  // else normalized builder value" resolution — replaces nine near-identical
  // ternary ladders. Heatmap fields keep a bespoke chain below because they also
  // fall back to legacy top-level raw.* keys.
  const resolved: Record<string, unknown> = {};
  for (const spec of PAINT_FALLBACK_FIELDS) {
    resolved[spec.builderKey] = resolvePaintFallback(spec, paint, normalizedRawBuilder);
  }

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

  const builder = compactRecord({
    ...normalizedRawBuilder,
    ...resolved,
    heatmapRamp,
    heatmapWeightColumn,
  });

  return Object.keys(builder).length > 0 ? builder : undefined;
}

function normalizeRenderMode(raw: Record<string, unknown> | null | undefined): StyleConfig['render_mode'] | undefined {
  const direct = raw?.render_mode;
  if (typeof direct === 'string' && RENDER_MODES.has(direct)) {
    return direct as StyleConfig['render_mode'];
  }

  const rawBuilder = raw?.builder;
  const nested = rawBuilder && typeof rawBuilder === 'object' && !Array.isArray(rawBuilder)
    ? (rawBuilder as Record<string, unknown>).render_mode
    : undefined;
  if (typeof nested === 'string' && RENDER_MODES.has(nested)) {
    return nested as StyleConfig['render_mode'];
  }

  return undefined;
}

function normalizedRawStyleBase(
  raw: Record<string, unknown>,
  builder: StyleConfig['builder'] | undefined,
): Record<string, unknown> {
  const base: Record<string, unknown> = { ...raw };
  if (builder) {
    base.builder = builder;
    return base;
  }

  const rawBuilder = raw.builder;
  if (rawBuilder && typeof rawBuilder === 'object' && !Array.isArray(rawBuilder)) {
    const cleanedBuilder = { ...(rawBuilder as Record<string, unknown>) };
    delete cleanedBuilder.render_mode;
    if (Object.keys(cleanedBuilder).length > 0) {
      base.builder = cleanedBuilder;
    } else {
      delete base.builder;
    }
  }
  return base;
}

/**
 * builder-audit #338 CPLX-01: early-return ladder replacing the prior 3-level nested
 * ternary. Picks the base StyleConfig shape: legacy field-name mapping, canonical
 * mode+column passthrough, or a builder/render-mode-only shell — else null.
 */
function resolveNormalizedBase(
  raw: Record<string, unknown>,
  isLegacy: boolean,
  builder: StyleConfig['builder'] | undefined,
  renderMode: StyleConfig['render_mode'] | undefined,
): StyleConfig | null {
  const renderModePatch = renderMode ? { render_mode: renderMode } : {};

  if (isLegacy) {
    return {
      mode: 'graduated',
      column: (raw.column_name ?? raw.value_field ?? '') as string,
      target: (raw.target as StyleConfig['target']) ?? 'color',
      ramp: (raw.ramp ?? raw.colormap ?? raw.color_scheme ?? 'YlOrRd') as string,
      classCount: (raw.classCount ?? raw.num_classes ?? raw.n_classes ?? 5) as number,
      method: (raw.method ?? raw.classification_method ?? raw.classification ?? 'quantile') as StyleConfig['method'],
      ...renderModePatch,
    };
  }

  const isCanonical = typeof raw.mode === 'string' && typeof raw.column === 'string';
  if (isCanonical || builder || renderMode) {
    return {
      ...(normalizedRawStyleBase(raw, builder) as unknown as StyleConfig),
      ...renderModePatch,
    };
  }

  return null;
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
  const renderMode = normalizeRenderMode(raw);
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

  // Start from canonical schema or map legacy field names (CPLX-01: early-return
  // ladder lives in resolveNormalizedBase).
  const normalized = resolveNormalizedBase(raw, Boolean(isLegacy), builder, renderMode);
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
  options: { isDem?: boolean | null } = {},
): NormalizedLayerStyleState {
  const style_config = normalizeDemStyleConfig(
    normalizeStyleConfig(raw, paint, geometryType),
    options.isDem,
  );
  const cleanPaint = stripLegacyBuilderPaint(paint);
  // Re-hydrate the raster colormap/stretch builder-private keys back onto the
  // in-memory paint view. The backend stores them in style_config.builder (the
  // clean-paint boundary), but RasterStretchControls + buildColormapTileUrl read
  // them as `_`-prefixed paint keys — so re-inject them after load to keep the
  // editor and tile-render path working without a separate builder read path.
  const builder = style_config?.builder;
  if (builder) {
    if (typeof builder.colormap === 'string') cleanPaint._colormap = builder.colormap;
    if (typeof builder.stretch === 'string') cleanPaint._stretch = builder.stretch;
    if (typeof builder.pmin === 'number') cleanPaint._pmin = builder.pmin;
    if (typeof builder.pmax === 'number') cleanPaint._pmax = builder.pmax;
    if (typeof builder.sigma === 'number') cleanPaint._sigma = builder.sigma;
    if (typeof builder.hypso_enabled === 'boolean') cleanPaint['_hypso-enabled'] = builder.hypso_enabled;
    if (typeof builder.hypso_ramp === 'string') cleanPaint['_hypso-ramp'] = builder.hypso_ramp;
  }
  return { style_config, paint: cleanPaint };
}
