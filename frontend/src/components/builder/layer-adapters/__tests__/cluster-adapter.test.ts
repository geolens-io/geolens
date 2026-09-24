// A cluster colour ramp becomes a step expression on the point count.
import { describe, it, expect } from 'vitest';
import { clusterColorValue } from '../cluster-adapter';

describe('clusterColorValue', () => {
  it('returns the flat color when the ramp has fewer than 2 stops', () => {
    expect(clusterColorValue(undefined, '#abcdef')).toBe('#abcdef');
    expect(clusterColorValue([], '#abcdef')).toBe('#abcdef');
    expect(clusterColorValue([{ count: 0, color: '#111111' }], '#abcdef')).toBe('#abcdef');
  });

  it('builds a strictly-ascending step expression on point_count', () => {
    const expr = clusterColorValue(
      [
        { count: 750, color: '#333333' },
        { count: 0, color: '#111111' },
        { count: 100, color: '#222222' },
      ],
      '#abcdef',
    );
    // base color first, then strictly-ascending (threshold, color) pairs
    expect(expr).toEqual(['step', ['get', 'point_count'], '#111111', 100, '#222222', 750, '#333333']);
  });

  it('drops non-ascending/non-positive thresholds and falls back to flat if no valid step remains', () => {
    // base + a single threshold of 0 (dropped, must be > 0) → no valid step → flat
    expect(clusterColorValue([{ count: 0, color: '#111111' }, { count: 0, color: '#222222' }], '#abcdef')).toBe('#abcdef');
  });
});
