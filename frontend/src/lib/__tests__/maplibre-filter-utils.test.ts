import { describe, it, expect } from 'vitest';
import type { FilterSpecification } from 'maplibre-gl';
import { sanitizeNullableNumericFilter } from '../maplibre-filter-utils';

// ---------------------------------------------------------------------------
// EDIT-03: empty-array -> null boundary hardening in sanitizeNullableNumericFilter
// ---------------------------------------------------------------------------
describe('sanitizeNullableNumericFilter', () => {
  it('EDIT-03 — returns null for an empty-array filter (never lets [] reach setFilter)', () => {
    expect(sanitizeNullableNumericFilter([] as unknown as FilterSpecification)).toBeNull();
  });

  it('returns null for null and undefined (regression guard — unchanged behavior)', () => {
    expect(sanitizeNullableNumericFilter(null)).toBeNull();
    expect(sanitizeNullableNumericFilter(undefined)).toBeNull();
  });

  it('wraps a non-empty numeric comparison with the nullable-safe accessor (existing behavior preserved)', () => {
    const filter = ['==', ['get', 'pop'], 5] as unknown as FilterSpecification;
    const result = sanitizeNullableNumericFilter(filter);
    expect(result).toEqual([
      '==',
      ['to-number', ['get', 'pop'], -1_000_000_000_000],
      5,
    ]);
  });
});
