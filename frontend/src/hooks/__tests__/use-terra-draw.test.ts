import { describe, it, expect } from 'vitest';
import {
  getAvailableModes,
  getModeName,
  extractSingleGeometry,
  isMultiPartGeometry,
} from '@/hooks/use-terra-draw';

describe('getAvailableModes', () => {
  it('returns empty array for null geometry type', () => {
    expect(getAvailableModes(null)).toEqual([]);
  });

  it('returns point mode for POINT', () => {
    expect(getAvailableModes('POINT')).toEqual(['point']);
  });

  it('returns polygon modes for MULTIPOLYGON', () => {
    expect(getAvailableModes('MULTIPOLYGON')).toEqual([
      'polygon',
      'rectangle',
      'circle',
      'freehand',
    ]);
  });

  it('returns empty array for unknown geometry type', () => {
    expect(getAvailableModes('UNKNOWN')).toEqual([]);
  });

  it('handles case-insensitive input via toUpperCase', () => {
    expect(getAvailableModes('point')).toEqual(['point']);
  });

  it('returns linestring mode for LINESTRING', () => {
    expect(getAvailableModes('LINESTRING')).toEqual(['linestring']);
  });

  it('returns linestring mode for MULTILINESTRING', () => {
    expect(getAvailableModes('MULTILINESTRING')).toEqual(['linestring']);
  });

  it('returns point mode for MULTIPOINT', () => {
    expect(getAvailableModes('MULTIPOINT')).toEqual(['point']);
  });
});

describe('getModeName', () => {
  it('maps Point to point', () => {
    expect(getModeName('Point')).toBe('point');
  });

  it('maps MultiPolygon to polygon', () => {
    expect(getModeName('MultiPolygon')).toBe('polygon');
  });

  it('maps LineString to linestring', () => {
    expect(getModeName('LineString')).toBe('linestring');
  });

  it('maps MultiPoint to point', () => {
    expect(getModeName('MultiPoint')).toBe('point');
  });

  it('maps MultiLineString to linestring', () => {
    expect(getModeName('MultiLineString')).toBe('linestring');
  });

  it('returns polygon as default fallback for unknown type', () => {
    expect(getModeName('UnknownType')).toBe('polygon');
  });
});

describe('extractSingleGeometry', () => {
  it('extracts Point from MultiPoint', () => {
    expect(
      extractSingleGeometry({
        type: 'MultiPoint',
        coordinates: [[1, 2], [3, 4]],
      }),
    ).toEqual({ type: 'Point', coordinates: [1, 2] });
  });

  it('extracts LineString from MultiLineString', () => {
    expect(
      extractSingleGeometry({
        type: 'MultiLineString',
        coordinates: [[[0, 0], [1, 1]]],
      }),
    ).toEqual({ type: 'LineString', coordinates: [[0, 0], [1, 1]] });
  });

  it('extracts Polygon from MultiPolygon', () => {
    expect(
      extractSingleGeometry({
        type: 'MultiPolygon',
        coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]]],
      }),
    ).toEqual({
      type: 'Polygon',
      coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]],
    });
  });

  it('returns same geometry for single types (no-op)', () => {
    const geometry = { type: 'Point', coordinates: [1, 2] };
    expect(extractSingleGeometry(geometry)).toBe(geometry);
  });

  it('returns same geometry for MultiPoint with empty coordinates', () => {
    const geometry = { type: 'MultiPoint', coordinates: [] };
    expect(extractSingleGeometry(geometry)).toBe(geometry);
  });
});

describe('isMultiPartGeometry', () => {
  it('returns false for single Point', () => {
    expect(isMultiPartGeometry({ type: 'Point', coordinates: [1, 2] })).toBe(false);
  });

  it('returns false for MultiPolygon with 1 polygon (safe to edit)', () => {
    expect(
      isMultiPartGeometry({
        type: 'MultiPolygon',
        coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]]],
      }),
    ).toBe(false);
  });

  it('returns true for MultiPolygon with 2 polygons (unsafe)', () => {
    expect(
      isMultiPartGeometry({
        type: 'MultiPolygon',
        coordinates: [
          [[[0, 0], [1, 0], [1, 1], [0, 0]]],
          [[[2, 2], [3, 2], [3, 3], [2, 2]]],
        ],
      }),
    ).toBe(true);
  });

  it('returns true for MultiPoint with 3 points', () => {
    expect(
      isMultiPartGeometry({
        type: 'MultiPoint',
        coordinates: [[1, 2], [3, 4], [5, 6]],
      }),
    ).toBe(true);
  });

  it('returns false for MultiLineString with 1 line', () => {
    expect(
      isMultiPartGeometry({
        type: 'MultiLineString',
        coordinates: [[[0, 0], [1, 1]]],
      }),
    ).toBe(false);
  });

  it('returns true for MultiLineString with 2 lines', () => {
    expect(
      isMultiPartGeometry({
        type: 'MultiLineString',
        coordinates: [[[0, 0], [1, 1]], [[2, 2], [3, 3]]],
      }),
    ).toBe(true);
  });

  it('returns false when coordinates is not an array', () => {
    expect(isMultiPartGeometry({ type: 'MultiPoint', coordinates: null })).toBe(false);
  });
});
