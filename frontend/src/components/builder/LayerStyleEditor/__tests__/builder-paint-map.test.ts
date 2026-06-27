import { describe, it, expect } from 'vitest';
import {
  BUILDER_PAINT_FIELDS,
  BUILDER_PAINT_STRIP_KEYS,
  buildBuilderControlPaint,
  routeBuilderPaintProp,
} from '../builder-paint-map';
import { CUSTOM_PAINT_PROPS } from '@/components/builder/layer-adapters/shared';

// builder-audit #338 DRY-01: the forward map (controlPaint), the reverse router
// (handlePaintProp), and the strip allowlist must all agree. Previously these
// were three hand-maintained sites that drifted; now they derive from one table.
describe('builder-paint-map (DRY-01 parity)', () => {
  it('the three derived sets agree: forward map === strip set, reverse ⊆ forward', () => {
    const forwardPaintKeys = new Set(BUILDER_PAINT_FIELDS.map((f) => f.paintKey));

    // Strip set is exactly the forward-map paint keys.
    expect([...BUILDER_PAINT_STRIP_KEYS].sort()).toEqual([...forwardPaintKeys].sort());

    // Reverse-routed keys are a subset of the forward map.
    for (const field of BUILDER_PAINT_FIELDS) {
      if (field.reverse) {
        expect(forwardPaintKeys.has(field.paintKey)).toBe(true);
        expect(routeBuilderPaintProp(field.paintKey)).toBe(field.builderKey);
      } else {
        expect(routeBuilderPaintProp(field.paintKey)).toBeUndefined();
      }
    }
  });

  it('every strip key is in the canonical CUSTOM_PAINT_PROPS allowlist (cannot drift into a 422)', () => {
    // Importing the canonical allowlist read-only ties our table to the
    // backend/adapter strip set: a new builder field that forgets the strip set
    // would fail this assertion instead of producing a runtime 422 on Apply.
    for (const key of BUILDER_PAINT_STRIP_KEYS) {
      expect(CUSTOM_PAINT_PROPS.has(key)).toBe(true);
    }
  });

  it('buildBuilderControlPaint overlays only defined builder fields onto paint', () => {
    const paint = { 'fill-color': '#fff', '_outline-color': '#000' };
    const result = buildBuilderControlPaint(paint, {
      outlineColor: '#abcdef',
      outlineWidth: undefined,
      fillDisabled: true,
    });
    // defined builder field wins over paint
    expect(result['_outline-color']).toBe('#abcdef');
    // undefined builder field does not overlay (paint untouched / absent)
    expect(result['_outline-width']).toBeUndefined();
    // boolean bookkeeping field overlays
    expect(result['_fill-disabled']).toBe(true);
    // non-builder paint passes through
    expect(result['fill-color']).toBe('#fff');
  });

  it('routeBuilderPaintProp returns undefined for plain MapLibre paint keys', () => {
    expect(routeBuilderPaintProp('fill-color')).toBeUndefined();
    expect(routeBuilderPaintProp('circle-radius')).toBeUndefined();
  });
});
