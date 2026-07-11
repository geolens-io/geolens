import { classifyGeometry } from '@/components/builder/layer-adapters/shared';

// --- Curated palette definitions ---
//
// cvdSafe designations sourced from ColorBrewer 2.0 (colorbrewer2.org), which
// publishes per-palette colorblind-safe flags based on empirical testing:
//   Sequential single-hue (Blues, Greens, Oranges, etc.) — safe.
//   Sequential multi-hue (YlOrRd, BuGn, etc.) — safe.
//   Viridis family (Viridis, Inferno, Plasma) — perceptually uniform, CVD-safe.
//   Diverging: BrBG, PiYG, PRGn, PuOr, RdBu, RdYlBu — safe per ColorBrewer.
//   Diverging: RdYlGn, Spectral — NOT safe (red-green / rainbow confusion).
//   Qualitative: Set2, Dark2, Paired — listed safe at small N per ColorBrewer.
//   Qualitative: Set1, Set3, Accent, Pastel1, Pastel2 — NOT safe.

export const SEQUENTIAL_RAMPS = [
  { name: 'YlOrRd', label: 'Yellow-Orange-Red', cvdSafe: true },
  { name: 'YlGnBu', label: 'Yellow-Green-Blue', cvdSafe: true },
  { name: 'Viridis', label: 'Viridis', cvdSafe: true },
  { name: 'Inferno', label: 'Inferno', cvdSafe: true },
  { name: 'Plasma', label: 'Plasma', cvdSafe: true },
  { name: 'Blues', label: 'Blues', cvdSafe: true },
  { name: 'Greens', label: 'Greens', cvdSafe: true },
  { name: 'Oranges', label: 'Oranges', cvdSafe: true },
  { name: 'Reds', label: 'Reds', cvdSafe: true },
  { name: 'Purples', label: 'Purples', cvdSafe: true },
  { name: 'BuGn', label: 'Blue-Green', cvdSafe: true },
  { name: 'BuPu', label: 'Blue-Purple', cvdSafe: true },
  { name: 'OrRd', label: 'Orange-Red', cvdSafe: true },
  { name: 'YlGn', label: 'Yellow-Green', cvdSafe: true },
] as const;

export const DIVERGING_RAMPS = [
  { name: 'RdYlBu', label: 'Red-Yellow-Blue', cvdSafe: true },
  // RdYlGn uses red-green contrast — NOT colorblind-safe per ColorBrewer.
  { name: 'RdYlGn', label: 'Red-Yellow-Green', cvdSafe: false },
  { name: 'RdBu', label: 'Red-Blue', cvdSafe: true },
  { name: 'BrBG', label: 'Brown-BlueGreen', cvdSafe: true },
  { name: 'PiYG', label: 'Pink-YellowGreen', cvdSafe: true },
  { name: 'PRGn', label: 'Purple-Green', cvdSafe: true },
  // Spectral is a rainbow-like multi-hue — NOT colorblind-safe per ColorBrewer.
  { name: 'Spectral', label: 'Spectral', cvdSafe: false },
] as const;

export const QUALITATIVE_RAMPS = [
  // Set1 and Set3 use problematic red-green pairings — NOT colorblind-safe.
  { name: 'Set1', label: 'Set 1', cvdSafe: false },
  // Set2 and Dark2 are listed as colorblind-safe at small N per ColorBrewer.
  { name: 'Set2', label: 'Set 2', cvdSafe: true },
  { name: 'Set3', label: 'Set 3', cvdSafe: false },
  // Paired is listed as colorblind-safe per ColorBrewer.
  { name: 'Paired', label: 'Paired', cvdSafe: true },
  { name: 'Dark2', label: 'Dark 2', cvdSafe: true },
  // Accent, Pastel1, Pastel2 include red-green pairs — NOT colorblind-safe.
  { name: 'Accent', label: 'Accent', cvdSafe: false },
  { name: 'Pastel1', label: 'Pastel 1', cvdSafe: false },
  { name: 'Pastel2', label: 'Pastel 2', cvdSafe: false },
] as const;

// ---------------------------------------------------------------------------
// ENH-08: Deterministic ramp rotation + data-character suggestion
// ---------------------------------------------------------------------------
//
// Rotation lists are CVD-safe-first so the default visual experience works
// for colour-blind users without any explicit preference.
//
// GRADUATED rotation (sequential ramps, CVD-safe-first):
//   All SEQUENTIAL_RAMPS are cvdSafe, so the full list is the rotation.
//   Order chosen to maximise hue contrast between successive layers:
//   YlOrRd (warm) → Blues (cool) → Greens → Viridis (multi-hue) →
//   Oranges → Purples → YlGnBu → Inferno → BuGn → Reds →
//   Plasma → BuPu → OrRd → YlGn
//
// CATEGORICAL rotation (qualitative ramps, CVD-safe-first):
//   CVD-safe: Set2, Paired, Dark2
//   Non-safe (appended after so they are still reachable): Set1, Set3, Accent
const GRADUATED_ROTATION: readonly string[] = [
  'YlOrRd',
  'Blues',
  'Greens',
  'Viridis',
  'Oranges',
  'Purples',
  'YlGnBu',
  'Inferno',
  'BuGn',
  'Reds',
  'Plasma',
  'BuPu',
  'OrRd',
  'YlGn',
] as const;

const CATEGORICAL_ROTATION: readonly string[] = [
  // CVD-safe first
  'Set2',
  'Paired',
  'Dark2',
  // Non-CVD-safe (still useful at small N, included for completeness)
  'Set1',
  'Set3',
  'Accent',
] as const;

/**
 * Deterministic ramp rotation: maps a zero-based `index` to a ramp name by
 * cycling through the appropriate rotation list.
 *
 * - 'graduated' → sequences through sequential ramps (CVD-safe-first)
 * - 'categorical' → sequences through qualitative ramps (CVD-safe-first)
 *
 * Cycling guarantee: nextRotatingRamp(mode, k) === nextRotatingRamp(mode, k + listLength)
 * Distinct guarantee: the first listLength calls produce listLength distinct names
 * before any repetition occurs.
 *
 * Pure and deterministic — no randomness.
 */
export function nextRotatingRamp(
  mode: 'categorical' | 'graduated',
  index: number,
): string {
  const list = mode === 'graduated' ? GRADUATED_ROTATION : CATEGORICAL_ROTATION;
  return list[((index % list.length) + list.length) % list.length];
}

/**
 * Suggest a default ramp by data character:
 * - 'graduated'  → first sequential ramp in the rotation (YlOrRd)
 * - 'categorical' → first qualitative ramp in the rotation (Set2)
 *
 * Equivalent to nextRotatingRamp(mode, 0), exposed as a named helper so
 * call-sites can clearly express "I want the data-appropriate default".
 */
export function suggestRampForMode(mode: 'categorical' | 'graduated'): string {
  return nextRotatingRamp(mode, 0);
}

// ---------------------------------------------------------------------------

/**
 * Reverse an array of color strings.
 * Pure function — does not mutate the input.
 * Reversing twice is identity: reverseRamp(reverseRamp(colors)) === colors.
 */
export function reverseRamp(colors: string[]): string[] {
  return [...colors].reverse();
}

/**
 * Filter a ramp array to entries tagged cvdSafe: true.
 * Works with any of the three ramp arrays (SEQUENTIAL/DIVERGING/QUALITATIVE),
 * or a combined array formed by spreading them.
 */
export function cvdSafeRamps<T extends { cvdSafe: boolean }>(ramps: T[] | readonly T[]): T[] {
  return (ramps as T[]).filter((r) => r.cvdSafe);
}

// fix(#448): static ColorBrewer stop arrays (dumped verbatim from
// chroma.brewer) + a local interpolator replace the chroma-js dependency in
// this module. chroma-js (19.5KB gz, chunked as color-vendor) was leaking
// into the ENTRY graph via layer-icons/LegendEntries → this file, making the
// login page download it for two decorative heatmap previews. Output is
// bit-exact with chroma.scale(name).colors(count) — including replicating
// chroma's 1/(n-1) domain-breakpoint float arithmetic — and is pinned by a
// parity test that compares against chroma directly
// (__tests__/color-ramps-chroma-parity.test.ts). chroma-js remains a
// builder-only dependency (color-relief-sync.ts).
const BREWER_STOPS: Record<string, readonly string[]> = {
  YlOrRd: ['#ffffcc', '#ffeda0', '#fed976', '#feb24c', '#fd8d3c', '#fc4e2a', '#e31a1c', '#bd0026', '#800026'],
  YlGnBu: ['#ffffd9', '#edf8b1', '#c7e9b4', '#7fcdbb', '#41b6c4', '#1d91c0', '#225ea8', '#253494', '#081d58'],
  Viridis: ['#440154', '#482777', '#3f4a8a', '#31678e', '#26838f', '#1f9d8a', '#6cce5a', '#b6de2b', '#fee825'],
  Blues: ['#f7fbff', '#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#08519c', '#08306b'],
  Greens: ['#f7fcf5', '#e5f5e0', '#c7e9c0', '#a1d99b', '#74c476', '#41ab5d', '#238b45', '#006d2c', '#00441b'],
  Oranges: ['#fff5eb', '#fee6ce', '#fdd0a2', '#fdae6b', '#fd8d3c', '#f16913', '#d94801', '#a63603', '#7f2704'],
  Reds: ['#fff5f0', '#fee0d2', '#fcbba1', '#fc9272', '#fb6a4a', '#ef3b2c', '#cb181d', '#a50f15', '#67000d'],
  Purples: ['#fcfbfd', '#efedf5', '#dadaeb', '#bcbddc', '#9e9ac8', '#807dba', '#6a51a3', '#54278f', '#3f007d'],
  BuGn: ['#f7fcfd', '#e5f5f9', '#ccece6', '#99d8c9', '#66c2a4', '#41ae76', '#238b45', '#006d2c', '#00441b'],
  BuPu: ['#f7fcfd', '#e0ecf4', '#bfd3e6', '#9ebcda', '#8c96c6', '#8c6bb1', '#88419d', '#810f7c', '#4d004b'],
  OrRd: ['#fff7ec', '#fee8c8', '#fdd49e', '#fdbb84', '#fc8d59', '#ef6548', '#d7301f', '#b30000', '#7f0000'],
  YlGn: ['#ffffe5', '#f7fcb9', '#d9f0a3', '#addd8e', '#78c679', '#41ab5d', '#238443', '#006837', '#004529'],
  RdYlBu: ['#a50026', '#d73027', '#f46d43', '#fdae61', '#fee090', '#ffffbf', '#e0f3f8', '#abd9e9', '#74add1', '#4575b4', '#313695'],
  RdYlGn: ['#a50026', '#d73027', '#f46d43', '#fdae61', '#fee08b', '#ffffbf', '#d9ef8b', '#a6d96a', '#66bd63', '#1a9850', '#006837'],
  RdBu: ['#67001f', '#b2182b', '#d6604d', '#f4a582', '#fddbc7', '#f7f7f7', '#d1e5f0', '#92c5de', '#4393c3', '#2166ac', '#053061'],
  BrBG: ['#543005', '#8c510a', '#bf812d', '#dfc27d', '#f6e8c3', '#f5f5f5', '#c7eae5', '#80cdc1', '#35978f', '#01665e', '#003c30'],
  PiYG: ['#8e0152', '#c51b7d', '#de77ae', '#f1b6da', '#fde0ef', '#f7f7f7', '#e6f5d0', '#b8e186', '#7fbc41', '#4d9221', '#276419'],
  PRGn: ['#40004b', '#762a83', '#9970ab', '#c2a5cf', '#e7d4e8', '#f7f7f7', '#d9f0d3', '#a6dba0', '#5aae61', '#1b7837', '#00441b'],
  Spectral: ['#9e0142', '#d53e4f', '#f46d43', '#fdae61', '#fee08b', '#ffffbf', '#e6f598', '#abdda4', '#66c2a5', '#3288bd', '#5e4fa2'],
  Set1: ['#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#ffff33', '#a65628', '#f781bf', '#999999'],
  Set2: ['#66c2a5', '#fc8d62', '#8da0cb', '#e78ac3', '#a6d854', '#ffd92f', '#e5c494', '#b3b3b3'],
  Set3: ['#8dd3c7', '#ffffb3', '#bebada', '#fb8072', '#80b1d3', '#fdb462', '#b3de69', '#fccde5', '#d9d9d9', '#bc80bd', '#ccebc5', '#ffed6f'],
  Paired: ['#a6cee3', '#1f78b4', '#b2df8a', '#33a02c', '#fb9a99', '#e31a1c', '#fdbf6f', '#ff7f00', '#cab2d6', '#6a3d9a', '#ffff99', '#b15928'],
  Dark2: ['#1b9e77', '#d95f02', '#7570b3', '#e7298a', '#66a61e', '#e6ab02', '#a6761d', '#666666'],
  Accent: ['#7fc97f', '#beaed4', '#fdc086', '#ffff99', '#386cb0', '#f0027f', '#bf5b17', '#666666'],
  Pastel1: ['#fbb4ae', '#b3cde3', '#ccebc5', '#decbe4', '#fed9a6', '#ffffcc', '#e5d8bd', '#fddaec', '#f2f2f2'],
  Pastel2: ['#b3e2cd', '#fdcdac', '#cbd5e8', '#f4cae4', '#e6f5c9', '#fff2ae', '#f1e2cc', '#cccccc'],
};

function hexToRgb(hex: string): [number, number, number] {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

function rgbToHex(r: number, g: number, b: number): string {
  return (
    '#' +
    [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')
  );
}

/** Sample a stop array at t ∈ [0,1] with chroma-compatible RGB interpolation. */
function sampleStops(stops: readonly string[], t: number): string {
  const n = stops.length;
  if (t <= 0) return stops[0];
  if (t >= 1) return stops[n - 1];
  // chroma.scale places stops at k/(n-1) breakpoints and derives the segment
  // fraction from those (inexact) binary fractions; mirror that arithmetic
  // so rounding matches chroma's output bit-for-bit.
  let k = 0;
  while (t >= (k + 1) / (n - 1)) k++;
  if (k > n - 2) k = n - 2;
  const f = (t - k / (n - 1)) / ((k + 1) / (n - 1) - k / (n - 1));
  const a = hexToRgb(stops[k]);
  const b = hexToRgb(stops[k + 1]);
  return rgbToHex(
    a[0] + (b[0] - a[0]) * f,
    a[1] + (b[1] - a[1]) * f,
    a[2] + (b[2] - a[2]) * f,
  );
}

/**
 * Generate an array of hex color strings from a named ColorBrewer color scale.
 * Pass reversed=true to get the reverse of the normal color order (e.g. dark-low vs dark-high).
 *
 * Unknown ramp names fall back to YlOrRd — this includes 'Inferno' and
 * 'Plasma' from SEQUENTIAL_RAMPS, faithfully preserving the pre-#448
 * behavior (chroma-js has no brewer entry for either, so the old
 * try/catch already served YlOrRd for them).
 */
export function getRampColors(rampName: string, count: number, reversed = false): string[] {
  const stops = BREWER_STOPS[rampName] ?? BREWER_STOPS.YlOrRd;
  const colors =
    count === 1
      ? [sampleStops(stops, 0.5)]
      : Array.from({ length: count }, (_, i) => sampleStops(stops, i / (count - 1)));
  return reversed ? reverseRamp(colors) : colors;
}

/**
 * Build a MapLibre categorical (match) expression.
 * Returns: ['match', ['get', column], val1, color1, val2, color2, ..., fallback]
 */
export function buildCategoricalExpression(
  column: string,
  valueColorMap: [unknown, string][],
  fallback: string,
): unknown[] {
  const pairs: unknown[] = [];
  for (const [value, color] of valueColorMap) {
    pairs.push(value, color);
  }
  const matchExpr = ['match', ['get', column], ...pairs, fallback];
  return ['case', ['==', ['get', column], null], fallback, matchExpr];
}

/**
 * Build a MapLibre graduated (step) expression.
 * Returns: ['step', ['get', column], colors[0], breaks[0], colors[1], ..., breaks[n-1], colors[n]]
 * Requires colors.length === breaks.length + 1
 */
export function buildGraduatedExpression(
  column: string,
  breaks: number[],
  colors: string[],
): unknown[] {
  if (colors.length !== breaks.length + 1) {
    throw new Error(
      `colors.length (${colors.length}) must equal breaks.length + 1 (${breaks.length + 1})`,
    );
  }

  const step: unknown[] = ['step', ['get', column], colors[0]];
  for (let i = 0; i < breaks.length; i++) {
    step.push(breaks[i], colors[i + 1]);
  }
  return ['case', ['==', ['get', column], null], '#cccccc', step];
}

/**
 * Return the MapLibre paint property name for coloring based on geometry type.
 */
export function getColorProperty(geometryType: string | null): string {
  // builder-audit #338 ADAPT-02/DRY-05: derive from the single classifyGeometry scanner.
  switch (classifyGeometry(geometryType)) {
    case 'point':
      return 'circle-color';
    case 'line':
      return 'line-color';
    default:
      return 'fill-color';
  }
}

/**
 * Build a MapLibre graduated (step) expression for numeric size properties.
 * Identical shape to buildGraduatedExpression but with numeric sizes instead of color strings.
 * Returns: ['step', ['get', column], sizes[0], breaks[0], sizes[1], ..., breaks[n-1], sizes[n]]
 * Requires sizes.length === breaks.length + 1
 */
export function buildGraduatedSizeExpression(
  column: string,
  breaks: number[],
  sizes: number[],
): unknown[] {
  if (sizes.length !== breaks.length + 1) {
    throw new Error(
      `sizes.length (${sizes.length}) must equal breaks.length + 1 (${breaks.length + 1})`,
    );
  }

  const expr: unknown[] = ['step', ['get', column], sizes[0]];
  for (let i = 0; i < breaks.length; i++) {
    expr.push(breaks[i], sizes[i + 1]);
  }
  // Guard null values: render at 0 size (invisible) instead of minimum size
  return ['case', ['==', ['get', column], null], 0, expr];
}

/**
 * Return the MapLibre paint property name for size-based styling, or null if not applicable.
 * Point + radius -> 'circle-radius'
 * Line + width -> 'line-width'
 * Everything else -> null (polygons have no size property; 'color' target returns null)
 */
export function getSizeProperty(
  geometryType: string | null,
  target: 'color' | 'radius' | 'width',
): string | null {
  if (!geometryType || target === 'color') return null;

  const gt = geometryType.toLowerCase().replace('multi', '');
  if (target === 'radius' && gt.includes('point')) return 'circle-radius';
  if (target === 'width' && (gt.includes('line') || gt.includes('linestring'))) return 'line-width';
  return null;
}
