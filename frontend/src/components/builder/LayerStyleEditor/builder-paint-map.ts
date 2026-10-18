import type { BuilderStyleConfig } from '@/types/api';

/**
 * Single declarative source for the builderConfig-key <-> underscore-paint-key
 * <-> reverse-routed parity table. The orchestrator derives three things from
 * it:
 *   - {@link buildBuilderControlPaint} forward-maps builder fields onto `_`-paint keys
 *   - {@link routeBuilderPaintProp} reverse-routes `_`-paint keys back into builderConfig
 *   - {@link BUILDER_PAINT_STRIP_KEYS} is the builder-config-backed subset of the
 *     paint-strip allowlist (builder-paint-map.test.ts asserts it stays a subset
 *     of the canonical CUSTOM_PAINT_PROPS)
 *
 * Adding a builder-private style field = one row here.
 */
interface BuilderPaintField {
  /** Canonical (camelCase) builder key, e.g. `outlineColor`. */
  builderKey: keyof BuilderStyleConfig;
  /** Builder-private `_`-prefixed paint key, e.g. `_outline-color`. */
  paintKey: string;
  /**
   * When true, handlePaintProp reverse-routes edits of `paintKey` back into
   * updateBuilderConfig(builderKey) rather than writing raw MapLibre paint. Only
   * the user-editable outline color/width controls round-trip this way; the
   * *-saved / *-disabled bookkeeping keys are written by the orchestrator
   * directly.
   */
  reverse?: boolean;
}

export const BUILDER_PAINT_FIELDS: readonly BuilderPaintField[] = [
  { builderKey: 'outlineColor', paintKey: '_outline-color', reverse: true },
  { builderKey: 'outlineWidth', paintKey: '_outline-width', reverse: true },
  { builderKey: 'fillDisabled', paintKey: '_fill-disabled' },
  { builderKey: 'strokeDisabled', paintKey: '_stroke-disabled' },
  { builderKey: 'fillOpacitySaved', paintKey: '_fill-opacity-saved' },
  { builderKey: 'outlineWidthSaved', paintKey: '_outline-width-saved' },
  { builderKey: 'heightColumn', paintKey: '_height_column' },
  { builderKey: 'heatmapRamp', paintKey: '_heatmap-ramp' },
  { builderKey: 'heatmapReversed', paintKey: '_heatmap-reversed' },
  { builderKey: 'heatmapWeightColumn', paintKey: '_heatmap-weight-column' },
] as const;

/** Reverse router: `_`-paint key -> builder key, for the round-trip controls. */
const REVERSE_ROUTE: ReadonlyMap<string, keyof BuilderStyleConfig> = new Map(
  BUILDER_PAINT_FIELDS.filter((f) => f.reverse).map((f) => [f.paintKey, f.builderKey]),
);

/**
 * Builder-config-backed paint keys that must be stripped before paint reaches
 * MapLibre. A subset of the canonical CUSTOM_PAINT_PROPS allowlist (the canonical
 * set additionally carries non-underscore aliases and raster-only `_hypso-*` keys
 * that are not builder-config fields).
 */
export const BUILDER_PAINT_STRIP_KEYS: ReadonlySet<string> = new Set(
  BUILDER_PAINT_FIELDS.map((f) => f.paintKey),
);

/**
 * Forward map: overlay builder-config values onto the paint object under their
 * `_`-paint keys so the per-mode editors see a builder-canonical paint view.
 */
export function buildBuilderControlPaint(
  paint: Record<string, unknown>,
  builderConfig: BuilderStyleConfig,
): Record<string, unknown> {
  const overrides: Record<string, unknown> = {};
  for (const field of BUILDER_PAINT_FIELDS) {
    const value = builderConfig[field.builderKey];
    if (value !== undefined) overrides[field.paintKey] = value;
  }
  return { ...paint, ...overrides };
}

/**
 * Reverse router: returns the builder key a `_`-paint edit should route into,
 * or undefined when the key is plain MapLibre paint.
 */
export function routeBuilderPaintProp(key: string): keyof BuilderStyleConfig | undefined {
  return REVERSE_ROUTE.get(key);
}
