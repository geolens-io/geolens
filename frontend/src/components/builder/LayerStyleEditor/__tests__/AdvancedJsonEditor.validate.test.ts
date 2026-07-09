import { describe, expect, it } from 'vitest';
import { validatePropertyBlock } from '../AdvancedJsonEditor';

/**
 * fix(#431 codex r2): mixed-geometry layers carry fill-*, line-*, and circle-*
 * keys in ONE paint dict (the adapter fans them out to family sublayers).
 * Validating the whole dict as a single fill layer rejected the line/circle
 * keys — the exact keys this editor is the styling path for. The 'mixed'
 * layerType now validates each family's subset against its own layer type.
 */
describe('validatePropertyBlock — mixed-geometry layers', () => {
  it('accepts paint mixing fill-*, line-*, and circle-* keys', () => {
    const errors = validatePropertyBlock(
      {
        'fill-color': '#ff0000',
        'fill-opacity': 0.5,
        'line-color': '#00ff00',
        'line-width': 3,
        'circle-color': '#0000ff',
        'circle-radius': 6,
      },
      'mixed',
      'paint',
    );
    expect(errors).toEqual([]);
  });

  it('still rejects invalid values within each family', () => {
    const errors = validatePropertyBlock(
      { 'line-width': 'not-a-number', 'circle-radius': 6 },
      'mixed',
      'paint',
    );
    expect(errors).not.toBeNull();
    expect(errors!.length).toBeGreaterThan(0);
    expect(errors!.join(' ')).toContain('line-width');
  });

  it('rejects fill-extrusion-* keys (the mixed adapter has no extrusion sublayer)', () => {
    const errors = validatePropertyBlock(
      { 'fill-extrusion-height': 10 },
      'mixed',
      'paint',
    );
    expect(errors).not.toBeNull();
    expect(errors!.length).toBeGreaterThan(0);
  });

  it('validates un-prefixed layout keys (visibility) under the fill primary', () => {
    expect(validatePropertyBlock({ visibility: 'none' }, 'mixed', 'layout')).toEqual([]);
    expect(
      validatePropertyBlock({ 'line-cap': 'round', visibility: 'visible' }, 'mixed', 'layout'),
    ).toEqual([]);
  });

  it('single-type validation is unchanged for concrete layers', () => {
    expect(validatePropertyBlock({ 'fill-color': '#123456' }, 'fill', 'paint')).toEqual([]);
    const errors = validatePropertyBlock({ 'line-color': '#123456' }, 'fill', 'paint');
    expect(errors).not.toBeNull();
    expect(errors!.length).toBeGreaterThan(0);
  });
});
