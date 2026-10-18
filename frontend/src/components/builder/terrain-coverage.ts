import { toast } from 'sonner';
import i18n from '@/i18n/i18n';

/** Minimal shape we read off MapLibre's LngLatBounds (only the four edges). */
interface BoundsLike {
  getWest(): number;
  getSouth(): number;
  getEast(): number;
  getNorth(): number;
}

/** Minimal map surface the coverage guard needs — just the current viewport. */
interface MapWithBounds {
  getBounds(): BoundsLike;
}

/**
 * Small-DEM viewport guard.
 *
 * A high-resolution DEM with a small footprint (e.g. swissALTI3D over a single
 * AOI) covers only a sliver of a zoomed-out viewport. With terrain enabled the
 * user sees a tiny raised patch on flat ground, and with edge nodata what looks
 * like a "pedestal". A non-blocking warning recommends draping the high-res DEM
 * over a coarse global DEM (Copernicus GLO-30) for small AOIs, or zooming in.
 *
 * Coverage = (DEM bounds ∩ viewport area) / viewport area, in the lng/lat
 * degree plane. This ignores Mercator area distortion, which is fine for a UX
 * threshold.
 *
 * `demBounds` sources differ by call site. BuilderMap passes the DEM layer's
 * `dataset_extent_bbox`, in the RFC 7946 §5.2 form, so a seam-crossing
 * footprint arrives as a `west > east` pair with its real width intact. The
 * tile token's `bounds` (`RasterTileToken.bounds`, from `extent_to_span_bbox` in
 * processing/tiles/router.py) widens a crossing extent to exactly
 * [-180, s, 180, n], indistinguishable from a global DEM (see `lonOverlap`), so
 * it is only the fallback for a layer with no extent. use-viewer-terrain passes
 * the token bounds because `SharedLayerResponse` has no extent field, which is
 * harmless: it passes `audience: 'viewer'`, which returns before `demBounds` is
 * read.
 *
 * The seam still matters for the viewport rectangle. `map.getBounds()` is
 * monotonic (min/max over four unwrapped corner longitudes) but runs past ±180
 * when the viewport straddles the antimeridian, e.g. `[179.5, …, 182, …]`. A
 * planar `Math.min(ve, demEast)` would clip the DEM at +180 and fire the
 * "small DEM" toast for a DEM covering the whole screen. So longitude is
 * measured on the circle: each rectangle becomes an unwrapped interval (a
 * crossing pair unwraps past 180) and the DEM is scored as the repeating
 * pattern it is. Latitude needs none of this.
 */

/** Default coverage threshold below which the warning fires. */
export const SMALL_DEM_COVERAGE_THRESHOLD = 0.25;

type Bounds4 = [number, number, number, number]; // [west, south, east, north]

function isFiniteBounds4(bounds: number[] | null | undefined): bounds is Bounds4 {
  return Array.isArray(bounds)
    && bounds.length === 4
    && bounds.every((v) => Number.isFinite(v))
    // West may exceed east: that is the RFC 7946 §5.2 encoding of a crossing
    // box, not a malformed one. Only a zero-width longitude span is degenerate.
    && bounds[0] !== bounds[2]
    && bounds[1] < bounds[3];
}

/** A longitude pair as an increasing interval, unwrapping a seam-crossing pair
 *  past 180 (`[178.5, -178.5]` → `[178.5, 181.5]`). */
function lonInterval(west: number, east: number): [number, number] {
  return [west, east < west ? east + 360 : east];
}

/**
 * Length of the repeating DEM covered between the DEM's own west edge and `t`
 * degrees east of it, where the DEM is `width` wide and repeats every 360.
 *
 * Whole turns contribute a full `width` each; the partial turn contributes how
 * far into it the DEM reaches. Defined for negative `t` too, since the viewport
 * can sit west of the DEM's west edge. Continuous across turn boundaries
 * (`q * width + width` from below, `(q + 1) * width + 0` from above), so float
 * noise near a boundary can't jump the result by a period.
 */
function coveredLength(t: number, width: number): number {
  const turns = Math.floor(t / 360);
  return turns * width + Math.min(t - turns * 360, width);
}

/**
 * Longitudinal overlap of the DEM with the viewport, measured on the circle.
 *
 * Turns are not enumerated: `renderWorldCopies` is on by default, so
 * `getBounds()` runs further out as the user pans (a Fiji DEM can be viewed at
 * `[899.5, 902]`, two whole turns east), and any fixed shift list eventually
 * reports zero coverage for a DEM that fills the screen. The DEM is a pattern
 * repeating every 360 degrees; `coveredLength` measures it from the DEM's west
 * edge to any point, and the overlap is that measured at the viewport's two
 * edges and subtracted. Exact for any pan distance at constant cost, and it
 * can't exceed the viewport width because `coveredLength` grows at most 1:1
 * with its argument.
 */
function lonOverlap(dem: [number, number], view: [number, number]): number {
  const demWidth = dem[1] - dem[0];
  // A DEM spanning the globe covers every longitude, at every pan distance.
  //
  // A seam-crossing DEM must not reach this branch: `extent_to_span_bbox`
  // widens a crossing extent to exactly [-180, s, 180, n], the same value a
  // genuinely global raster produces, so the footprint would be lost and this
  // would answer "global" and under-warn (a Fiji footprint in viewport
  // [179.5, -20, 190, -15] is truly 19% covered). BuilderMap therefore passes
  // `dataset_extent_bbox`, so the crossing case arrives as [178.5, …, -178.5, …]
  // (3 degrees wide) and is scored correctly below. What is left here is a DEM
  // that really wraps the world. Don't point the builder back at the token span.
  if (demWidth >= 360) return view[1] - view[0];
  return Math.max(
    0,
    coveredLength(view[1] - dem[0], demWidth) - coveredLength(view[0] - dem[0], demWidth),
  );
}

/**
 * Fraction of the viewport covered by the DEM bounds, in [0, 1]. Returns `null`
 * when either rectangle is degenerate/unknown, so the caller doesn't warn: only
 * a confident small-coverage signal warns.
 */
export function demViewportCoverage(
  demBounds: number[] | null | undefined,
  viewport: number[] | null | undefined,
): number | null {
  if (!isFiniteBounds4(demBounds) || !isFiniteBounds4(viewport)) return null;

  const [vw, vs, ve, vn] = viewport;
  const view = lonInterval(vw, ve);
  const viewWidth = view[1] - view[0];
  const viewportArea = viewWidth * (vn - vs);
  if (!(viewportArea > 0)) return null;

  const ix = lonOverlap(lonInterval(demBounds[0], demBounds[2]), view);
  const iy = Math.max(0, Math.min(vn, demBounds[3]) - Math.max(vs, demBounds[1]));
  const intersection = ix * iy;

  return Math.max(0, Math.min(1, intersection / viewportArea));
}

/** Whether the small-DEM warning should fire. Pure so the threshold is testable
 *  without a live map. */
export function shouldWarnSmallDemCoverage(
  demBounds: number[] | null | undefined,
  viewport: number[] | null | undefined,
  threshold = SMALL_DEM_COVERAGE_THRESHOLD,
): boolean {
  const coverage = demViewportCoverage(demBounds, viewport);
  if (coverage == null) return false;
  return coverage < threshold;
}

function boundsToArray(b: BoundsLike): Bounds4 {
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
}

/**
 * Per-map dedupe key store: warn at most once per (map, terrain dataset) until
 * the terrain is disabled or a different DEM is selected, so pans/zooms/syncs
 * don't re-fire it.
 */
const warnedKeys = new WeakMap<object, Set<string>>();

function keyStore(map: object): Set<string> {
  let store = warnedKeys.get(map);
  if (!store) {
    store = new Set<string>();
    warnedKeys.set(map, store);
  }
  return store;
}

/**
 * Reset the dedupe state for a map; call when terrain is disabled or the source
 * DEM changes so the warning can fire again for a genuinely new enable.
 */
export function resetSmallDemWarning(map: object, activeKey?: string | null): void {
  const store = keyStore(map);
  if (activeKey) {
    // Keep only the still-active key, so toggling between two DEMs re-warns for
    // each but a no-op re-sync of the same DEM stays quiet.
    for (const k of [...store]) {
      if (k !== activeKey) store.delete(k);
    }
  } else {
    store.clear();
  }
}

/**
 * Emit the small-DEM coverage warning toast once per (map, dedupeKey) when the
 * active terrain DEM covers less than `threshold` of the viewport.
 *
 * `dedupeKey` should encode the terrain dataset id so switching DEMs re-warns.
 * Safe on every terrain-apply pass: the WeakMap dedupe makes repeat calls for
 * the same active DEM no-ops.
 */
export function maybeWarnSmallDemCoverage(args: {
  map: MapWithBounds;
  demBounds: number[] | null | undefined;
  dedupeKey: string;
  threshold?: number;
  /**
   * The warning's copy ("zoom in", "drape it over a coarse global DEM") is
   * builder-actionable advice that anonymous/read-only viewers can't act on.
   * `'viewer'` suppresses the toast for that audience. Defaults to `'builder'`.
   */
  audience?: 'builder' | 'viewer';
}): boolean {
  const { map, demBounds, dedupeKey, audience = 'builder' } = args;
  const threshold = args.threshold ?? SMALL_DEM_COVERAGE_THRESHOLD;

  // Viewer sessions never see this builder-oriented advice toast.
  if (audience === 'viewer') return false;

  let viewport: number[] | null = null;
  try {
    viewport = boundsToArray(map.getBounds());
  } catch {
    return false;
  }

  if (!shouldWarnSmallDemCoverage(demBounds, viewport, threshold)) return false;

  const store = keyStore(map as object);
  if (store.has(dedupeKey)) return false;
  store.add(dedupeKey);

  toast.warning(i18n.t('builder:terrain.smallDemWarning'), {
    id: `small-dem-${dedupeKey}`,
    duration: 8000,
  });
  return true;
}
