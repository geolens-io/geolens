import { findElevationColumn } from '../geo-utils';

describe('findElevationColumn', () => {
  it('returns null for null input', () => {
    expect(findElevationColumn(null)).toBeNull();
  });

  it('returns null for undefined input', () => {
    expect(findElevationColumn(undefined)).toBeNull();
  });

  it('returns null for empty array', () => {
    expect(findElevationColumn([])).toBeNull();
  });

  it('returns null when no columns match', () => {
    const cols = [
      { name: 'name', type: 'text' },
      { name: 'category', type: 'text' },
      { name: 'gid', type: 'integer' },
    ];
    expect(findElevationColumn(cols)).toBeNull();
  });

  it('matches "height" column with numeric type', () => {
    const cols = [
      { name: 'name', type: 'text' },
      { name: 'height', type: 'double precision' },
    ];
    expect(findElevationColumn(cols)).toBe('height');
  });

  it('matches "elev" column case-insensitively', () => {
    const cols = [{ name: 'Elev', type: 'float' }];
    expect(findElevationColumn(cols)).toBe('Elev');
  });

  it('matches "elevation" with integer type', () => {
    const cols = [{ name: 'elevation', type: 'integer' }];
    expect(findElevationColumn(cols)).toBe('elevation');
  });

  it('matches "z" with numeric type', () => {
    const cols = [{ name: 'z', type: 'numeric' }];
    expect(findElevationColumn(cols)).toBe('z');
  });

  it('matches compound names like "elev_ft"', () => {
    const cols = [{ name: 'elev_ft', type: 'integer' }];
    expect(findElevationColumn(cols)).toBe('elev_ft');
  });

  it('matches "height_m" and "height_ft"', () => {
    expect(findElevationColumn([{ name: 'height_m', type: 'real' }])).toBe('height_m');
    expect(findElevationColumn([{ name: 'height_ft', type: 'float8' }])).toBe('height_ft');
  });

  it('rejects elevation name with non-numeric type', () => {
    const cols = [{ name: 'dem', type: 'text' }];
    expect(findElevationColumn(cols)).toBeNull();
  });

  it('rejects "dtm" with varchar type', () => {
    const cols = [{ name: 'dtm', type: 'character varying' }];
    expect(findElevationColumn(cols)).toBeNull();
  });

  it('does not partial-match — "z_order" should not match "z"', () => {
    const cols = [{ name: 'z_order', type: 'integer' }];
    expect(findElevationColumn(cols)).toBeNull();
  });

  it('does not partial-match — "height_class" should not match "height"', () => {
    const cols = [{ name: 'height_class', type: 'text' }];
    expect(findElevationColumn(cols)).toBeNull();
  });

  it('accepts column without type info (backward compat)', () => {
    const cols = [{ name: 'height' }];
    expect(findElevationColumn(cols)).toBe('height');
  });

  it('returns the first matching column when multiple exist', () => {
    const cols = [
      { name: 'name', type: 'text' },
      { name: 'elev', type: 'float' },
      { name: 'height', type: 'double precision' },
    ];
    expect(findElevationColumn(cols)).toBe('elev');
  });
});
