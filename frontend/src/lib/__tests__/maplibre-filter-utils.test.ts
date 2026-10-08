import { describe, it, expect } from 'vitest';
import type { FilterSpecification } from 'maplibre-gl';
import {
  sanitizeNullableNumericFilter,
  parseCanonicalFilter,
  extractFilterField,
  validateRawFilter,
  FilterValidationError,
  maplibreFilterToCql2,
} from '../maplibre-filter-utils';

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

  it('FL-01: returns the SAME reference for an already-sanitized filter (structurally unchanged)', () => {
    const filter = [
      'all',
      ['==', ['to-number', ['get', 'pop'], -1_000_000_000_000], 5],
      ['>', ['to-number', ['get', 'area'], -1_000_000_000_000], 10],
    ] as unknown as FilterSpecification;
    const result = sanitizeNullableNumericFilter(filter);
    expect(result).toBe(filter);
  });

  it('FL-01: still transforms a genuinely-unsanitized bare-get numeric comparison, returning a new array', () => {
    const filter = ['==', ['get', 'pop'], 5] as unknown as FilterSpecification;
    const result = sanitizeNullableNumericFilter(filter);
    expect(result).not.toBe(filter);
    expect(result).toEqual([
      '==',
      ['to-number', ['get', 'pop'], -1_000_000_000_000],
      5,
    ]);
  });
});

// ---------------------------------------------------------------------------
// builder-audit #338 FILT-01 / DRY-01: shared field extractor + canonical parser
// ---------------------------------------------------------------------------
describe('extractFilterField', () => {
  it('unwraps ["get", f]', () => {
    expect(extractFilterField(['get', 'name'])).toBe('name');
  });

  it('FILT-01: unwraps the ["to-number", ["get", f], _] numeric accessor', () => {
    expect(extractFilterField(['to-number', ['get', 'pop'], -1])).toBe('pop');
  });

  it('returns a bare string field name', () => {
    expect(extractFilterField('name')).toBe('name');
  });

  it('returns null for an unrecognized operand', () => {
    expect(extractFilterField(['literal', [1, 2]])).toBeNull();
  });
});

describe('parseCanonicalFilter', () => {
  it('parses a bare comparison as one editable condition with rawValue', () => {
    const result = parseCanonicalFilter(['==', ['get', 'name'], 'foo'] as FilterSpecification);
    expect(result.kind).toBe('editable');
    if (result.kind === 'editable') {
      expect(result.combinator).toBe('all');
      expect(result.conditions[0]).toMatchObject({ field: 'name', operator: '==', value: 'foo', rawValue: 'foo' });
    }
  });

  it('FILT-01: parses a to-number numeric comparison back to field + numeric rawValue', () => {
    const expr = ['>', ['to-number', ['get', 'pop'], -1_000_000_000_000], 5] as FilterSpecification;
    const result = parseCanonicalFilter(expr);
    expect(result.kind).toBe('editable');
    if (result.kind === 'editable') {
      expect(result.conditions[0]).toMatchObject({ field: 'pop', operator: '>', value: '5', rawValue: 5 });
    }
  });

  it('FILT-02: parses ["in", value, ["get", f]] as a contains condition', () => {
    const result = parseCanonicalFilter(['in', 'Main', ['get', 'name']] as unknown as FilterSpecification);
    expect(result.kind).toBe('editable');
    if (result.kind === 'editable') {
      expect(result.conditions[0]).toMatchObject({ field: 'name', operator: 'contains', value: 'Main' });
    }
  });

  it('parses in_list with listValues for preview', () => {
    const expr = ['in', ['get', 'k'], ['literal', ['a', 'b']]] as unknown as FilterSpecification;
    const result = parseCanonicalFilter(expr);
    if (result.kind === 'editable') {
      expect(result.conditions[0]).toMatchObject({ field: 'k', operator: 'in_list', listValues: ['a', 'b'] });
    }
  });

  it('returns opaque (same reference) for an unsupported expression', () => {
    const expr = ['case', ['==', ['get', 'x'], 1], true, false] as unknown as FilterSpecification;
    const result = parseCanonicalFilter(expr);
    expect(result.kind).toBe('opaque');
    if (result.kind === 'opaque') expect(result.raw).toBe(expr);
  });
});

// ---------------------------------------------------------------------------
// builder-audit #338 P1-04: raw-JSON filter validator/normalizer
// ---------------------------------------------------------------------------
describe('validateRawFilter', () => {
  it('treats null and [] as clear (returns null)', () => {
    expect(validateRawFilter(null)).toBeNull();
    expect(validateRawFilter([])).toBeNull();
  });

  it('accepts a valid expression-form comparison verbatim', () => {
    const f = ['==', ['get', 'name'], 'x'];
    expect(validateRawFilter(f)).toEqual(f);
  });

  it('normalizes a legacy bare-field comparison into expression form', () => {
    expect(validateRawFilter(['>', 'population', 100])).toEqual(['>', ['get', 'population'], 100]);
  });

  it('preserves $type / $id legacy pseudo-fields without rewriting to get', () => {
    const f = ['==', '$type', 'Polygon'];
    expect(validateRawFilter(f)).toEqual(f);
  });

  it('rejects a comparison with wrong arity', () => {
    expect(() => validateRawFilter(['==', ['get', 'a']])).toThrow(FilterValidationError);
  });

  it('rejects the legacy bare-field "in" form', () => {
    expect(() => validateRawFilter(['in', 'field', 'a', 'b'])).toThrow(FilterValidationError);
  });

  it('rejects "!" with the wrong number of operands', () => {
    expect(() => validateRawFilter(['!', ['has', 'a'], ['has', 'b']])).toThrow(FilterValidationError);
  });

  it('preserves a structurally-valid opaque filter (match) verbatim', () => {
    const f = ['match', ['get', 'k'], 'a', 1, 0];
    expect(validateRawFilter(f)).toEqual(f);
  });

  it('recurses combinators and normalizes nested legacy comparisons', () => {
    const result = validateRawFilter(['all', ['==', 'name', 'x'], ['has', 'y']]);
    expect(result).toEqual(['all', ['==', ['get', 'name'], 'x'], ['has', 'y']]);
  });
});

describe('maplibreFilterToCql2', () => {
  const p = (field: string) => ({ property: field });
  const isNull = (field: string) => ({ op: 'isNull', args: [p(field)] });

  it('returns null for no filter', () => {
    expect(maplibreFilterToCql2(null)).toBeNull();
    expect(maplibreFilterToCql2(['all'] as unknown as FilterSpecification)).toBeNull();
  });

  it.each([
    [['==', ['get', 'kind'], 'a'], { op: '=', args: [p('kind'), 'a'] }],
    [['>', ['to-number', ['get', 'mag'], -1e12], 5], { op: '>', args: [p('mag'), 5] }],
    [['==', ['get', 'ok'], true], { op: '=', args: [p('ok'), true] }],
    // A feature with no value passes a MapLibre `!=`, so SQL must keep nulls.
    [
      ['!=', ['get', 'kind'], 'a'],
      { op: 'or', args: [isNull('kind'), { op: '<>', args: [p('kind'), 'a'] }] },
    ],
    [['in', ['get', 'kind'], ['literal', ['a', 'b']]], { op: 'in', args: [p('kind'), ['a', 'b']] }],
    [
      ['!', ['in', ['get', 'kind'], ['literal', ['a']]]],
      {
        op: 'or',
        args: [isNull('kind'), { op: 'not', args: [{ op: 'in', args: [p('kind'), ['a']] }] }],
      },
    ],
    // LIKE wildcards in the substring are literals in MapLibre's `in`.
    [['in', '50%_a\\b', ['get', 'name']], { op: 'like', args: [p('name'), '%50\\%\\_a\\\\b%'] }],
    [['has', 'kind'], { op: 'not', args: [isNull('kind')] }],
    [['any', ['!', ['has', 'kind']], ['==', ['get', 'kind'], null]], isNull('kind')],
  ])('translates %j', (filter, expected) => {
    expect(maplibreFilterToCql2(filter as unknown as FilterSpecification)).toEqual(expected);
  });

  it('joins conditions with the combinator', () => {
    expect(
      maplibreFilterToCql2([
        'any',
        ['==', ['get', 'a'], 1],
        ['==', ['get', 'b'], 2],
      ] as unknown as FilterSpecification),
    ).toEqual({
      op: 'or',
      args: [
        { op: '=', args: [p('a'), 1] },
        { op: '=', args: [p('b'), 2] },
      ],
    });
  });

  it.each([
    ['an expression outside the editor subset', ['match', ['get', 'k'], 'a', true, false]],
    ['a nested combinator', ['all', ['any', ['has', 'a'], ['has', 'b']]]],
    ['a legacy pseudo-field', ['has', '$id']],
    ['a non-scalar comparison value', ['==', ['get', 'a'], ['get', 'b']]],
  ])('refuses %s', (_label, filter) => {
    expect(maplibreFilterToCql2(filter as unknown as FilterSpecification)).toBe('unsupported');
  });
});
