/**
 * Phase 1136 EDITOR Pitfall #9 grep guard (phase-scoped).
 *
 * Asserts that the 5 editor source files modified during Phase 1136
 * contain ZERO direct `map.setPaintProperty` / `map.setLayoutProperty`
 * callsites. All paint/layout mutations from these files MUST route
 * through the v1026 owned-property contract:
 *   - paint: `onPaintProp(key, value)` → adapter `syncPaint` → `*_OWNED_PAINT_PROPERTIES`
 *   - layout: `onLayoutChange(layerId, layout)` → reconciler hook `handleLayoutChange`
 *             (documented exception per Phase 1133 WALK-04 audit)
 *
 * This guard is SCOPED to the 5 phase-1136 files. The broader baseline
 * of documented exceptions (label-layer-utils, ViewerMap.tsx, reconciler
 * hooks, basemap-style-mutation.ts) is the responsibility of Phase 1133
 * WALK-04's audit table, not this guard.
 *
 * Uses Vite `?raw` imports (no node:fs / @types/node dependency in tsconfig.app.json).
 */
import { describe, it, expect } from 'vitest';
import rasterEditorSrc from '../LayerStyleEditor/RasterEditor.tsx?raw';
import lineEditorSrc from '../LayerStyleEditor/LineEditor.tsx?raw';
import fillEditorSrc from '../LayerStyleEditor/FillEditor.tsx?raw';
import basemapGroupEditorSrc from '../BasemapGroupEditorScene.tsx?raw';
import basemapSublayerEditorSrc from '../BasemapSublayerEditorScene.tsx?raw';

function stripComments(src: string): string {
  // Drop /* ... */ block comments (non-greedy, multi-line)
  let s = src.replace(/\/\*[\s\S]*?\*\//g, '');
  // Drop // line comments
  s = s.replace(/^\s*\/\/.*$/gm, '');
  return s;
}

function countMatches(src: string, pattern: RegExp): number {
  const stripped = stripComments(src);
  const matches = stripped.match(pattern);
  return matches ? matches.length : 0;
}

const WATCHED = [
  {
    name: 'LayerStyleEditor/RasterEditor.tsx',
    src: rasterEditorSrc,
  },
  {
    name: 'LayerStyleEditor/LineEditor.tsx',
    src: lineEditorSrc,
  },
  {
    name: 'LayerStyleEditor/FillEditor.tsx',
    src: fillEditorSrc,
  },
  {
    name: 'BasemapGroupEditorScene.tsx',
    src: basemapGroupEditorSrc,
  },
  {
    name: 'BasemapSublayerEditorScene.tsx',
    src: basemapSublayerEditorSrc,
  },
];

describe('Phase 1136 EDITOR Pitfall #9 grep guard', () => {
  it.each(WATCHED)(
    '$name contains ZERO direct map.setPaintProperty callsites',
    ({ name, src }) => {
      const count = countMatches(src, /map\.setPaintProperty/g);
      expect(
        count,
        `Phase 1136 Pitfall #9 violation: ${name} contains ${count} direct map.setPaintProperty callsite(s). Route paint writes through onPaintProp + adapter OWNED_PAINT_PROPERTIES instead.`,
      ).toBe(0);
    },
  );

  it.each(WATCHED)(
    '$name contains ZERO direct map.setLayoutProperty callsites',
    ({ name, src }) => {
      const count = countMatches(src, /map\.setLayoutProperty/g);
      expect(
        count,
        `Phase 1136 Pitfall #9 violation: ${name} contains ${count} direct map.setLayoutProperty callsite(s). Route layout writes through onLayoutChange + adapter OWNED_LAYOUT_PROPERTIES instead.`,
      ).toBe(0);
    },
  );
});
