import css from '../index.css?raw';

// Most focus indicators are Tailwind rings, which are box shadows; forced
// colors (Windows high contrast) removes those. The global rule must stay
// outside any cascade layer so it outranks the `outline-none` utilities.
describe('keyboard focus in forced colors', () => {
  it('draws an outline on every focus-visible element, outside any layer', () => {
    const rule = /@media \(forced-colors: active\) \{\s*:focus-visible,\s*\.maplibregl-ctrl :is\(button, summary\):focus-visible \{\s*outline: 2px solid CanvasText;/;
    const match = rule.exec(css);
    expect(match).not.toBeNull();

    // Not nested in any block, so not in a layer.
    const depth = [...css.slice(0, match!.index)].reduce((d, ch) => (ch === '{' ? d + 1 : ch === '}' ? d - 1 : d), 0);
    expect(depth).toBe(0);
  });

  it('keeps the outline visible where the default colour would not show', () => {
    const block = css.slice(css.indexOf('@media (forced-colors: active)'));
    // The dark theme's invert filter on MapLibre controls inverts the outline too.
    expect(block).toMatch(/\.dark \.maplibregl-ctrl-group button:focus-visible,\s*\.dark \.maplibregl-ctrl-attrib-button:focus-visible \{\s*outline-color: Canvas;/);
    // A selected toggle keeps its Highlight background, so CanvasText is too faint on it.
    expect(block).toMatch(/\[data-slot="toggle-group-item"\]\[data-state="on"\]:focus-visible \{\s*outline-color: HighlightText;/);
  });
});
