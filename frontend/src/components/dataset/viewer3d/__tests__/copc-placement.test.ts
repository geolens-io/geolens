import { describe, expect, it } from 'vitest';
import { lngOffset } from '../copc-placement';

describe('lngOffset', () => {
  it('is the plain difference away from the antimeridian', () => {
    expect(lngOffset(-122.9, -123)).toBeCloseTo(0.1, 9);
    expect(lngOffset(10, 12)).toBe(-2);
  });

  it('stays small for points on either side of the antimeridian', () => {
    expect(lngOffset(-179.9, 179.9)).toBeCloseTo(0.2, 9);
    expect(lngOffset(179.9, -179.9)).toBeCloseTo(-0.2, 9);
  });
});
