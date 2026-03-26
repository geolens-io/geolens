/**
 * Compute a center + zoom view for a bbox that is too large for fitBounds
 * (large extents cause z0/z1 tile errors with complex geometries).
 */
export function computeLargeExtentView(bbox: [number, number, number, number]) {
  const [minx, miny, maxx, maxy] = bbox;
  const lonSpan = maxx - minx;
  const latSpan = maxy - miny;
  const zoomForLon = Math.log2(360 / Math.max(lonSpan, 1));
  const zoomForLat = Math.log2(170 / Math.max(latSpan, 1));
  const zoom = Math.max(1, Math.round(Math.min(zoomForLon, zoomForLat)));
  return {
    center: [(minx + maxx) / 2, Math.max(-60, Math.min(60, (miny + maxy) / 2))] as [number, number],
    zoom,
  };
}

/** Check whether a bbox spans a large enough area that fitBounds should be avoided */
export function isLargeExtent(bbox: [number, number, number, number]) {
  const [minx, miny, maxx, maxy] = bbox;
  return (maxx - minx > 90 || maxy - miny > 60);
}
