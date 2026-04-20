import chroma from 'chroma-js';

// --- Curated palette definitions ---

export const SEQUENTIAL_RAMPS = [
  { name: 'YlOrRd', label: 'Yellow-Orange-Red' },
  { name: 'YlGnBu', label: 'Yellow-Green-Blue' },
  { name: 'Viridis', label: 'Viridis' },
  { name: 'Inferno', label: 'Inferno' },
  { name: 'Plasma', label: 'Plasma' },
  { name: 'Blues', label: 'Blues' },
  { name: 'Greens', label: 'Greens' },
  { name: 'Oranges', label: 'Oranges' },
  { name: 'Reds', label: 'Reds' },
  { name: 'Purples', label: 'Purples' },
  { name: 'BuGn', label: 'Blue-Green' },
  { name: 'BuPu', label: 'Blue-Purple' },
  { name: 'OrRd', label: 'Orange-Red' },
  { name: 'YlGn', label: 'Yellow-Green' },
] as const;

export const DIVERGING_RAMPS = [
  { name: 'RdYlBu', label: 'Red-Yellow-Blue' },
  { name: 'RdYlGn', label: 'Red-Yellow-Green' },
  { name: 'RdBu', label: 'Red-Blue' },
  { name: 'BrBG', label: 'Brown-BlueGreen' },
  { name: 'PiYG', label: 'Pink-YellowGreen' },
  { name: 'PRGn', label: 'Purple-Green' },
  { name: 'Spectral', label: 'Spectral' },
] as const;

export const QUALITATIVE_RAMPS = [
  { name: 'Set1', label: 'Set 1' },
  { name: 'Set2', label: 'Set 2' },
  { name: 'Set3', label: 'Set 3' },
  { name: 'Paired', label: 'Paired' },
  { name: 'Dark2', label: 'Dark 2' },
  { name: 'Accent', label: 'Accent' },
  { name: 'Pastel1', label: 'Pastel 1' },
  { name: 'Pastel2', label: 'Pastel 2' },
] as const;

/**
 * Generate an array of hex color strings from a named chroma-js color scale.
 */
export function getRampColors(rampName: string, count: number): string[] {
  try {
    return chroma.scale(rampName as chroma.BrewerPaletteName).colors(count);
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
  valueColorMap: [string, string][],
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
  if (!geometryType) return 'fill-color';

  const gt = geometryType.toLowerCase().replace('multi', '');
  if (gt.includes('line') || gt.includes('linestring')) return 'line-color';
  if (gt.includes('point')) return 'circle-color';
  return 'fill-color';
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
