import { describe, expect, it } from 'vitest';
import { colorShiftFor } from '../copc-color';

describe('colorShiftFor', () => {
  it('keeps 8-bit values stored in the 16-bit fields', () => {
    expect(colorShiftFor(255)).toBe(0);
    expect(colorShiftFor(0)).toBe(0);
  });

  it('shifts real 16-bit colour down to 8 bits', () => {
    expect(colorShiftFor(256)).toBe(8);
    expect(colorShiftFor(65535)).toBe(8);
  });
});
