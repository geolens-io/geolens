import { viewportPreviewBbox } from '../AnalysisPanel';

/**
 * fix(#727 codex P2 round 1): `map.getBounds()` is MONOTONIC and UNWRAPPED —
 * MapLibre takes min/max over the four raw corner longitudes, so an
 * antimeridian-straddling viewport or a pan through extra world copies
 * (`renderWorldCopies` is on by default) returns values like `[179.5, 182]`
 * or `[899.5, 902]`, both numerically west < east and both OUTSIDE the
 * `[-180, 180]` range `geom_4326` actually stores. Sending those straight to
 * `ST_MakeEnvelope` silently misses real on-screen data instead of scoping to
 * it — worse than sending no bbox at all, since it looks scoped and isn't.
 *
 * `viewportPreviewBbox` is the guard: it returns `undefined` (no bbox, this
 * panel's pre-#727 whole-dataset behaviour) for exactly the viewports that
 * cannot be expressed as one valid, non-crossing `[minx, miny, maxx, maxy]`
 * envelope, and returns a normalized in-range envelope for every other case.
 */
function bounds(west: number, south: number, east: number, north: number) {
  return {
    getWest: () => west,
    getSouth: () => south,
    getEast: () => east,
    getNorth: () => north,
  };
}

describe('viewportPreviewBbox', () => {
  it('passes through an ordinary in-range viewport unchanged', () => {
    expect(viewportPreviewBbox(bounds(-74.1, 40.6, -73.9, 40.8))).toEqual([
      -74.1, 40.6, -73.9, 40.8,
    ]);
  });

  it('normalizes a viewport unwrapped past +180 into range', () => {
    // A real antimeridian-straddling viewport MapLibre reports as
    // monotonic — the repository's own documented example
    // (terrain-coverage.ts): west=179.5, east=182 is genuinely 2.5° wide,
    // straddling the seam, and wraps to [179.5, -178] — which correctly
    // reports as crossing (west > east) and cannot be one envelope.
    expect(viewportPreviewBbox(bounds(179.5, -10, 182, 10))).toBeUndefined();
  });

  it('normalizes a viewport panned through extra world copies', () => {
    // renderWorldCopies pans this two full turns east of the prime
    // meridian; wrapped it is an ordinary 2.5°-wide box at the seam and
    // still crosses it, so still undefined — but for the RIGHT reason
    // (crossing), not because the raw numbers looked wrong.
    expect(viewportPreviewBbox(bounds(899.5, -10, 902, 10))).toBeUndefined();
  });

  it('normalizes an ordinary viewport panned through one world copy', () => {
    // A pan that does NOT cross a seam still comes back unwrapped
    // (360-410 instead of 0-50); the normalized box must be the same one a
    // pan of zero world copies would have produced.
    expect(viewportPreviewBbox(bounds(360, 10, 370, 20))).toEqual([0, 10, 10, 20]);
  });

  it('returns undefined for a whole-world (or wider) viewport', () => {
    expect(viewportPreviewBbox(bounds(-180, -85, 180, 85))).toBeUndefined();
    expect(viewportPreviewBbox(bounds(-200, -85, 200, 85))).toBeUndefined();
  });

  it('returns undefined for a genuinely seam-crossing normalized viewport', () => {
    // Already in range on both ends, but decreasing: e.g. Fiji expressed in
    // the RFC 7946 spec form (west=178, east=-178) rather than the monotonic
    // form MapLibre's own getBounds() always returns. Caught by the
    // monotonicity guard (rawEast >= rawWest), not the west/east comparison
    // the pre-round-4 version used — this input is outside what a real
    // MapLibre bounds object can produce, so degrading to "no bbox" is the
    // same safe answer either way.
    expect(viewportPreviewBbox(bounds(178, -20, -178, -15))).toBeUndefined();
  });

  it('normalizes a non-crossing viewport that starts exactly at the seam (#727 codex P3 round 4)', () => {
    // The bug: [180, 190] is a genuinely representable 10°-wide box —
    // equivalent to [-180, -170], entirely on the western side of the seam —
    // but the old wrap() kept west at +180 (already "in range" by its own
    // inclusive check) while independently wrapping east down to -170,
    // manufacturing a false west > east crossing out of a box that never had
    // one and silently falling back to the whole dataset.
    expect(viewportPreviewBbox(bounds(180, -10, 190, 10))).toEqual([-180, -10, -170, 10]);
  });

  it('keeps [170, 180] a valid non-crossing interval (#727 codex P3 round 4)', () => {
    // The case the round-4 fix has to NOT break while fixing the one above:
    // a box that legitimately ends exactly at +180 without crossing it.
    expect(viewportPreviewBbox(bounds(170, -10, 180, 10))).toEqual([170, -10, 180, 10]);
  });
});
