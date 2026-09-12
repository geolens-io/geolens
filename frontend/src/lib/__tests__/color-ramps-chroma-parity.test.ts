import { describe, it, expect } from 'vitest';
import chroma from 'chroma-js';
import {
  getRampColors,
  SEQUENTIAL_RAMPS,
  DIVERGING_RAMPS,
  QUALITATIVE_RAMPS,
} from '../color-ramps';

// chroma-js is test-only reference data. Keep the production
// implementation bit-identical so saved-map colors and legend swatches agree.

const ALL_RAMPS = [...SEQUENTIAL_RAMPS, ...DIVERGING_RAMPS, ...QUALITATIVE_RAMPS].map(
  (r) => r.name as string,
);
const QUALITATIVE_NAMES = new Set(QUALITATIVE_RAMPS.map((r) => r.name as string));
// chroma-js has no brewer entry for Inferno/Plasma, so getRampColors preserves
// their YlOrRd fallback. Qualitative ramps such as Set2 are not sampled
// continuously — getRampColors now cycles discrete palette entries for
// them, so they intentionally diverge from chroma.scale()'s gradient output
// and are excluded from the bit-parity checks below.
const CHROMA_KNOWN = ALL_RAMPS.filter(
  (n) => n !== 'Inferno' && n !== 'Plasma' && !QUALITATIVE_NAMES.has(n),
);

describe('getRampColors ↔ chroma-js parity', () => {
  it.each(CHROMA_KNOWN)('%s matches chroma output for counts 1..14', (name) => {
    for (let count = 1; count <= 14; count++) {
      expect(getRampColors(name, count)).toEqual(
        chroma.scale(name as chroma.BrewerPaletteName).colors(count),
      );
    }
  });

  it('serves the YlOrRd fallback for Inferno, Plasma, and unknown names', () => {
    expect(getRampColors('Inferno', 5)).toEqual(chroma.scale('YlOrRd').colors(5));
    expect(getRampColors('Plasma', 5)).toEqual(chroma.scale('YlOrRd').colors(5));
    expect(getRampColors('not-a-ramp', 5)).toEqual(chroma.scale('YlOrRd').colors(5));
  });

  // chroma.scale() lowercases brewer names, so legacy
  // style configs with 'viridis'/'blues' resolved correctly — the local
  // lookup must stay case-insensitive rather than fall back to YlOrRd.
  it.each(CHROMA_KNOWN)('%s resolves case-insensitively like chroma', (name) => {
    const lower = name.toLowerCase();
    expect(getRampColors(lower, 7)).toEqual(
      chroma.scale(lower as chroma.BrewerPaletteName).colors(7),
    );
    expect(getRampColors(name.toUpperCase(), 7)).toEqual(getRampColors(name, 7));
  });
});
