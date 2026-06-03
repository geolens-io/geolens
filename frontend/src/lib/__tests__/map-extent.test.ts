import { describe, it, expect } from 'vitest';
import { computeLargeExtentView, isLargeExtent } from '../map-extent';

describe('isLargeExtent', () => {
  it('returns true when longitude span exceeds 90 degrees', () => {
    expect(isLargeExtent([-100, 30, 10, 50])).toBe(true);
  });

  it('returns true when latitude span exceeds 60 degrees', () => {
    expect(isLargeExtent([0, -40, 30, 40])).toBe(true);
  });

  it('returns false for small extents', () => {
    expect(isLargeExtent([-74.5, 40.5, -73.5, 41.5])).toBe(false);
  });

  it('returns true at exact 90-degree longitude threshold', () => {
    expect(isLargeExtent([0, 0, 90.01, 10])).toBe(true);
  });

  it('returns false at exactly 90-degree longitude span', () => {
    expect(isLargeExtent([0, 0, 90, 10])).toBe(false);
  });
});

describe('computeLargeExtentView', () => {
  it('computes center as midpoint of bbox', () => {
    const { center } = computeLargeExtentView([-180, -60, 180, 60]);
    expect(center[0]).toBe(0);
    expect(center[1]).toBe(0);
  });

  it('clamps latitude center to [-60, 60]', () => {
    const { center } = computeLargeExtentView([-180, -90, 180, 90]);
    expect(center[1]).toBe(0); // midpoint of -90,90 = 0, within range
  });

  it('clamps high latitude center', () => {
    const { center } = computeLargeExtentView([0, 50, 100, 90]);
    // midpoint lat = 70, clamped to 60
    expect(center[1]).toBe(60);
  });

  it('clamps low latitude center', () => {
    const { center } = computeLargeExtentView([0, -90, 100, -50]);
    // midpoint lat = -70, clamped to -60
    expect(center[1]).toBe(-60);
  });

  it('returns zoom >= 1', () => {
    const { zoom } = computeLargeExtentView([-180, -90, 180, 90]);
    expect(zoom).toBeGreaterThanOrEqual(1);
  });

  it('returns higher zoom for narrower extents', () => {
    const wide = computeLargeExtentView([-180, -60, 180, 60]);
    const narrow = computeLargeExtentView([-100, 20, 0, 50]);
    expect(narrow.zoom).toBeGreaterThan(wide.zoom);
  });

  it('handles single-degree span without division by zero', () => {
    const { zoom } = computeLargeExtentView([0, 0, 1, 1]);
    expect(zoom).toBeGreaterThan(0);
    expect(Number.isFinite(zoom)).toBe(true);
  });
});
