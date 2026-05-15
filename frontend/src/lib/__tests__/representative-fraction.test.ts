/**
 * Unit tests for the representative-fraction formatter.
 * SP-12 — closes the last v1009.1 followup.
 *
 * Locks Rule A: trailing ".0" is dropped.
 *   1000 → "1k"  (not "1.0k")
 *   999999 → "1M" (rolls to M tier; 999999/1e6 ≈ 1.0 → "1M" — Rule A: .0 dropped)
 */

import { describe, expect, it } from 'vitest';
import {
  formatRepresentativeFraction,
  formatRfValue,
  metersPerPixel,
} from '../representative-fraction';

// ---------------------------------------------------------------------------
// formatRfValue — compact denominator formatter
// ---------------------------------------------------------------------------

describe('formatRfValue', () => {
  describe('clamp: non-finite / NaN / sub-1 inputs', () => {
    it('returns "1" for 0', () => expect(formatRfValue(0)).toBe('1'));
    it('returns "1" for 0.5', () => expect(formatRfValue(0.5)).toBe('1'));
    it('returns "1" for negative', () => expect(formatRfValue(-100)).toBe('1'));
    it('returns "1" for Infinity', () => expect(formatRfValue(Infinity)).toBe('1'));
    it('returns "1" for NaN', () => expect(formatRfValue(NaN)).toBe('1'));
  });

  describe('plain integer range (< 1 000)', () => {
    it('formats 850 as "850"', () => expect(formatRfValue(850)).toBe('850'));
    it('formats 999 as "999"', () => expect(formatRfValue(999)).toBe('999'));
    it('formats 1 as "1"', () => expect(formatRfValue(1)).toBe('1'));
  });

  describe('k range (1 000 – 999 999) — Rule A: drop trailing ".0"', () => {
    // 1000 → 1000/1000 = 1.0 → Rule A drops .0 → "1k"
    it('formats 1000 as "1k" (Rule A: trailing .0 dropped)', () =>
      expect(formatRfValue(1000)).toBe('1k'));

    it('formats 1234 as "1.2k"', () => expect(formatRfValue(1234)).toBe('1.2k'));

    // 99499/1000 = 99.499 → rounds to 99.5 → "99.5k"
    it('formats 99499 as "99.5k"', () => expect(formatRfValue(99499)).toBe('99.5k'));

    // 288000/1000 = 288.0 → Rule A → "288k"
    it('formats 288000 as "288k"', () => expect(formatRfValue(288000)).toBe('288k'));

    // 999000/1000 = 999.0 → "999k"
    it('formats 999000 as "999k"', () => expect(formatRfValue(999000)).toBe('999k'));
  });

  describe('M range (>= 1 000 000) — Rule A: drop trailing ".0"', () => {
    // 999999/1e6 = 0.999999 → rounds to 1.0 → Rule A → "1M"
    it('formats 999999 as "1M" (rounds up to M tier; Rule A drops .0)', () =>
      expect(formatRfValue(999999)).toBe('1M'));

    it('formats 1234567 as "1.2M"', () => expect(formatRfValue(1234567)).toBe('1.2M'));

    // 120000000/1e6 = 120.0 → "120M"
    it('formats 120000000 as "120M"', () => expect(formatRfValue(120000000)).toBe('120M'));
  });
});

// ---------------------------------------------------------------------------
// metersPerPixel — classic Web Mercator formula
// ---------------------------------------------------------------------------

describe('metersPerPixel', () => {
  it('returns ≈ 156543.034 at equator zoom 0', () => {
    expect(metersPerPixel(0, 0)).toBeCloseTo(156543.034, 0);
  });

  it('returns ≈ 38.218 at equator zoom 12', () => {
    expect(metersPerPixel(0, 12)).toBeCloseTo(38.218, 2);
  });

  it('returns ≈ 19.109 at lat 60° zoom 12 (cos(60°) = 0.5)', () => {
    expect(metersPerPixel(60, 12)).toBeCloseTo(19.109, 2);
  });

  it('returns ≈ 19.109 at lat -60° zoom 12 (cos symmetric)', () => {
    expect(metersPerPixel(-60, 12)).toBeCloseTo(19.109, 2);
  });
});

// ---------------------------------------------------------------------------
// formatRepresentativeFraction — composed helper
// ---------------------------------------------------------------------------

describe('formatRepresentativeFraction', () => {
  it('returns a 1:1XXk value at lat=0, zoom=12 (sanity check)', () => {
    // At equator z=12: M_PER_PX ≈ 38.22, denominator ≈ 144 478 → ~"1:144k"
    // Accept any value in the 100k–199k range (allows for rounding variation).
    const result = formatRepresentativeFraction(0, 12);
    expect(result).toMatch(/^1:1\d\d(\.\d)?k$/);
  });

  it('returns a plain-integer denominator at very high zoom mid-latitude', () => {
    // At lat=45, zoom=21 the denominator is ~750 — in plain-int range.
    const result = formatRepresentativeFraction(45, 21);
    expect(result).toMatch(/^1:\d+$/);
  });

  it('returns "1:1" at lat=90 (cos(90°)=0 → denominator collapses → clamped)', () => {
    expect(formatRepresentativeFraction(90, 12)).toBe('1:1');
  });
});
