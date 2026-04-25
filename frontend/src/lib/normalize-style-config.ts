import type { StyleConfig } from '@/types/api';
import { getColorProperty, getSizeProperty } from './color-ramps';

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
  if (!raw) return null;

  // Detect legacy schema
  const isLegacy =
    raw.type === 'classified' ||
    raw.type === 'choropleth' ||
    (raw.column_name && !raw.column) ||
    (raw.value_field && !raw.column);

  // Start from canonical schema or map legacy field names
  const normalized: StyleConfig = isLegacy
    ? {
        mode: 'graduated',
        column: (raw.column_name ?? raw.value_field ?? '') as string,
        target: (raw.target as StyleConfig['target']) ?? 'color',
        ramp: (raw.ramp ?? raw.colormap ?? raw.color_scheme ?? 'YlOrRd') as string,
        classCount: (raw.classCount ?? raw.num_classes ?? raw.n_classes ?? 5) as number,
        method: (raw.method ?? raw.classification_method ?? raw.classification ?? 'quantile') as StyleConfig['method'],
        ...(raw.render_mode ? { render_mode: raw.render_mode as StyleConfig['render_mode'] } : {}),
      }
    : { ...(raw as StyleConfig) };

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
    const colorProp = getColorProperty(geometryType);
    const sizeProp = getSizeProperty(geometryType, normalized.target ?? 'color');

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
