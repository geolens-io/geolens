/**
 * builder-audit DUP-04: shared typed paint accessors.
 *
 * These two trivial readers were previously copy-pasted verbatim in
 * RasterLayerControls and DEMEditorScene. They live here as the single
 * source so both raster/DEM editor surfaces read paint identically.
 */
export function getNumberPaint(
  paint: Record<string, unknown>,
  key: string,
  fallback: number,
): number {
  return typeof paint[key] === 'number' ? (paint[key] as number) : fallback;
}

export function getStringPaint(
  paint: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  return typeof paint[key] === 'string' ? (paint[key] as string) : fallback;
}
