/**
 * Shared typed paint accessors: the single source so the raster and DEM editor
 * surfaces (RasterLayerControls, DEMEditorScene) read paint identically.
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
