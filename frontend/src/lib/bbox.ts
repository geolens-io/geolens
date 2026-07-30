// fix(#903): the frontend's shared antimeridian-aware bbox helpers.
//
// The backend can now hold an extent that crosses the antimeridian as a
// two-ring MULTIPOLYGON, and `extent_to_bbox()` reports it in the RFC 7946
// §5.2 / STAC **spec form**: `west > east` (e.g. Fiji, `[178.5, -20, -178.5,
// -15]`). Nothing on the frontend understood that, so `core/geo.py` routes six
// map-facing consumers through `extent_to_span_bbox()` instead, which returns a
// monotonic `-180..180`. That fallback is honest but over-broad: a Fiji dataset
// reports the whole world.
//
// These helpers mirror the backend split so each call site declares which form
// it wants instead of assuming `minx < maxx`. They do not change what the API
// sends today — they are what has to exist before the backend can flip a
// consumer back to the spec form (see the issue's sequencing: #934, then this,
// then one consumer at a time).

export type Bbox = [number, number, number, number];

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
 * crossing bbox widens to full `-180..180`. For consumers that can only accept
 * one increasing box and have no way to express two — a MapLibre source
 * `bounds`, most obviously, where an inverted pair matches no tile at all and
 * the layer renders blank. Over-broad, but safe; the alternative there is
 * nothing rendering.
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
 * lands on the ANTIPODE of a seam-crossing extent — a confident fly-to on the
 * opposite side of the planet, which is why this is a helper and not an inline
 * average.
 */
export function bboxCenterLon(bbox: Bbox): number {
  const center = bbox[0] + bboxLonSpan(bbox) / 2;
  return center > 180 ? center - 360 : center;
}

/**
 * The corner pair MapLibre's `fitBounds` / `initialViewState.bounds` wants.
 * MapLibre normalizes longitudes itself, so a crossing bbox is expressed by
 * letting east run past 180 (`[178.5, …] → [181.5, …]`) rather than by
 * splitting — it then fits the ~3° that Fiji occupies instead of skipping the
 * fit or flying to the far side of the world.
 */
export function toFitBounds(bbox: Bbox): [[number, number], [number, number]] {
  const [west, south, east, north] = bbox;
  return [
    [west, south],
    [crossesAntimeridian(bbox) ? east + 360 : east, north],
  ];
}
