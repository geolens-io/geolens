/**
 * fix(#1472 review): dataset credits reach MapLibre's attribution control,
 * which assigns them to innerHTML. MapLibre's own sanitizer removes only
 * <script>, on* handlers, and javascript:/data: URLs — img, iframe, and inline
 * style survive it — so an editor-supplied credit is an injection vector into
 * every public, shared, and embedded map unless it is escaped first.
 */
import { describe, expect, it } from 'vitest';
import { escapeAttributionHtml, toMapLibreAttribution } from '../attribution-safety';

describe('escapeAttributionHtml', () => {
  it('neutralizes the tag characters', () => {
    expect(escapeAttributionHtml('<img src=x>')).toBe('&lt;img src=x&gt;');
  });

  it('escapes the ampersand first so entities are not double-decoded', () => {
    // '&lt;' must survive as literal text, not decode back into '<'.
    expect(escapeAttributionHtml('&lt;script&gt;')).toBe('&amp;lt;script&amp;gt;');
  });

  it.each([
    ['<img src=1 onerror=alert(1)>', 'img'],
    ['<iframe src="https://evil.example"></iframe>', 'iframe'],
    ['<div style="position:fixed;inset:0">overlay</div>', 'style'],
  ])('leaves no live %s markup (the shapes MapLibre would keep)', (payload) => {
    const escaped = escapeAttributionHtml(payload);
    expect(escaped).not.toContain('<');
    expect(escaped).not.toContain('>');
  });

  it('leaves ordinary credit text alone apart from the ampersand', () => {
    expect(escapeAttributionHtml('© swisstopo — swissALTI3D')).toBe(
      '© swisstopo — swissALTI3D',
    );
    expect(escapeAttributionHtml("Rand & McNally, 'the' map")).toBe(
      "Rand &amp; McNally, 'the' map",
    );
  });
});

describe('toMapLibreAttribution', () => {
  it('trims and escapes in one step', () => {
    expect(toMapLibreAttribution('  <b>NOAA</b>  ')).toBe('&lt;b&gt;NOAA&lt;/b&gt;');
  });

  it.each([null, undefined, '', '   ', '\n\t'])(
    'returns null for %p so callers omit the property entirely',
    (input) => {
      expect(toMapLibreAttribution(input)).toBeNull();
    },
  );
});
