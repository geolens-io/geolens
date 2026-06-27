import { describe, it, expect } from 'vitest';
import { styleConfigAlreadyMatches } from '../DataDrivenStyleEditor';
import type { StyleConfig } from '@/types/api';

// builder-audit #338 COMPLEXITY-01: the three styling effects' infinite-loop skip
// guards now live in one helper. Each case below builds the config the matching
// effect WOULD write, then asserts the guard reports a match (so the effect
// skips the write) — and that a single diverging field breaks the match.
describe('styleConfigAlreadyMatches (COMPLEXITY-01 loop guards)', () => {
  it('returns false when there is no existing config', () => {
    expect(
      styleConfigAlreadyMatches({
        existing: null,
        mode: 'categorical',
        target: 'color',
        column: 'cat',
        ramp: 'Set2',
        reversed: false,
        method: 'equal_interval',
        classCount: 5,
        breaks: [],
        sizeRange: [2, 20],
        categoryValues: ['a'],
      }),
    ).toBe(false);
  });

  describe('categorical (Effect 1)', () => {
    const values = ['a', 'b'];
    const written: StyleConfig = {
      mode: 'categorical',
      column: 'cat',
      ramp: 'Set2',
      reversed: false,
      categories: [
        { value: 'a', color: '#111111' },
        { value: 'b', color: '#222222' },
      ],
    };
    const params = {
      existing: written,
      mode: 'categorical' as const,
      target: 'color' as const,
      column: 'cat',
      ramp: 'Set2',
      reversed: false,
      method: 'equal_interval' as const,
      classCount: 5,
      breaks: [] as number[],
      sizeRange: [2, 20] as [number, number],
      categoryValues: values,
    };

    it('matches its own written config', () => {
      expect(styleConfigAlreadyMatches(params)).toBe(true);
    });

    it('does not match when ramp diverges', () => {
      expect(styleConfigAlreadyMatches({ ...params, ramp: 'Dark2' })).toBe(false);
    });

    it('does not match when category values diverge', () => {
      expect(styleConfigAlreadyMatches({ ...params, categoryValues: ['a', 'c'] })).toBe(false);
    });

    it('treats a missing reversed field as false', () => {
      const noReversed: StyleConfig = { ...written, reversed: undefined };
      expect(styleConfigAlreadyMatches({ ...params, existing: noReversed })).toBe(true);
    });
  });

  describe('graduated color (Effect 2)', () => {
    const written: StyleConfig = {
      mode: 'graduated',
      column: 'pop',
      ramp: 'YlOrRd',
      reversed: false,
      classCount: 5,
      method: 'equal_interval',
      breaks: [1, 2, 3, 4],
      colors: ['#a', '#b', '#c', '#d', '#e'],
      target: 'color',
    };
    const params = {
      existing: written,
      mode: 'graduated' as const,
      target: 'color' as const,
      column: 'pop',
      ramp: 'YlOrRd',
      reversed: false,
      method: 'equal_interval' as const,
      classCount: 5,
      breaks: [1, 2, 3, 4],
      sizeRange: [2, 20] as [number, number],
    };

    it('matches its own written config', () => {
      expect(styleConfigAlreadyMatches(params)).toBe(true);
    });

    it('does not match when classCount diverges', () => {
      expect(styleConfigAlreadyMatches({ ...params, classCount: 6 })).toBe(false);
    });

    it('requires matching breaks only for manual method', () => {
      // non-manual: differing breaks still matches (count-based regeneration)
      expect(styleConfigAlreadyMatches({ ...params, breaks: [9, 9, 9, 9] })).toBe(true);
      // manual: breaks must match exactly
      const manualWritten: StyleConfig = { ...written, method: 'manual', breaks: [10, 20] };
      const manualParams = { ...params, existing: manualWritten, method: 'manual' as const, breaks: [10, 20] };
      expect(styleConfigAlreadyMatches(manualParams)).toBe(true);
      expect(styleConfigAlreadyMatches({ ...manualParams, breaks: [10, 21] })).toBe(false);
    });
  });

  describe('graduated size (Effect 3)', () => {
    const written: StyleConfig = {
      mode: 'graduated',
      column: 'pop',
      ramp: 'YlOrRd',
      classCount: 5,
      method: 'equal_interval',
      breaks: [1, 2, 3, 4],
      target: 'radius',
      sizes: [2, 5, 10, 15, 20],
      sizeRange: [2, 20],
    };
    const params = {
      existing: written,
      mode: 'graduated' as const,
      target: 'radius' as const,
      column: 'pop',
      ramp: 'YlOrRd',
      reversed: false,
      method: 'equal_interval' as const,
      classCount: 5,
      breaks: [1, 2, 3, 4],
      sizeRange: [2, 20] as [number, number],
    };

    it('matches its own written config', () => {
      expect(styleConfigAlreadyMatches(params)).toBe(true);
    });

    it('does not match when sizeRange diverges', () => {
      expect(styleConfigAlreadyMatches({ ...params, sizeRange: [2, 30] })).toBe(false);
    });

    it('does not match when target diverges', () => {
      expect(styleConfigAlreadyMatches({ ...params, target: 'width' })).toBe(false);
    });
  });
});
