// fillPatternTint gives the colour a built-in pattern draws in, and only ever a string.
import { describe, it, expect } from 'vitest';
import { fillPatternTint } from '@/lib/fill-pattern-preview';

describe('fillPatternTint', () => {
  it('prefers a solid paint colour', () => {
    expect(fillPatternTint({ 'fill-color': '#abcdef' }, { fillColorSaved: '#0f0' })).toBe('#abcdef');
  });

  it('falls back to the stash when a pattern owns the fill', () => {
    expect(fillPatternTint({ 'fill-pattern': 'geolens-fill-hatch' }, { fillColorSaved: '#0f0' })).toBe('#0f0');
  });

  it('ignores an expression-valued paint colour, which cannot be a tint', () => {
    const ramp = ['match', ['get', 'k'], 'a', '#f00', '#0f0'];
    expect(fillPatternTint({ 'fill-color': ramp }, { fillColorSaved: '#0f0' })).toBe('#0f0');
  });

  it.each([[42], [{ r: 1 }], [['#fff']], [true], [null]])(
    'returns undefined for a non-string stash (%o) rather than passing junk on',
    (junk) => {
      const builder = { fillColorSaved: junk } as unknown as { fillColorSaved?: string };
      expect(fillPatternTint({ 'fill-pattern': 'geolens-fill-hatch' }, builder)).toBeUndefined();
    },
  );

  it('returns undefined when there is nothing to tint with', () => {
    expect(fillPatternTint({}, undefined)).toBeUndefined();
  });
});
