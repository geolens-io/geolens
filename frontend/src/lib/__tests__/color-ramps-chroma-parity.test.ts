import { describe, it, expect } from 'vitest';
import chroma from 'chroma-js';
import {
  getRampColors,
  SEQUENTIAL_RAMPS,
  DIVERGING_RAMPS,
  QUALITATIVE_RAMPS,
} from '../color-ramps';

// fix(#448): getRampColors no longer imports chroma-js — the static import
// chain layer-icons/LegendEntries → color-ramps → chroma-js pulled the
// color-vendor chunk into the ENTRY graph (the login page downloaded 19.5KB
// gz for two decorative heatmap previews). This suite pins the local
// reimplementation to chroma.scale(name).colors(count) BIT-FOR-BIT so
// legend swatches keep matching the colors stored in existing saved maps
// (which were generated with chroma in the builder). chroma-js remains a
// builder-only dependency (color-relief-sync.ts), so importing it in tests
// is free — tests are never bundled.

const ALL_RAMPS = [...SEQUENTIAL_RAMPS, ...DIVERGING_RAMPS, ...QUALITATIVE_RAMPS].map(
  (r) => r.name as string,
);
// chroma-js has no brewer entry for Inferno/Plasma — the pre-#448 try/catch
// already served the YlOrRd fallback for them, which getRampColors preserves.
const CHROMA_KNOWN = ALL_RAMPS.filter((n) => n !== 'Inferno' && n !== 'Plasma');

describe('getRampColors ↔ chroma-js parity', () => {
  it.each(CHROMA_KNOWN)('%s matches chroma output for counts 1..14', (name) => {
    for (let count = 1; count <= 14; count++) {
      expect(getRampColors(name, count)).toEqual(
        chroma.scale(name as chroma.BrewerPaletteName).colors(count),
      );
    }
  });

  it('serves the YlOrRd fallback for Inferno/Plasma/unknown names (pre-#448 behavior)', () => {
    expect(getRampColors('Inferno', 5)).toEqual(chroma.scale('YlOrRd').colors(5));
    expect(getRampColors('Plasma', 5)).toEqual(chroma.scale('YlOrRd').colors(5));
    expect(getRampColors('not-a-ramp', 5)).toEqual(chroma.scale('YlOrRd').colors(5));
  });
});
