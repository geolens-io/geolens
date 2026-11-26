import { readFileSync } from 'node:fs';
import css from '../index.css?raw';

// Most focus indicators are Tailwind rings, which are box shadows; forced
// colors (Windows high contrast) removes those. The global rule must stay
// outside any cascade layer so it outranks the `outline-none` utilities.
describe('keyboard focus in forced colors', () => {
  it('draws an outline on every focus-visible element, outside any layer', () => {
    const rule = /@media \(forced-colors: active\) \{\s*:focus-visible,\s*\.maplibregl-ctrl :is\(button, summary\):focus-visible \{\s*outline: 2px solid transparent;/;
    const match = rule.exec(css);
    expect(match).not.toBeNull();

    // Not nested in any block, so not in a layer.
    const depth = [...css.slice(0, match!.index)].reduce((d, ch) => (ch === '{' ? d + 1 : ch === '}' ? d - 1 : d), 0);
    expect(depth).toBe(0);
  });

  it('keeps the outline visible where the default colour would not show', () => {
    const block = css.slice(css.indexOf('@media (forced-colors: active)'));
    // The dark theme's invert filter would flip MapLibre's palette-aware zoom and compass icons.
    expect(block).toMatch(/\.dark \.maplibregl-ctrl-group button \{\s*filter: none;/);
    expect(block).toMatch(/\.dark \.maplibregl-ctrl-group button \+ button \{\s*border-top-color: ButtonText;/);
    expect(block).not.toMatch(/\.dark[^{]*\{\s*outline-color: Canvas/);
    // The attribution icon is black unless the filter follows the palette, outline included.
    expect(block).toMatch(/@media \(prefers-color-scheme: light\) \{\s*:root \.maplibregl-map summary\.maplibregl-ctrl-attrib-button \{\s*filter: none;/);
    expect(block).toMatch(/@media \(prefers-color-scheme: dark\) \{\s*:root \.maplibregl-map summary\.maplibregl-ctrl-attrib-button \{\s*filter: invert\(1\);\s*\}\s*(?:\/\*[^*]*\*\/\s*)?:root \.maplibregl-map summary\.maplibregl-ctrl-attrib-button:focus-visible \{\s*outline-color: Canvas;/);
    // Terrain and globe icons are fixed-colour images without a high contrast variant.
    expect(block).toMatch(/:root \.maplibregl-ctrl-group button:is\(\.maplibregl-ctrl-terrain-enabled, \.maplibregl-ctrl-globe-enabled\) \{\s*filter: brightness\(0\.6\);/);
    expect(block).toMatch(/:root \.maplibregl-ctrl-group button:is\(\.maplibregl-ctrl-terrain, \.maplibregl-ctrl-globe\) \{\s*filter: invert\(1\);/);
    expect(block).toMatch(/button:is\(\.maplibregl-ctrl-terrain, \.maplibregl-ctrl-globe\):focus-visible \{\s*outline-color: Canvas;/);
    // A selected toggle keeps its Highlight background, so CanvasText is too faint on it.
    expect(block).toMatch(/\[data-slot="toggle-group-item"\]\[data-state="on"\]:focus-visible \{\s*outline-color: HighlightText;/);
  });

  it('covers every MapLibre icon button that has no high contrast variant', () => {
    const maplibre = readFileSync('node_modules/maplibre-gl/dist/maplibre-gl.css', 'utf8');
    const icons = (rules: string) => new Set([...rules.matchAll(/button\.maplibregl-ctrl-([a-z-]+?)(?::disabled)? \.maplibregl-ctrl-icon/g)].map((m) => m[1].replace(/-active.*|-background.*|-enabled/, '')));
    const forced = [...maplibre.matchAll(/@media[^{]*forced-colors[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g)].map((m) => m[0]).join('');
    const withVariant = icons(forced);
    const without = [...icons(maplibre)].filter((name) => !withVariant.has(name));
    // Add any new control here only after giving it a palette-aware rule in index.css.
    expect(without.sort()).toEqual(['globe', 'terrain']);
  });
});
