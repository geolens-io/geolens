/**
 * Centralized MapLibre paint color constants.
 *
 * MapLibre GL cannot consume CSS custom properties at runtime, so these
 * values use the frozen sRGB primary from branding v0.2.0 and clipped-sRGB
 * equivalents for the remaining light-theme OKLCH design tokens in index.css.
 * The parity test reads index.css and independently converts the non-frozen
 * tokens, so palette drift fails CI.
 *
 * Token reference (light mode):
 *   primary      oklch(0.55 0.18 250)  -> #3b6fd4 (branding v0.2.0)
 *   primary-700  oklch(0.46 0.16 250)  -> #0058ac
 */
const LIGHT_THEME_TOKEN_COLORS = {
  primary: '#3b6fd4',
  primary700: '#0058ac',
  viz: [
    '#3b6fd4', // viz-1: branded primary blue
    '#ec7c0e', // viz-2: orange
    '#2f9f3d', // viz-3: green
    '#914bbe', // viz-4: purple
    '#00a7a8', // viz-5: teal
    '#ec4b7f', // viz-6: pink
    '#e2a000', // viz-7: amber
    '#544ec5', // viz-8: indigo
  ],
} as const;

export const MAP_COLORS = {
  /** Default layer paint colors (blue primary) */
  default: {
    fill: LIGHT_THEME_TOKEN_COLORS.primary,
    stroke: LIGHT_THEME_TOKEN_COLORS.primary700,
    fillOpacity: 0.3,
    strokeWidth: 1.5,
  },
  /** Selection/highlight state (amber for contrast) */
  selection: {
    fill: '#f59e0b',
    stroke: '#d97706',
    fillOpacity: 0.25,
  },
  /** Drawing/overlay state (green for newly drawn geometry) */
  drawing: {
    fill: '#22c55e',
    stroke: '#15803d',
    fillOpacity: 0.25,
  },
  /** Terra Draw closing/action point (red) */
  closing: {
    point: '#ef4444',
    pointOutline: '#ffffff',
  },
  /** Label defaults */
  label: {
    color: '#333333',
    halo: '#ffffff',
  },
  /** Map canvas shown while a blank basemap is active. */
  canvas: {
    background: '#111111',
    settingsBackground: '#ffffff',
  },
  /** Default editable basemap line styling. */
  basemapSublayer: {
    stroke: '#888888',
    casing: '#cccccc',
  },
  /** Cluster count and bubble contrast colors. */
  cluster: {
    text: '#ffffff',
    stroke: '#ffffff',
    textHalo: 'rgba(0, 0, 0, 0.35)',
  },
  /** Temporary query-result overlay. */
  ephemeral: {
    color: '#f97316',
    outline: '#ffffff',
  },
  /** Measurement line and vertex overlay. */
  measurement: {
    color: LIGHT_THEME_TOKEN_COLORS.primary,
    pointOutline: '#ffffff',
  },
  /** Terrain hillshade defaults. */
  hillshade: {
    shadow: '#000000',
    highlight: '#ffffff',
    accent: '#000000',
  },
  /** Geometry glyph fallbacks when a layer has no explicit style color. */
  icon: {
    fallback: LIGHT_THEME_TOKEN_COLORS.viz[7],
    outline: '#666666',
    invalidColor: '#333333',
  },
  /** Fixed colors for the exported map-image title, legend, and attribution. */
  exportImage: {
    background: '#ffffff',
    text: '#0a0a0a',
    mutedText: '#666666',
    attribution: '#999999',
  },
  /** Transparent MapLibre paint value. */
  transparent: 'rgba(0,0,0,0)',
  /** Thumbnail/legend outline used when no authored stroke is available. */
  previewOutline: 'rgba(0,0,0,0.35)',
  /** Data-driven style fallback color */
  fallback: '#cccccc',
  /** Legend outline fallback when no explicit outline-color is set */
  legendOutline: 'rgba(0,0,0,0.15)',
  /** Select mode handle/midpoint colors */
  handle: {
    point: '#ffffff',
    pointOutline: '#1d4ed8',
    midpoint: '#93c5fd',
    midpointOutline: '#1d4ed8',
  },
  /**
   * Categorical palette for multi-layer coloring (8 distinct colors).
   * Map-safe equivalents of the light-theme --viz-1..8 tokens. Viz-1 uses
   * branding v0.2.0's frozen sRGB primary; the remaining slots are clipped.
   */
  categorical: LIGHT_THEME_TOKEN_COLORS.viz,
} as const;
