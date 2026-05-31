import { expressionColumn, displayColumn } from '../LegendPlugin';

// Pure-logic coverage for the legend plugin's expression/column helpers. The
// full legend render needs MapLibre paint objects; these helpers are the parts
// most prone to silent breakage when paint expressions are partial or nested.

describe('expressionColumn', () => {
  it('extracts the column from a direct get expression', () => {
    expect(expressionColumn(['get', 'population'])).toBe('population');
  });

  it('recurses into nested interpolate/step expressions', () => {
    const expr = ['interpolate', ['linear'], ['get', 'mhi'], 0, 'a', 100, 'b'];
    expect(expressionColumn(expr)).toBe('mhi');
  });

  it('finds the column inside a case expression', () => {
    const expr = ['case', ['==', ['get', 'kind'], 1], 'a', 'b'];
    expect(expressionColumn(expr)).toBe('kind');
  });

  it('returns null for a plain string color (no expression)', () => {
    expect(expressionColumn('#ff0000')).toBeNull();
  });

  it('returns null when no get expression is present', () => {
    expect(expressionColumn(['rgb', 1, 2, 3])).toBeNull();
  });
});

describe('displayColumn', () => {
  it('falls back to "value" when undefined', () => {
    expect(displayColumn(undefined)).toBe('value');
  });

  it('strips leading underscores and humanizes separators', () => {
    expect(displayColumn('pop_density')).toBe('pop density');
  });

  it('expands the mhi token to income', () => {
    expect(displayColumn('_median_mhi')).toBe('median income');
  });
});
