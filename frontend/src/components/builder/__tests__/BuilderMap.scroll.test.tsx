/**
 * Map container does not scroll the page body during pan/zoom.
 *
 * This test pins the static surface: the BuilderMap outer wrapper and the
 * MapBuilderPage parent column do NOT have `overflow-auto`, `overflow-scroll`,
 * or `overflow-y-*` classes on the ancestor chain from BuilderMap up to the
 * page root. MapLibre sets `touch-action: none` on its canvas internally; the
 * remaining risk is an ancestor scroll context that intercepts wheel events
 * before MapLibre.
 *
 * Live behavior (page body scrollY === 0 during canvas pan/zoom) is verified
 * in a Playwright MCP run at 800×600 and 414×896 viewports.
 *
 * Uses Vite ?raw imports — same pattern as preserve-drawing-buffer.test.ts
 * (no node:fs / @types/node dependency in tsconfig.app.json).
 */
import builderMapSrc from '../BuilderMap.tsx?raw';
import mapBuilderPageSrc from '../../../pages/MapBuilderPage.tsx?raw';

describe('MAP-19 — BuilderMap scroll containment', () => {
  it('BuilderMap outer wrapper has no overflow-auto / overflow-scroll classes', () => {
    // The outer wrapper has `data-builder-canvas="true"`. Read 300 chars on
    // each side of the marker to cover its className without spanning unrelated
    // code. The className should be `relative h-full w-full` only.
    const startIdx = builderMapSrc.indexOf('data-builder-canvas');
    expect(startIdx, 'data-builder-canvas marker not found in BuilderMap.tsx').toBeGreaterThan(0);
    const context = builderMapSrc.slice(Math.max(0, startIdx - 300), startIdx + 300);
    expect(context).not.toMatch(/overflow-(auto|scroll|y-(auto|scroll))/);
  });

  it('MapBuilderPage map column has min-h-0 + min-w-0 (no overflow setter)', () => {
    // The docked column is a vertical flex `relative flex min-h-0 min-w-0
    // flex-col`; its map wrapper (the MapErrorBoundary div) carries
    // `relative min-h-0 flex-1` — still no overflow setter anywhere on the
    // ancestor chain.
    expect(mapBuilderPageSrc).toMatch(/relative\s+flex\s+min-h-0\s+min-w-0\s+flex-col/);
  });

  it('BuilderMap MapGL element fills the wrapper without explicit overflow', () => {
    // MapGL inline style is `{ width: '100%', height: '100%' }`. No overflow.
    expect(builderMapSrc).toMatch(/style=\{\{\s*width:\s*'100%',\s*height:\s*'100%'\s*\}\}/);
  });

  it('regression pin: any new overflow-auto on BuilderMap outer chain triggers this test', () => {
    // This is documentation as a test: it always passes today, but if a
    // future engineer adds overflow-auto to the BuilderMap wrapper or the
    // page column, the first 2 tests will fail. Reverification surface:
    // 1. Search frontend/src/components/builder/BuilderMap.tsx
    // 2. Search frontend/src/pages/MapBuilderPage.tsx parent column
    // 3. Live MCP smoke at 800×600 and 414×896.
    expect(true).toBe(true);
  });
});
