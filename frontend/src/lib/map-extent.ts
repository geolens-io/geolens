import { type Bbox, bboxCenterLon, bboxLonSpan } from '@/lib/bbox';

/**
 * Compute a center + zoom view for a bbox that is too large for fitBounds
 * (large extents cause z0/z1 tile errors with complex geometries).
 *
 * The longitude span and center come from the seam-aware helpers: plain
 * arithmetic gives a crossing bbox a negative span (swallowed by
 * `Math.max(lonSpan, 1)` into a world-wide zoom) and a center on the ANTIPODE.
 */
export function computeLargeExtentView(bbox: Bbox) {
  const [, miny, , maxy] = bbox;
  const lonSpan = bboxLonSpan(bbox);
  const latSpan = maxy - miny;
  const zoomForLon = Math.log2(360 / Math.max(lonSpan, 1));
  const zoomForLat = Math.log2(170 / Math.max(latSpan, 1));
  const zoom = Math.max(1, Math.round(Math.min(zoomForLon, zoomForLat)));
  return {
    center: [bboxCenterLon(bbox), Math.max(-60, Math.min(60, (miny + maxy) / 2))] as [number, number],
    zoom,
  };
}

/** Check whether a bbox spans a large enough area that fitBounds should be avoided.
 *
 * `maxx - minx` goes negative for a crossing bbox, which would read as small
 * and take the fitBounds path with an inverted pair. */
export function isLargeExtent(bbox: Bbox) {
  const [, miny, , maxy] = bbox;
  return (bboxLonSpan(bbox) > 90 || maxy - miny > 60);
}

/** A longitude span this wide draws its outline on every world copy as vertical lines. */
export function isWorldSpanningExtent(bbox: Bbox) {
  return bboxLonSpan(bbox) >= 350;
}
