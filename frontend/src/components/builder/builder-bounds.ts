import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';

// fix(#1877): this file must import nothing from BuilderMap.tsx — a static
// import from it defeats MapBuilderPage's `lazy(() => import(BuilderMap))`
// code-split boundary.

export type VisibleLayerBounds = [[number, number], [number, number]];

/** Merges every visible layer's bbox into one box, unwrapping an
 * antimeridian crossing (west > east) rather than dropping it (fix #903). */
export function getVisibleLayerBounds(layers: MapLayerResponse[]): VisibleLayerBounds | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let hasBounds = false;

  for (const layer of layers) {
    const bbox = layer.visible ? layer.dataset_extent_bbox : null;
    if (
      !Array.isArray(bbox) ||
      bbox.length !== 4 ||
      bbox.some((value) => !Number.isFinite(value)) ||
      bbox[1] > bbox[3]
    ) {
      continue;
    }

    // fix(#903): unwrap a `west > east` pair past 180 rather than dropping
    // it — MapLibre normalizes the result, so a seam-crossing layer still
    // fits the few degrees it occupies.
    let west = bbox[0];
    let east = bbox[0] > bbox[2] ? bbox[2] + 360 : bbox[2];

    // Try all three turns of the globe the merged interval could sit on and
    // keep whichever yields the smallest span (fix #903) — comparing west
    // edges alone is not sufficient to find it.
    if (hasBounds) {
      let bestSpan = Infinity;
      let bestShift = 0;
      for (const shift of [-360, 0, 360]) {
        const span =
          Math.max(maxX, east + shift) - Math.min(minX, west + shift);
        if (span < bestSpan) {
          bestSpan = span;
          bestShift = shift;
        }
      }
      west += bestShift;
      east += bestShift;
    }

    hasBounds = true;
    if (west < minX) minX = west;
    if (bbox[1] < minY) minY = bbox[1];
    if (east > maxX) maxX = east;
    if (bbox[3] > maxY) maxY = bbox[3];
  }

  if (!hasBounds) return null;
  // No union of longitude intervals can exceed 360° — clamp here so a
  // seam-crossing layer added to a world-spanning one can't widen the key
  // past the world bounds it started from (fix #903).
  if (maxX - minX >= 360) {
    minX = -180;
    maxX = 180;
  }
  return [[minX, minY], [maxX, maxY]];
}

/** Comparable string for a bounds value — cheap equality check for effect deps. */
export function visibleLayerBoundsKey(bounds: VisibleLayerBounds | null): string {
  return bounds
    ? `${bounds[0][0]},${bounds[0][1]},${bounds[1][0]},${bounds[1][1]}`
    : '';
}

/** A wide bounds fit can land below zoom 2, where complex vector tiles fail
 * to render (ST_AsMVT). Call right after any fitBounds to a merged extent. */
export function clampMinZoomAfterFit(map: Pick<MaplibreMap, 'getZoom' | 'setZoom'>): void {
  if (map.getZoom() < 2) {
    map.setZoom(2);
  }
}
