import { deepEqual } from '@/lib/deep-equal';
import { MAP_COLORS } from '@/lib/map-colors';
import type { BuilderStyleConfig, MapLayerResponse, StyleConfig } from '@/types/api';

// Exported for unit testing. True iff the editor draft (`draft`) diverges from
// its server-state baseline (`saved`) in paint, layout or style_config.
// Identity-equal references short-circuit to false. When `saved` is undefined it
// returns false: with no baseline to compare, the "Pending style preview"
// banner stays hidden.
export function hasUnsavedStyleChanges(
  draft: MapLayerResponse,
  saved: MapLayerResponse | undefined,
): boolean {
  if (!saved) return false;
  if (draft === saved) return false;
  return !(
    deepEqual(draft.paint ?? {}, saved.paint ?? {})
    && deepEqual(draft.layout ?? {}, saved.layout ?? {})
    && deepEqual(draft.style_config ?? null, saved.style_config ?? null)
  );
}

export const LINE_DASH_PRESETS = [
  { key: 'solid', value: undefined },
  { key: 'dashed', value: [4, 2] },
  { key: 'dotted', value: [1, 2] },
  { key: 'dashDot', value: [4, 2, 1, 2] },
] as const;

export const LINE_DASH_SERIALIZED = LINE_DASH_PRESETS.map((p) => JSON.stringify(p.value));

export const FILL_DEFAULTS = {
  'fill-color': MAP_COLORS.default.fill,
  'fill-opacity': MAP_COLORS.default.fillOpacity,
  '_outline-color': MAP_COLORS.default.stroke,
  '_outline-width': 1,
} as const;

export const LINE_DEFAULTS = {
  'line-color': MAP_COLORS.default.fill,
  'line-width': 2,
} as const;

export const CIRCLE_DEFAULTS = {
  'circle-color': MAP_COLORS.default.fill,
  'circle-radius': 5,
  'circle-stroke-color': MAP_COLORS.default.stroke,
  'circle-stroke-width': 1,
} as const;

export function getPaintValue<T>(paint: Record<string, unknown>, key: string, fallback: T): T {
  const val = paint[key];
  // Expression arrays (data-driven styles) aren't valid for scalar controls
  if (Array.isArray(val)) return fallback;
  return val !== undefined && val !== null ? (val as T) : fallback;
}

// Returns a scalar number or a MapLibre expression array (data-driven / zoom
// expression), never an arbitrary `unknown`, so callers (ZoomExpressionEditor
// `value`) get the scalar-or-expression contract.
export function getEditableNumericPaintValue(
  paint: Record<string, unknown>,
  key: string,
  fallback: number,
): number | unknown[] {
  const val = paint[key];
  if (typeof val === 'number') return val;
  if (Array.isArray(val)) return val;
  return fallback;
}

export function compactBuilder(builder: BuilderStyleConfig): BuilderStyleConfig | undefined {
  const compacted = Object.fromEntries(
    Object.entries(builder).filter(([, value]) => value !== undefined),
  ) as BuilderStyleConfig;
  return Object.keys(compacted).length > 0 ? compacted : undefined;
}

export function withBuilderConfig(styleConfig: StyleConfig | null | undefined, patch: BuilderStyleConfig): StyleConfig | null {
  const nextBuilder = compactBuilder({ ...(styleConfig?.builder ?? {}), ...patch });
  const nextConfig = { ...(styleConfig ?? {}) } as StyleConfig;
  if (nextBuilder) nextConfig.builder = nextBuilder;
  else delete nextConfig.builder;
  return Object.keys(nextConfig).length > 0 ? nextConfig : null;
}

export function hasUnsupportedBuilderState(layer: MapLayerResponse, geomType: string): boolean {
  const config = layer.style_config;
  if (!config) return false;
  if (config.render_mode === 'heatmap' || config.render_mode === 'symbol') return false;
  if (config.mode !== undefined && config.mode !== 'categorical' && config.mode !== 'graduated') return true;
  if (geomType === 'circle' || geomType === 'line' || geomType === 'fill') return false;
  return true;
}
