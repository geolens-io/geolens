import { expressionColumn, displayColumn, getSwatchStyleFromPaint } from '../LegendPlugin';

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

// fix(#1288 codex): a stroke the user turned off through the builder can leave
// paint's _stroke-disabled/_outline-width unchanged (toggling a polygon stroke
// off writes both builder.strokeDisabled and builder.outlineWidth: 0, not the
// paint mirror) — the categorical/graduated legend swatch must prefer builder
// state, same as extractStyleHints on the layer-icon path.
describe('getSwatchStyleFromPaint — builder stroke precedence (fix #1288)', () => {
  it('prefers builder.strokeDisabled over a stale paint mirror', () => {
    const style = getSwatchStyleFromPaint(
      { 'fill-opacity': 0, '_outline-color': '#ec4b7f' },
      'POLYGON',
      1,
      { strokeDisabled: true, outlineColor: '#ec4b7f' },
    );
    expect(style.strokeDisabled).toBe(true);
  });

  it('treats an explicit builder.outlineWidth of 0 as a disabled stroke', () => {
    const style = getSwatchStyleFromPaint(
      { 'fill-opacity': 0, '_outline-color': '#ec4b7f', '_outline-width': 2 },
      'POLYGON',
      1,
      { outlineWidth: 0, outlineColor: '#ec4b7f' },
    );
    expect(style.strokeDisabled).toBe(true);
    expect(style.strokeWidth).toBe(0);
  });

  it('leaves a normal visible outline unchanged', () => {
    const style = getSwatchStyleFromPaint(
      { 'fill-opacity': 0.5, '_outline-color': '#ec4b7f', '_outline-width': 2 },
      'POLYGON',
      1,
      undefined,
    );
    expect(style.strokeDisabled).toBe(false);
    expect(style.outlineColor).toBe('#ec4b7f');
    expect(style.strokeWidth).toBe(2);
  });
});
