import { getGeometryTypeLabel, withCoordSuffix } from './labels';

const t = (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? '';

describe('getGeometryTypeLabel', () => {
  it('keeps the M suffix on a measured (XYM) type', () => {
    expect(getGeometryTypeLabel(t, 'POINTM')).toBe('PointM');
  });

  it('keeps the Z suffix on a 3D type', () => {
    expect(getGeometryTypeLabel(t, 'LINESTRINGZ')).toBe('LineStringZ');
  });

  it('keeps the ZM suffix on a measured 3D type', () => {
    expect(getGeometryTypeLabel(t, 'MULTIPOLYGONZM')).toBe('MultiPolygonZM');
  });

  it('still labels a plain type with no suffix', () => {
    expect(getGeometryTypeLabel(t, 'MULTIPOINT')).toBe('MultiPoint');
  });
});

describe('withCoordSuffix', () => {
  it('appends M for a measured, non-3D geometry', () => {
    expect(withCoordSuffix('MultiPoint', false, 3)).toBe('MultiPointM');
  });

  it('appends Z for a 3D, non-measured geometry', () => {
    expect(withCoordSuffix('Point', true, 3)).toBe('PointZ');
  });

  it('appends ZM for a measured 3D geometry', () => {
    expect(withCoordSuffix('Polygon', true, 4)).toBe('PolygonZM');
  });

  it('leaves a plain 2D geometry alone', () => {
    expect(withCoordSuffix('Polygon', false, 2)).toBe('Polygon');
  });
});
