/**
 * builder-audit ADAPT-05 / ADAPT-06 / DRY-04 / DRY-06: single source of truth for
 * per-render-mode default paint and the arrow/extrusion magic constants that the
 * layer adapters and renderAs both need.
 *
 * Before this module the heatmap/hillshade/circle/fill defaults and the
 * arrow(14/80)/extrusion(14/0.85) constants were copy-pasted across renderAs.ts
 * and the individual adapters, in several cases with DIVERGENT values (heatmap
 * radius 18-vs-30, fill-opacity 0.45-vs-0.30) so a layer rendered one way when
 * created via the render-mode switch and another way via the adapter fallback.
 *
 * All colors are sourced from the MAP_COLORS design tokens (map-colors.ts), never
 * bare hex, so a palette change updates one place.
 */
import { MAP_COLORS } from '@/lib/map-colors';

/**
 * builder-audit ADAPT-05: reconcile the two conflicting DEFAULT_HEATMAP_PAINT
 * (renderAs radius 18 / weight 0.5 vs heatmap-adapter radius 30 / weight 1) to ONE
 * value. We prefer the ADAPTER's authored values (radius 30, weight 1) because
 * those are what a freshly-created heatmap actually renders with at add-time.
 *
 * `heatmap-color` is intentionally NOT included here: it is built from a named
 * ramp by buildHeatmapColorExpression() in heatmap-adapter.ts. Pulling that into
 * this constants module would create a circular import, and renderAs's heatmap
 * default never carried a color anyway. Consumers that need the color spread this
 * object and add `heatmap-color` themselves.
 */
export const DEFAULT_HEATMAP_PAINT = {
  'heatmap-radius': 30,
  'heatmap-weight': 1,
  'heatmap-intensity': 1,
  'heatmap-opacity': 0.8,
} as const;

/**
 * builder-audit ADAPT-06: single hillshade default (previously byte-identical
 * copies in renderAs.DEFAULT_HILLSHADE_PAINT and
 * hillshade-adapter.HILLSHADE_PAINT_DEFAULTS). Shadow/highlight/accent are pure
 * black/white, not palette tokens, so they stay as literals.
 */
export const DEFAULT_HILLSHADE_PAINT = {
  'hillshade-illumination-direction': 335,
  'hillshade-illumination-anchor': 'viewport',
  'hillshade-exaggeration': 0.5,
  'hillshade-shadow-color': '#000000',
  'hillshade-highlight-color': '#ffffff',
  'hillshade-accent-color': '#000000',
} as const;

/**
 * builder-audit ADAPT-03 / DRY-04: canonical default circle paint, matching the
 * add-time fallback used by BOTH circle-adapter and cluster-adapter (the dominant
 * path). NOTE: renderAs's render-as-switch circle default previously used a white
 * (#ffffff) stroke; render-as-created circles will now start with the token stroke
 * (MAP_COLORS.default.stroke = #1d4ed8) instead, matching what every default point
 * already renders with at add-time.
 */
export const DEFAULT_CIRCLE_PAINT = {
  'circle-radius': 5,
  'circle-color': MAP_COLORS.default.fill,
  'circle-stroke-color': MAP_COLORS.default.stroke,
  'circle-stroke-width': 1,
} as const;

/**
 * builder-audit DRY-04: canonical default fill paint. fill-opacity is reconciled
 * to MAP_COLORS.default.fillOpacity (0.30). NOTE: render-mode-switch-created
 * polygons previously started at fill-opacity 0.45; they will now start at 0.30,
 * matching map-colors.ts and shared.ts OPACITY_DEFAULTS.fill.
 */
export const DEFAULT_FILL_PAINT = {
  'fill-color': MAP_COLORS.default.fill,
  'fill-opacity': MAP_COLORS.default.fillOpacity,
  'fill-outline-color': MAP_COLORS.default.stroke,
} as const;

/** builder-audit DRY-06: arrow render-mode defaults (size 14, spacing 80 px). */
export const DEFAULT_ARROW_SIZE = 14;
export const DEFAULT_ARROW_SPACING = 80;

/** builder-audit DRY-06: 3D fill-extrusion defaults. Below the min zoom the
 *  extrusion is not shown; the opacity cap bounds a freshly-converted extrusion. */
export const DEFAULT_EXTRUSION_MIN_ZOOM = 14;
export const DEFAULT_EXTRUSION_OPACITY_CAP = 0.85;
