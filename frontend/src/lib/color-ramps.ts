import chroma from 'chroma-js';
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

/**
 * Generate an array of hex color strings from a named chroma-js color scale.
 * Pass reversed=true to get the reverse of the normal color order (e.g. dark-low vs dark-high).
 */
export function getRampColors(rampName: string, count: number, reversed = false): string[] {
  try {
    const colors = chroma.scale(rampName as chroma.BrewerPaletteName).colors(count);
    return reversed ? reverseRamp(colors) : colors;
  } catch {
    // Fallback for unknown ramp names
    return chroma.scale('YlOrRd').colors(count);
  }
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
  // builder-audit ADAPT-02/DRY-05: derive from the single classifyGeometry scanner.
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
