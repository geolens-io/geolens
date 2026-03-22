/**
 * Centralized MapLibre paint color constants.
 *
 * MapLibre GL cannot consume CSS custom properties at runtime, so these
 * hex values are the sRGB equivalents of the OKLCH design tokens defined
 * in index.css. Keep them in sync when the token palette changes.
 *
 * Token reference (light mode):
 *   primary-500  oklch(0.55 0.18 250)  -> #3b82f6
 *   primary-700  oklch(0.46 0.16 250)  -> #1d4ed8
 */
export const MAP_COLORS = {
  /** Default layer paint colors (blue primary) */
  default: {
    fill: '#3b82f6',
    stroke: '#1d4ed8',
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
  /** Data-driven style fallback color */
  fallback: '#cccccc',
  /** Select mode handle/midpoint colors */
  handle: {
    point: '#ffffff',
    pointOutline: '#1d4ed8',
    midpoint: '#93c5fd',
    midpointOutline: '#1d4ed8',
  },
  /**
   * Categorical palette for multi-layer coloring (8 distinct colors).
   * Visually matches the --viz-* OKLCH tokens.
   */
  categorical: [
    '#3b82f6', // viz-1: blue
    '#f59e0b', // viz-2: orange
    '#22c55e', // viz-3: green
    '#a855f7', // viz-4: purple
    '#14b8a6', // viz-5: teal
    '#f43f5e', // viz-6: pink
    '#eab308', // viz-7: amber
    '#6366f1', // viz-8: indigo
  ],
} as const;
