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
 * Issue #186 (b): small-DEM viewport guard.
 *
 * A high-resolution DEM with a small footprint (e.g. swissALTI3D over a single
 * AOI) only covers a sliver of a zoomed-out viewport. When terrain is enabled
 * at that zoom the user sees a tiny raised patch surrounded by flat ground and
 * — combined with edge nodata — what looks like a "pedestal". We surface a
 * non-blocking warning recommending draping the high-res DEM over a coarse
 * global DEM (Copernicus GLO-30) for small AOIs, or zooming in.
 *
 * Coverage = (DEM bounds ∩ viewport area) / viewport area, computed in the
 * lng/lat degree plane. This is an approximation (it ignores Mercator area
 * distortion), which is fine for a UX threshold check.
 *
 * fix(#1128): where `demBounds` comes from, because it is easy to get wrong,
 * and it is no longer the same on both call sites.
 *
 * BuilderMap passes the DEM layer's `dataset_extent_bbox` — the RFC 7946 §5.2
 * spec form since #1112, so a seam-crossing footprint arrives as a `west > east`
 * pair with its real width intact. It used to pass the tile token's `bounds`
 * (`RasterTileToken.bounds`, built by `extent_to_span_bbox` at
 * processing/tiles/router.py), which widens a crossing extent to exactly
 * [-180, s, 180, n] and is therefore indistinguishable from a global DEM; see
 * `lonOverlap` below for what that cost. The token span survives only as the
 * fallback for a layer with no extent.
 *
 * use-viewer-terrain still passes the token bounds, because `SharedLayerResponse`
 * carries no extent field (maps/schemas.py) — and it does not matter: that call
 * site passes `audience: 'viewer'`, which returns below before `demBounds` is
 * ever read (#430 V-06). The viewer emits no coverage toast at all.
 *
 * The seam still matters, for the other rectangle. `map.getBounds()` is always
 * monotonic — MapLibre takes min/max over four UNWRAPPED corner longitudes —
 * but it runs past ±180 when the viewport straddles the antimeridian, e.g.
 * `[179.5, …, 182, …]`. A planar `Math.min(ve, demEast)` then clipped the DEM
 * at +180 and reported a fifth of the coverage a world-spanning DEM really
 * has, firing the "small DEM" toast for a DEM that covers the whole screen.
 * So the longitude axis is measured on the circle: each rectangle becomes an
 * unwrapped interval (a crossing pair unwraps past 180) and the DEM is scored
 * as the repeating pattern it is. Latitude needs none of this.
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
 * Whole turns contribute a full `width` each; the partial turn contributes
 * however far into it the DEM reaches. Defined for negative `t` too, because
 * the viewport can sit west of the DEM's west edge.
 *
 * Continuous across turn boundaries by construction: approaching a boundary
 * from below gives `q * width + width`, and from above `(q + 1) * width + 0`.
 * Float noise near a boundary therefore cannot jump the result by a period.
 */
function coveredLength(t: number, width: number): number {
  const turns = Math.floor(t / 360);
  return turns * width + Math.min(t - turns * 360, width);
}

/**
 * Longitudinal overlap of the DEM with the viewport, measured on the circle.
 *
 * fix(#1124 codex P2): this used to score the DEM against a fixed `[-360, 0,
 * 360]` shift list. `renderWorldCopies` is on by default, so `getBounds()` runs
 * further out the more the user pans and a Fiji DEM can legitimately be viewed
 * at `[899.5, 902]`, two whole turns east. A fixed list answers "how many
 * turns?" with a guess, and one pan past the last entry reported zero coverage
 * and warned about a DEM that fills the screen — the same class of bug this
 * function exists to fix, one level out.
 *
 * So don't enumerate turns at all. The DEM is a pattern repeating every 360
 * degrees, and `coveredLength` measures that pattern from the DEM's west edge
 * to any point; the overlap is that measured at the viewport's two edges and
 * subtracted. Exact for any pan distance, and the same cost at 2 turns as at
 * 2000. The result cannot exceed the viewport width because `coveredLength`
 * grows at most 1:1 with its argument.
 */
function lonOverlap(dem: [number, number], view: [number, number]): number {
  const demWidth = dem[1] - dem[0];
  // A DEM spanning the globe covers every longitude, at every pan distance.
  //
  // fix(#1128): this branch used to swallow every seam-crossing DEM too, and no
  // arithmetic here could have separated them. `extent_to_span_bbox`
  // (processing/tiles/router.py) widens a crossing extent to exactly
  // [-180, s, 180, n] — the same value a genuinely global raster produces — so
  // by the time the pair reached this function the footprint was already gone
  // and the branch had to guess. It guessed "global", which under-warned: a
  // Fiji footprint in viewport [179.5, -20, 190, -15] is truly 19% covered
  // (warn) and this returned 100% (silent). The pre-#1122 planar math happened
  // to return 4.8% and warn, but only as a side effect of the +180 clipping bug
  // that produced the far worse false alarm this module was changed to fix.
  //
  // The cure was a change of DATA SOURCE, not of this math: BuilderMap now
  // passes `dataset_extent_bbox`, so the crossing case arrives as
  // [178.5, …, -178.5, …] — a real 3 degrees wide, never reaching this branch,
  // and already scored at the correct 19% by the lines below. What is left here
  // is the honest case it was always right about: a DEM that really does wrap
  // the world. Do not point the builder back at the token span.
  if (demWidth >= 360) return view[1] - view[0];
  return Math.max(
    0,
    coveredLength(view[1] - dem[0], demWidth) - coveredLength(view[0] - dem[0], demWidth),
  );
}

/**
 * Fraction of the viewport covered by the DEM bounds, in [0, 1].
 * Returns `null` when either rectangle is degenerate/unknown (caller should
 * then NOT warn — we only warn on a confident small-coverage signal).
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

/**
 * Decide whether the small-DEM warning should fire.
 * Pure + exported so the threshold logic is unit testable without a live map.
 */
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
 * the terrain is disabled / a different DEM is selected. Prevents the warning
 * from re-firing on every pan/zoom/sync while the same small DEM stays active.
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
 * Reset the dedupe state for a map — call when terrain is disabled or the
 * source DEM changes so the warning can fire again for a genuinely new enable.
 */
export function resetSmallDemWarning(map: object, activeKey?: string | null): void {
  const store = keyStore(map);
  if (activeKey) {
    // Drop every key except the still-active one, so toggling between two DEMs
    // re-warns for each but a no-op re-sync of the same DEM stays quiet.
    for (const k of [...store]) {
      if (k !== activeKey) store.delete(k);
    }
  } else {
    store.clear();
  }
}

/**
 * Emit the small-DEM coverage warning toast once per (map, dedupeKey) when the
 * active terrain DEM covers less than `threshold` of the current viewport.
 *
 * `dedupeKey` should encode the terrain dataset id so switching DEMs re-warns.
 * Safe to call on every terrain-apply pass — the WeakMap dedupe makes repeat
 * calls for the same active DEM no-ops.
 */
export function maybeWarnSmallDemCoverage(args: {
  map: MapWithBounds;
  demBounds: number[] | null | undefined;
  dedupeKey: string;
  threshold?: number;
  /**
   * fix(#430 V-06): the warning's copy ("zoom in", "drape it over a coarse global
   * DEM") is builder-actionable advice; anonymous/read-only viewers can't act
   * on it. Pass `'viewer'` to suppress the toast entirely for that audience.
   * Defaults to `'builder'` so existing call sites keep their behavior.
   */
  audience?: 'builder' | 'viewer';
}): boolean {
  const { map, demBounds, dedupeKey, audience = 'builder' } = args;
  const threshold = args.threshold ?? SMALL_DEM_COVERAGE_THRESHOLD;

  // fix(#430 V-06): viewer sessions never see this builder-oriented advice toast.
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
