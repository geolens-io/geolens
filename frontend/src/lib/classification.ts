/**
 * Compute equal-interval class breaks.
 * Returns classCount - 1 break values evenly spaced between min and max,
 * rounded to 2 decimal places.
 */
export function equalIntervalBreaks(
  min: number,
  max: number,
  classCount: number,
): number[] {
  if (classCount < 2) return [];
  const step = (max - min) / classCount;
  const breaks: number[] = [];
  for (let i = 1; i < classCount; i++) {
    breaks.push(Math.round((min + step * i) * 100) / 100);
  }
  return breaks;
}

/**
 * Pass through quantile values from the API (already computed server-side).
 * Thin wrapper for semantic clarity and to keep a consistent module API.
 */
export function quantileBreaks(quantiles: number[]): number[] {
  return quantiles;
}
