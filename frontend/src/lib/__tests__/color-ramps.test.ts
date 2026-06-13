import { describe, it, expect } from 'vitest';
import {
  buildGraduatedSizeExpression,
  getSizeProperty,
  getColorProperty,
  reverseRamp,
  cvdSafeRamps,
  getRampColors,
  SEQUENTIAL_RAMPS,
  DIVERGING_RAMPS,
  QUALITATIVE_RAMPS,
} from '../color-ramps';

describe('buildGraduatedSizeExpression', () => {
  it('returns a step expression with correct shape', () => {
    const result = buildGraduatedSizeExpression('pop', [100, 500, 1000], [3, 6, 10, 16]);
    expect(result).toEqual(['case', ['==', ['get', 'pop'], null], 0, ['step', ['get', 'pop'], 3, 100, 6, 500, 10, 1000, 16]]);
  });

  it('throws if sizes.length !== breaks.length + 1', () => {
    expect(() => buildGraduatedSizeExpression('pop', [100, 500], [3, 6])).toThrow();
    expect(() => buildGraduatedSizeExpression('pop', [100], [3, 6, 10])).toThrow();
  });

  it('handles single break (2 classes)', () => {
    const result = buildGraduatedSizeExpression('x', [50], [4, 12]);
    expect(result).toEqual(['case', ['==', ['get', 'x'], null], 0, ['step', ['get', 'x'], 4, 50, 12]]);
  });
});

describe('getSizeProperty', () => {
  it('returns circle-radius for Point + radius', () => {
    expect(getSizeProperty('Point', 'radius')).toBe('circle-radius');
  });

  it('returns circle-radius for MultiPoint + radius', () => {
    expect(getSizeProperty('MultiPoint', 'radius')).toBe('circle-radius');
  });

  it('returns line-width for LineString + width', () => {
    expect(getSizeProperty('LineString', 'width')).toBe('line-width');
  });

  it('returns line-width for MultiLineString + width', () => {
    expect(getSizeProperty('MultiLineString', 'width')).toBe('line-width');
  });

  it('returns null for Polygon + radius (no size property for polygons)', () => {
    expect(getSizeProperty('Polygon', 'radius')).toBeNull();
  });

  it('returns null for Point + color (color is not a size target)', () => {
    expect(getSizeProperty('Point', 'color')).toBeNull();
  });

  it('returns null for null geometryType', () => {
    expect(getSizeProperty(null, 'radius')).toBeNull();
  });

  it('returns null for MultiPolygon + width', () => {
    expect(getSizeProperty('MultiPolygon', 'width')).toBeNull();
  });

  it('returns null for LineString + radius (wrong target for line)', () => {
    expect(getSizeProperty('LineString', 'radius')).toBeNull();
  });

  it('returns null for Point + width (wrong target for point)', () => {
    expect(getSizeProperty('Point', 'width')).toBeNull();
  });
});

describe('reverseRamp', () => {
  it('reverses a 3-color array', () => {
    expect(reverseRamp(['#000', '#888', '#fff'])).toEqual(['#fff', '#888', '#000']);
  });

  it('reversing twice is identity', () => {
    const colors = ['#000', '#888', '#fff'];
    expect(reverseRamp(reverseRamp(colors))).toEqual(colors);
  });

  it('does not mutate the input array', () => {
    const colors = ['#aaa', '#bbb', '#ccc'];
    reverseRamp(colors);
    expect(colors).toEqual(['#aaa', '#bbb', '#ccc']);
  });

  it('handles a single color (round-trips)', () => {
    expect(reverseRamp(['#ff0000'])).toEqual(['#ff0000']);
  });
});

describe('getRampColors with reversed flag', () => {
  it('reversed=true returns the reverse of reversed=false for same ramp + count', () => {
    const forward = getRampColors('Blues', 5, false);
    const backward = getRampColors('Blues', 5, true);
    expect(backward).toEqual(reverseRamp(forward));
  });

  it('reversed=false (default) equals calling without the flag', () => {
    expect(getRampColors('Viridis', 7, false)).toEqual(getRampColors('Viridis', 7));
  });

  it('reversed flag round-trip: reversed(reversed) equals original', () => {
    const colors = getRampColors('YlOrRd', 5);
    const reversed = reverseRamp(colors);
    expect(reverseRamp(reversed)).toEqual(colors);
  });
});

describe('cvdSafeRamps', () => {
  it('excludes Spectral (cvdSafe: false) from diverging ramps', () => {
    const safe = cvdSafeRamps(DIVERGING_RAMPS);
    expect(safe.map((r) => r.name)).not.toContain('Spectral');
  });

  it('excludes RdYlGn (cvdSafe: false) from diverging ramps', () => {
    const safe = cvdSafeRamps(DIVERGING_RAMPS);
    expect(safe.map((r) => r.name)).not.toContain('RdYlGn');
  });

  it('includes Viridis (cvdSafe: true) in sequential ramps', () => {
    const safe = cvdSafeRamps(SEQUENTIAL_RAMPS);
    expect(safe.map((r) => r.name)).toContain('Viridis');
  });

  it('includes RdBu and BrBG (cvdSafe: true) in diverging ramps', () => {
    const safe = cvdSafeRamps(DIVERGING_RAMPS);
    const names = safe.map((r) => r.name);
    expect(names).toContain('RdBu');
    expect(names).toContain('BrBG');
  });

  it('excludes Set1, Set3, Accent, Pastel1, Pastel2 from qualitative ramps', () => {
    const safe = cvdSafeRamps(QUALITATIVE_RAMPS);
    const names = safe.map((r) => r.name);
    expect(names).not.toContain('Set1');
    expect(names).not.toContain('Set3');
    expect(names).not.toContain('Accent');
    expect(names).not.toContain('Pastel1');
    expect(names).not.toContain('Pastel2');
  });

  it('includes Set2, Dark2, Paired in qualitative ramps', () => {
    const safe = cvdSafeRamps(QUALITATIVE_RAMPS);
    const names = safe.map((r) => r.name);
    expect(names).toContain('Set2');
    expect(names).toContain('Dark2');
    expect(names).toContain('Paired');
  });

  it('all sequential ramps are cvdSafe', () => {
    expect(cvdSafeRamps(SEQUENTIAL_RAMPS)).toHaveLength(SEQUENTIAL_RAMPS.length);
  });
});

describe('getColorProperty regression', () => {
  it('returns fill-color for Polygon', () => {
    expect(getColorProperty('Polygon')).toBe('fill-color');
  });

  it('returns line-color for LineString', () => {
    expect(getColorProperty('LineString')).toBe('line-color');
  });

  it('returns circle-color for Point', () => {
    expect(getColorProperty('Point')).toBe('circle-color');
  });

  it('returns fill-color for null', () => {
    expect(getColorProperty(null)).toBe('fill-color');
  });

  it('returns circle-color for MultiPoint', () => {
    expect(getColorProperty('MultiPoint')).toBe('circle-color');
  });
});
