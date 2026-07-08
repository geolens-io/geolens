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
 */

/** Default coverage threshold below which the warning fires. */
export const SMALL_DEM_COVERAGE_THRESHOLD = 0.25;

type Bounds4 = [number, number, number, number]; // [west, south, east, north]

function isFiniteBounds4(bounds: number[] | null | undefined): bounds is Bounds4 {
  return Array.isArray(bounds)
    && bounds.length === 4
    && bounds.every((v) => Number.isFinite(v))
    && bounds[0] < bounds[2]
    && bounds[1] < bounds[3];
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
  const viewportArea = (ve - vw) * (vn - vs);
  if (!(viewportArea > 0)) return null;

  const ix = Math.max(0, Math.min(ve, demBounds[2]) - Math.max(vw, demBounds[0]));
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
