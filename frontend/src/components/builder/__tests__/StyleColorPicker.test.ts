import { describe, expect, it } from 'vitest';
import { MAP_COLORS } from '@/lib/map-colors';
import { PRESET_COLORS } from '../StyleColorPicker';

describe('StyleColorPicker presets', () => {
  it('includes the centralized default layer color', () => {
    expect(PRESET_COLORS).toContain(MAP_COLORS.default.fill);
  });
});
