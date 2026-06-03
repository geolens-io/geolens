import { describe, it, expect } from 'vitest';
import {
  buildGraduatedSizeExpression,
  getSizeProperty,
  getColorProperty,
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
