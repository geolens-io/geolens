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
 * longitudes beyond +/-180. Wraps them into [-180, 180]; a crossing box comes
 * back with west > east, which the search and aggregate APIs read as one.
 */
export function wrapBboxLongitudes([minX, minY, maxX, maxY]: Bbox): Bbox {
  if (maxX - minX >= 360) return [-180, minY, 180, maxY];
  const wrap = (lng: number) =>
    lng >= -180 && lng <= 180
      ? lng
      : Math.round(((((lng + 180) % 360) + 360) % 360 - 180) * 1e9) / 1e9;
  const west = wrap(minX);
  // A box whose east edge is the seam itself ends at +180, not -180.
  const east = wrap(maxX) === -180 && maxX > minX ? 180 : wrap(maxX);
  return [west, minY, east, maxY];
}

/** `wrapBboxLongitudes` for a `minx,miny,maxx,maxy` string. */
export function normalizeBboxLongitudes(bbox: string): string {
  return wrapBboxLongitudes(bbox.split(',').map(Number) as Bbox).join(',');
}

/**
 * Envelope of one GeoJSON geometry as [west, south, east, north]. Collections
 * fold member-by-member, recursing into nested collections; null when no
 * coordinate is finite.
 */
export function geometryBounds(
  geometry: GeoJSON.Geometry | null | undefined,
): Bbox | null {
  if (!geometry) return null;

  let west = Number.POSITIVE_INFINITY;
  let south = Number.POSITIVE_INFINITY;
  let east = Number.NEGATIVE_INFINITY;
  let north = Number.NEGATIVE_INFINITY;

  const visitCoordinates = (value: unknown) => {
    if (!Array.isArray(value)) return;
    if (
      value.length >= 2
      && typeof value[0] === 'number'
      && typeof value[1] === 'number'
      && Number.isFinite(value[0])
      && Number.isFinite(value[1])
    ) {
      west = Math.min(west, value[0]);
      east = Math.max(east, value[0]);
      south = Math.min(south, value[1]);
      north = Math.max(north, value[1]);
      return;
    }
    for (const item of value) visitCoordinates(item);
  };

  if (geometry.type === 'GeometryCollection') {
    for (const item of geometry.geometries) {
      const bounds = geometryBounds(item);
      if (!bounds) continue;
      west = Math.min(west, bounds[0]);
      south = Math.min(south, bounds[1]);
      east = Math.max(east, bounds[2]);
      north = Math.max(north, bounds[3]);
    }
  } else {
    visitCoordinates(geometry.coordinates);
  }

  return Number.isFinite(west) ? [west, south, east, north] : null;
}
