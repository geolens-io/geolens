import { MAP_COLORS } from '@/lib/map-colors';
import { stripLegacyBuilderPaint } from '@/lib/normalize-style-config';
import type { BuilderStyleConfig, MapLayerResponse, StyleConfig } from '@/types/api';

// ---------------------------------------------------------------------------
// SP-05 (Phase 1045): dirty-tracking helper
//
// Exported for unit testing. Returns true iff the editor draft (`draft`)
// diverges from its server-state baseline (`saved`) in any of:
//   - paint   (Record<string, unknown>)
//   - layout  (Record<string, unknown>)
//   - style_config (StyleConfig | null)
//
// Identity-equal references short-circuit to false. When `saved` is undefined,
// returns false — the caller has no baseline to compare against, so the
// "Pending style preview" banner stays hidden (smoke check 2026-05-15, M-04).
// ---------------------------------------------------------------------------
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

// Small inline deep-equality for plain JSON-ish values (objects, arrays,
// primitives, null). Sufficient for paint/layout/style_config which are JSON.
// Avoids pulling in lodash for a one-call surface.
function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') {
    return false;
  }
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i += 1) {
      if (!deepEqual(a[i], b[i])) return false;
    }
    return true;
  }
  const aKeys = Object.keys(a as Record<string, unknown>);
  const bKeys = Object.keys(b as Record<string, unknown>);
  if (aKeys.length !== bKeys.length) return false;
  for (const key of aKeys) {
    if (!Object.prototype.hasOwnProperty.call(b, key)) return false;
    if (!deepEqual((a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key])) return false;
  }
  return true;
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

export function getEditableNumericPaintValue(paint: Record<string, unknown>, key: string, fallback: number): number | unknown {
  const val = paint[key];
  return val !== undefined && val !== null ? val : fallback;
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

export function stylePreviewStyle(layer: MapLayerResponse) {
  const paint = layer.paint ?? {};
  const gt = (layer.dataset_geometry_type ?? '').toUpperCase();
  if (gt.includes('POLYGON')) {
    return {
      outlineColor: typeof paint['_outline-color'] === 'string' ? paint['_outline-color'] as string : undefined,
      strokeDisabled: Boolean(layer.style_config?.builder?.strokeDisabled ?? paint['_stroke-disabled']),
      opacity: layer.opacity,
      fillOpacity: typeof paint['fill-opacity'] === 'number' ? paint['fill-opacity'] as number : undefined,
      strokeWidth: typeof layer.style_config?.builder?.outlineWidth === 'number'
        ? layer.style_config.builder.outlineWidth
        : typeof paint['_outline-width'] === 'number'
          ? paint['_outline-width'] as number
          : undefined,
    };
  }
  if (gt.includes('POINT')) {
    return {
      outlineColor: typeof paint['circle-stroke-color'] === 'string' ? paint['circle-stroke-color'] as string : undefined,
      strokeDisabled: Boolean(layer.style_config?.builder?.strokeDisabled ?? paint['_stroke-disabled']),
      opacity: layer.opacity,
      fillOpacity: typeof paint['circle-opacity'] === 'number' ? paint['circle-opacity'] as number : undefined,
      strokeWidth: typeof paint['circle-stroke-width'] === 'number' ? paint['circle-stroke-width'] as number : undefined,
    };
  }
  return {
    opacity: layer.opacity,
    fillOpacity: typeof paint['line-opacity'] === 'number' ? paint['line-opacity'] as number : undefined,
    strokeWidth: typeof paint['line-width'] === 'number' ? paint['line-width'] as number : undefined,
  };
}

export function hasUnsupportedBuilderState(layer: MapLayerResponse, geomType: string): boolean {
  const config = layer.style_config;
  if (!config) return false;
  if (config.render_mode === 'heatmap' || config.render_mode === 'symbol') return false;
  if (config.mode !== undefined && config.mode !== 'categorical' && config.mode !== 'graduated') return true;
  if (geomType === 'circle' || geomType === 'line' || geomType === 'fill') return false;
  return true;
}

/**
 * Applies a builder config patch and strips legacy paint keys, then calls onStyleConfigChange.
 * Convenience wrapper used by the orchestrator's handleHeatmapPaintChange and
 * handleSymbolConfigChange callbacks.
 */
export function applyBuilderPatch(
  layerId: string,
  styleConfig: StyleConfig | null | undefined,
  patch: BuilderStyleConfig,
  paint: Record<string, unknown>,
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void,
): void {
  onStyleConfigChange(layerId, withBuilderConfig(styleConfig, patch), stripLegacyBuilderPaint(paint));
}
