import chroma from 'chroma-js';

// --- Curated palette definitions ---

export const SEQUENTIAL_RAMPS = [
  { name: 'YlOrRd', label: 'Yellow-Orange-Red' },
  { name: 'YlGnBu', label: 'Yellow-Green-Blue' },
  { name: 'Viridis', label: 'Viridis' },
  { name: 'Blues', label: 'Blues' },
  { name: 'Greens', label: 'Greens' },
  { name: 'Oranges', label: 'Oranges' },
  { name: 'Purples', label: 'Purples' },
] as const;

export const DIVERGING_RAMPS = [
  { name: 'RdYlBu', label: 'Red-Yellow-Blue' },
  { name: 'RdYlGn', label: 'Red-Yellow-Green' },
  { name: 'BrBG', label: 'Brown-BlueGreen' },
  { name: 'PiYG', label: 'Pink-YellowGreen' },
] as const;

export const QUALITATIVE_RAMPS = [
  { name: 'Set2', label: 'Set 2' },
  { name: 'Set3', label: 'Set 3' },
  { name: 'Paired', label: 'Paired' },
  { name: 'Dark2', label: 'Dark 2' },
] as const;

/**
 * Generate an array of hex color strings from a named chroma-js color scale.
 */
export function getRampColors(rampName: string, count: number): string[] {
  return chroma.scale(rampName as chroma.BrewerPaletteName).colors(count);
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
  const expr: unknown[] = ['match', ['get', column]];
  for (const [value, color] of valueColorMap) {
    expr.push(value, color);
  }
  expr.push(fallback);
  return expr;
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

  const expr: unknown[] = ['step', ['get', column], colors[0]];
  for (let i = 0; i < breaks.length; i++) {
    expr.push(breaks[i], colors[i + 1]);
  }
  return expr;
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
