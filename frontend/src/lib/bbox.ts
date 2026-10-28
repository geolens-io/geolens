// The frontend's shared antimeridian-aware bbox helpers.
//
// The backend can hold an extent that crosses the antimeridian as a
// two-ring MULTIPOLYGON, and `extent_to_bbox()` reports it in the RFC 7946
// §5.2 / STAC **spec form**: `west > east` (e.g. Fiji, `[178.5, -20, -178.5,
// -15]`). `core/geo.py` also offers `extent_to_span_bbox()`, which returns a
// monotonic `-180..180`; that form is honest but over-broad (a Fiji dataset
// reports the whole world).
//
// These helpers mirror the backend split so each call site declares which form
// it wants instead of assuming `minx < maxx`.

export type Bbox = [number, number, number, number];

// MapLibre's globe fit returns no camera for a zero-size box.
const POINT_FIT_HALF_SPAN = 5e-8;

/**
 * True for a bbox in the spec form — `west > east`, i.e. it crosses the
 * antimeridian. NOT a validity check: a malformed pair is indistinguishable
 * from a seam-crossing one by design (that is what RFC 7946 §5.2 chose), so
 * callers that need validation must do it before asking.
 */
export function crossesAntimeridian(bbox: Bbox): boolean {
  return bbox[0] > bbox[2];
}

/**
 * The two non-crossing halves of a seam-crossing bbox, west half first; a
 * one-element array for anything that does not cross. For consumers that can
 * draw or test more than one rectangle (GeoJSON rings, SVG rects).
 */
export function splitBbox(bbox: Bbox): Bbox[] {
  const [west, south, east, north] = bbox;
  if (!crossesAntimeridian(bbox)) return [bbox];
  return [
    [west, south, 180, north],
    [-180, south, east, north],
  ];
}

/**
 * The monotonic form, mirroring the backend's `extent_to_span_bbox()`: a
 * crossing bbox widens to full `-180..180`. For consumers that accept only one
 * increasing box, e.g. a MapLibre source `bounds`, where an inverted pair
 * matches no tile and the layer renders blank. Over-broad, but safe.
 */
export function toSpanBbox(bbox: Bbox): Bbox {
  if (!crossesAntimeridian(bbox)) return bbox;
  return [-180, bbox[1], 180, bbox[3]];
}

/**
 * Longitude span in degrees, measured the short way round the circle, so a
 * seam-crossing bbox reports the ~3° it actually covers instead of the -357°
 * that `maxx - minx` yields.
 */
export function bboxLonSpan(bbox: Bbox): number {
  const [west, , east] = bbox;
  return crossesAntimeridian(bbox) ? east + 360 - west : east - west;
}

/**
 * Center longitude, wrapped back into `-180..180`. The naive `(minx + maxx) / 2`
 * lands on the ANTIPODE of a seam-crossing extent.
 */
export function bboxCenterLon(bbox: Bbox): number {
  const center = bbox[0] + bboxLonSpan(bbox) / 2;
  return center > 180 ? center - 360 : center;
}

/**
 * The corner pair MapLibre's `fitBounds` / `initialViewState.bounds` wants.
 * MapLibre normalizes longitudes itself, so a crossing bbox is expressed by
 * letting east run past 180 (`[178.5, …] → [181.5, …]`) rather than by
 * splitting. A single point widens to a box about a centimetre across.
 */
export function toFitBounds(bbox: Bbox): [[number, number], [number, number]] {
  const [west, south, east, north] = bbox;
  if (west === east && south === north) {
    return [
      [west - POINT_FIT_HALF_SPAN, Math.max(-90, south - POINT_FIT_HALF_SPAN)],
      [east + POINT_FIT_HALF_SPAN, Math.min(90, north + POINT_FIT_HALF_SPAN)],
    ];
  }
  return [
    [west, south],
    [crossesAntimeridian(bbox) ? east + 360 : east, north],
  ];
}

/**
 * The map wraps around, so a box drawn across the antimeridian carries
 * longitudes beyond +/-180. The search API reads west > east as a crossing box.
 */
export function normalizeBboxLongitudes(bbox: string): string {
  const [minX, minY, maxX, maxY] = bbox.split(',').map(Number);
  if (maxX - minX >= 360) return `-180,${minY},180,${maxY}`;
  const wrap = (lng: number) =>
    lng >= -180 && lng <= 180
      ? lng
      : Math.round(((((lng + 180) % 360) + 360) % 360 - 180) * 1e9) / 1e9;
  const west = wrap(minX);
  // A box whose east edge is the seam itself ends at +180, not -180.
  const east = wrap(maxX) === -180 && maxX > minX ? 180 : wrap(maxX);
  return `${west},${minY},${east},${maxY}`;
}
