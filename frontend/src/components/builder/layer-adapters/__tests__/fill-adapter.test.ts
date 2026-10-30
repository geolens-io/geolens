// resolvePolygonStroke picks the outline colour from builder state, then the paint keys, then the default.
import { describe, it, expect } from 'vitest';
import { resolvePolygonStroke } from '../fill-adapter';

describe('resolvePolygonStroke outline colour', () => {
  it('falls back to a string fill-outline-color before the default', () => {
    const stroke = resolvePolygonStroke({ 'fill-outline-color': '#14532d' }, {});
    expect(stroke.authoredColor).toBe('#14532d');
    expect(stroke.color).toBe('#14532d');
  });

  it('ranks it below the builder and mirror colours', () => {
    expect(resolvePolygonStroke({ 'fill-outline-color': '#14532d', '_outline-color': '#111111' }, {}).color).toBe('#111111');
    expect(resolvePolygonStroke({ 'fill-outline-color': '#14532d' }, { outlineColor: '#222222' }).color).toBe('#222222');
  });

  it('ignores a fill-outline-color that is not a string', () => {
    expect(resolvePolygonStroke({ 'fill-outline-color': ['get', 'c'] }, {}).authoredColor).toBeUndefined();
  });
});
