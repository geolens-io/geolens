import { afterEach, describe, expect, it, vi } from 'vitest';

const toastWarning = vi.fn();
vi.mock('sonner', () => ({
  toast: { warning: (...args: unknown[]) => toastWarning(...args) },
}));
vi.mock('@/i18n/i18n', () => ({
  default: { t: (key: string) => key },
}));

import {
  SMALL_DEM_COVERAGE_THRESHOLD,
  demViewportCoverage,
  maybeWarnSmallDemCoverage,
  resetSmallDemWarning,
  shouldWarnSmallDemCoverage,
} from '../terrain-coverage';

// [west, south, east, north]
const WORLD_VIEW = [-10, -10, 10, 10];

function mapWithBounds(view: number[] | null) {
  return {
    getBounds: () => {
      if (!view) throw new Error('no bounds');
      const [w, s, e, n] = view;
      return {
        getWest: () => w,
        getSouth: () => s,
        getEast: () => e,
        getNorth: () => n,
      };
    },
  };
}

describe('demViewportCoverage', () => {
  it('returns full coverage when the DEM contains the viewport', () => {
    expect(demViewportCoverage([-20, -20, 20, 20], WORLD_VIEW)).toBe(1);
  });

  it('returns the intersected fraction for a partially-covering DEM', () => {
    // DEM covers the right half of the viewport → 0.5
    expect(demViewportCoverage([0, -10, 10, 10], WORLD_VIEW)).toBeCloseTo(0.5, 6);
  });

  it('returns a small fraction for a tiny DEM', () => {
    // 2x2 DEM inside a 20x20 viewport → 4 / 400 = 0.01
    expect(demViewportCoverage([-1, -1, 1, 1], WORLD_VIEW)).toBeCloseTo(0.01, 6);
  });

  it('returns 0 when the DEM is disjoint from the viewport', () => {
    expect(demViewportCoverage([100, 100, 110, 110], WORLD_VIEW)).toBe(0);
  });

  it('returns null for degenerate / missing rectangles', () => {
    expect(demViewportCoverage(null, WORLD_VIEW)).toBeNull();
    expect(demViewportCoverage([0, 0, 0, 0], WORLD_VIEW)).toBeNull(); // not west<east
    expect(demViewportCoverage([1, 2, 3], WORLD_VIEW)).toBeNull(); // wrong arity
    expect(demViewportCoverage([NaN, 0, 1, 1], WORLD_VIEW)).toBeNull();
    expect(demViewportCoverage([-1, -1, 1, 1], null)).toBeNull();
  });
});

// fix(#1112 review): the antimeridian cases. `demBounds` here is the TILE
// TOKEN's bounds (span form, from processing/tiles/router.py), not the map
// layer's `dataset_extent_bbox`, so both forms are exercised: the span form is
// what ships today, and the spec form is what a crossing extent looks like if
// this input is ever sourced seam-aware.
//
// The rectangle that actually crosses is the VIEWPORT: MapLibre's getBounds()
// takes min/max over unwrapped corner longitudes, so a viewport straddling the
// seam reads e.g. [179.5, 182] rather than inverting.
describe('demViewportCoverage across the antimeridian', () => {
  // Fiji-shaped DEM: ~3 degrees wide, sitting on the seam.
  const FIJI_SPEC = [178.5, -20, -178.5, -15];
  const FIJI_SPAN = [-180, -20, 180, -15];
  // Zoomed in over Fiji, straddling the seam. 2.5 x 2 degrees.
  const SEAM_VIEW = [179.5, -18, 182, -16];
  // Zoomed way out. 120 x 120 degrees.
  const WIDE_VIEW = [120, -60, 240, 60];

  it('reports a world-spanning DEM as fully covering a seam-straddling viewport', () => {
    // The regression this fixes: clipping the DEM at +180 scored this 0.2 and
    // warned about a "small DEM" that covers the entire screen.
    expect(demViewportCoverage(FIJI_SPAN, SEAM_VIEW)).toBe(1);
  });

  it('scores a crossing DEM against the part of the viewport it really covers', () => {
    // [178.5, 181.5] over a [179.5, 182] viewport → 2 of 2.5 degrees wide,
    // full height → 0.8. The old code returned null (west > east was rejected).
    expect(demViewportCoverage(FIJI_SPEC, SEAM_VIEW)).toBeCloseTo(0.8, 6);
  });

  it('still reports a crossing DEM as a sliver of a zoomed-out viewport', () => {
    // 3 degrees wide, 5 of 120 degrees tall, in a 120x120 viewport.
    expect(demViewportCoverage(FIJI_SPEC, WIDE_VIEW)).toBeCloseTo((3 * 5) / (120 * 120), 6);
  });

  it('does not credit a DEM on the far side of the globe', () => {
    // Central France against a Fiji viewport: no turn of the globe overlaps.
    expect(demViewportCoverage([1.5, -18, 2.5, -16], SEAM_VIEW)).toBe(0);
  });

  // fix(#1124 codex P2): `renderWorldCopies` is on by default, so getBounds()
  // keeps running further out the more the user pans east or west. There is no
  // bound on how far, which is why the scoring cannot enumerate a fixed set of
  // turns. FAR_VIEW is SEAM_VIEW moved two whole turns east (+720) and must
  // score identically; DEEP_VIEW is ten turns west (-3600) and so must the
  // rest of the axis.
  const FAR_VIEW = [899.5, -18, 902, -16];
  const DEEP_VIEW = [-3420.5, -18, -3418, -16];

  it('scores a far-panned viewport exactly like the equivalent one at the seam', () => {
    expect(demViewportCoverage(FIJI_SPEC, FAR_VIEW)).toBeCloseTo(
      demViewportCoverage(FIJI_SPEC, SEAM_VIEW) as number, 6,
    );
    expect(demViewportCoverage(FIJI_SPEC, DEEP_VIEW)).toBeCloseTo(
      demViewportCoverage(FIJI_SPEC, SEAM_VIEW) as number, 6,
    );
  });

  it('still reports a world-spanning DEM as full coverage after a far pan', () => {
    expect(demViewportCoverage(FIJI_SPAN, FAR_VIEW)).toBe(1);
    expect(demViewportCoverage(FIJI_SPAN, DEEP_VIEW)).toBe(1);
  });

  it('is turn-invariant for an ordinary DEM at any pan distance', () => {
    // A plain non-crossing DEM, viewed from every turn out to ±20 world copies.
    const dem = [10, -1, 20, 1];
    const baseline = demViewportCoverage(dem, [12, -1, 18, 1]) as number;
    expect(baseline).toBeGreaterThan(0);
    for (let turn = -20; turn <= 20; turn++) {
      const shifted = [12 + 360 * turn, -1, 18 + 360 * turn, 1];
      expect(demViewportCoverage(dem, shifted)).toBeCloseTo(baseline, 6);
    }
  });
});

describe('shouldWarnSmallDemCoverage across the antimeridian', () => {
  const FIJI_SPEC = [178.5, -20, -178.5, -15];
  const FIJI_SPAN = [-180, -20, 180, -15];
  const SEAM_VIEW = [179.5, -18, 182, -16];
  const WIDE_VIEW = [120, -60, 240, 60];

  it('does not warn when a crossing DEM genuinely covers the viewport', () => {
    expect(shouldWarnSmallDemCoverage(FIJI_SPAN, SEAM_VIEW)).toBe(false);
    expect(shouldWarnSmallDemCoverage(FIJI_SPEC, SEAM_VIEW)).toBe(false);
  });

  it('still warns when a crossing DEM genuinely covers only a sliver', () => {
    expect(shouldWarnSmallDemCoverage(FIJI_SPEC, WIDE_VIEW)).toBe(true);
    expect(shouldWarnSmallDemCoverage(FIJI_SPAN, WIDE_VIEW)).toBe(true);
  });

  // fix(#1124 codex P2): both directions again, but two turns east of the seam.
  const FAR_VIEW = [899.5, -18, 902, -16];
  const FAR_WIDE_VIEW = [840, -60, 960, 60];

  it('does not warn about a covering DEM after the user pans past the seam', () => {
    expect(shouldWarnSmallDemCoverage(FIJI_SPAN, FAR_VIEW)).toBe(false);
    expect(shouldWarnSmallDemCoverage(FIJI_SPEC, FAR_VIEW)).toBe(false);
  });

  it('still warns about a sliver DEM after the user pans past the seam', () => {
    expect(shouldWarnSmallDemCoverage(FIJI_SPEC, FAR_WIDE_VIEW)).toBe(true);
    expect(shouldWarnSmallDemCoverage(FIJI_SPAN, FAR_WIDE_VIEW)).toBe(true);
  });
});

describe('shouldWarnSmallDemCoverage', () => {
  it('warns below the threshold', () => {
    expect(shouldWarnSmallDemCoverage([-1, -1, 1, 1], WORLD_VIEW)).toBe(true);
  });

  it('does not warn at or above the threshold', () => {
    // Exactly half-covered (0.5) is above the 0.25 default.
    expect(shouldWarnSmallDemCoverage([0, -10, 10, 10], WORLD_VIEW)).toBe(false);
  });

  it('does not warn when coverage cannot be computed (no signal)', () => {
    expect(shouldWarnSmallDemCoverage(null, WORLD_VIEW)).toBe(false);
  });

  it('respects a custom threshold', () => {
    // 0.5 coverage warns when threshold is 0.6.
    expect(shouldWarnSmallDemCoverage([0, -10, 10, 10], WORLD_VIEW, 0.6)).toBe(true);
  });

  it('exposes a sane default threshold', () => {
    expect(SMALL_DEM_COVERAGE_THRESHOLD).toBeGreaterThan(0);
    expect(SMALL_DEM_COVERAGE_THRESHOLD).toBeLessThan(1);
  });
});

describe('maybeWarnSmallDemCoverage dedupe', () => {
  afterEach(() => {
    toastWarning.mockClear();
  });

  it('warns once per (map, dedupeKey) for a small DEM', () => {
    const map = mapWithBounds(WORLD_VIEW);
    const args = { map, demBounds: [-1, -1, 1, 1], dedupeKey: 'dem-a' };

    expect(maybeWarnSmallDemCoverage(args)).toBe(true);
    expect(maybeWarnSmallDemCoverage(args)).toBe(false); // deduped
    expect(toastWarning).toHaveBeenCalledTimes(1);
    expect(toastWarning).toHaveBeenCalledWith(
      'builder:terrain.smallDemWarning',
      expect.objectContaining({ id: 'small-dem-dem-a' }),
    );
  });

  it('does not warn for a DEM that adequately covers the viewport', () => {
    const map = mapWithBounds(WORLD_VIEW);
    expect(maybeWarnSmallDemCoverage({ map, demBounds: [-20, -20, 20, 20], dedupeKey: 'big' })).toBe(false);
    expect(toastWarning).not.toHaveBeenCalled();
  });

  it('re-warns after a reset (terrain disabled then re-enabled)', () => {
    const map = mapWithBounds(WORLD_VIEW);
    const args = { map, demBounds: [-1, -1, 1, 1], dedupeKey: 'dem-a' };

    expect(maybeWarnSmallDemCoverage(args)).toBe(true);
    resetSmallDemWarning(map); // terrain off
    expect(maybeWarnSmallDemCoverage(args)).toBe(true);
    expect(toastWarning).toHaveBeenCalledTimes(2);
  });

  it('keeps the active DEM quiet but re-warns a different DEM after a keyed reset', () => {
    const map = mapWithBounds(WORLD_VIEW);
    const a = { map, demBounds: [-1, -1, 1, 1], dedupeKey: 'dem-a' };
    const b = { map, demBounds: [-1, -1, 1, 1], dedupeKey: 'dem-b' };

    expect(maybeWarnSmallDemCoverage(a)).toBe(true);
    // Switch to DEM b: keyed reset drops a but not b; b warns fresh.
    resetSmallDemWarning(map, 'dem-b');
    expect(maybeWarnSmallDemCoverage(b)).toBe(true);
    // Re-applying a now warns again (its key was dropped by the keyed reset).
    resetSmallDemWarning(map, 'dem-a');
    expect(maybeWarnSmallDemCoverage(a)).toBe(true);
    expect(toastWarning).toHaveBeenCalledTimes(3);
  });

  it('no-ops safely when the map has no bounds', () => {
    const map = mapWithBounds(null);
    expect(maybeWarnSmallDemCoverage({ map, demBounds: [-1, -1, 1, 1], dedupeKey: 'x' })).toBe(false);
    expect(toastWarning).not.toHaveBeenCalled();
  });
});
