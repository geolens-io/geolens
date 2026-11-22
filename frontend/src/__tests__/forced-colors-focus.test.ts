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
});
