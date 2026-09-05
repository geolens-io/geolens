import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';

// fix(#1877 codex round 3): moved out of BuilderMap.tsx — a hook needed this
// pure merge, and a static import of ANY export from BuilderMap.tsx defeats
// MapBuilderPage.tsx's `lazy(() => import('@/components/builder/BuilderMap'))`
// split (Vite reports INEFFECTIVE_DYNAMIC_IMPORT and folds the map renderer,
// MapLibre GL and its worker/CSS side effects into the eager entry chunk).
// This file has no such import anywhere, so it stays safely shareable.

export type VisibleLayerBounds = [[number, number], [number, number]];

/**
 * Merges every visible layer's dataset_extent_bbox into one bounding box,
 * unwrapping an antimeridian-crossing layer (west > east) past 180 rather
 * than dropping it, and picking whichever of three global placements keeps
 * the merged span smallest (fix #903).
 */
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

    // fix(#903): a `west > east` pair used to be dropped here, which made both
    // fit paths and Zoom to Layer silent no-ops for a seam-crossing layer.
    // Unwrap it past 180 instead — MapLibre normalizes the result, so a single
    // crossing layer now fits the few degrees it occupies.
    let west = bbox[0];
    let east = bbox[0] > bbox[2] ? bbox[2] + 360 : bbox[2];

    // Then place the interval on whichever turn of the globe makes the merged
    // extent SMALLEST. Comparing west edges alone was not enough in either
    // direction: a crossing layer beside a non-crossing one across the seam
    // ([178, -178] + [-179, -177]) merged to a 361° span for a ~5° union, and a
    // world-wide layer followed by a contained one ([-180, 180] + [10, 20])
    // pushed the contained layer a turn away into a 530° span. Three candidates
    // is the whole search space — a longitude interval has no other placement.
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
  // No union of longitude intervals can be wider than the circle itself, so a
  // merged span past 360° means the layers already cover the world and the
  // placement search had nothing better to pick. Without this, adding a
  // seam-crossing layer to a world-spanning one produced [-180, 182] — a wider
  // key than the world bounds it started from, which moved the auto-fit for a
  // layer that expanded nothing.
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
