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
