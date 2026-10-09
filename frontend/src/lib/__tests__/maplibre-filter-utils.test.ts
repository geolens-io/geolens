import { describe, it, expect } from 'vitest';
import type { FilterSpecification } from 'maplibre-gl';
import {
  sanitizeNullableNumericFilter,
  parseCanonicalFilter,
  extractFilterField,
  validateRawFilter,
  FilterValidationError,
  maplibreFilterToCql2,
  utcTimestampText,
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
    // `to-number` reads a missing value as 0, which passes `< 5` on the map.
    [
      ['<', ['to-number', ['get', 'mag'], 1e12], 5],
      { op: 'or', args: [isNull('mag'), { op: '<', args: [p('mag'), 5] }] },
    ],
    [['!=', ['to-number', ['get', 'mag'], -1e12], 0], { op: '<>', args: [p('mag'), 0] }],
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
    // MapLibre shows no features for it, so dropping it would analyse them all.
    ['an empty any', ['any']],
  ])('refuses %s', (_label, filter) => {
    expect(maplibreFilterToCql2(filter as unknown as FilterSpecification)).toBe('unsupported');
  });

  describe('with the layer columns', () => {
    const columns = [
      { name: 'seen', type: 'date' },
      { name: 'at', type: 'timestamp without time zone' },
      { name: 'atz', type: 'timestamp with time zone' },
      { name: 'Zone', type: 'text' },
      { name: 'ref', type: 'uuid' },
      { name: 'pop', type: 'integer' },
      { name: 'meta', type: 'jsonb' },
      { name: 'props', type: 'json' },
      { name: 'tags', type: 'ARRAY' },
      { name: 'Odd Col', type: 'text' },
    ];
    const convert = (filter: unknown) =>
      maplibreFilterToCql2(filter as FilterSpecification, columns);

    it.each([
      [['==', ['get', 'seen'], '2024-02-01'], { op: '=', args: [p('seen'), { date: '2024-02-01' }] }],
      [
        ['>=', ['get', 'at'], '2024-02-01 06:30:00'],
        { op: '>=', args: [p('at'), { timestamp: '2024-02-01T06:30:00Z' }] },
      ],
      [
        ['==', ['get', 'at'], '2024-02-01 06:30:00.25'],
        { op: '=', args: [p('at'), { timestamp: '2024-02-01T06:30:00.25Z' }] },
      ],
      [
        ['in', ['get', 'seen'], ['literal', ['2024-01-01', '2024-03-01']]],
        { op: 'in', args: [p('seen'), [{ date: '2024-01-01' }, { date: '2024-03-01' }]] },
      ],
      [
        ['!=', ['get', 'seen'], '2024-01-01'],
        {
          op: 'or',
          args: [isNull('seen'), { op: '<>', args: [p('seen'), { date: '2024-01-01' }] }],
        },
      ],
      [['==', ['get', 'Zone'], 'north'], { op: '=', args: [p('Zone'), 'north'] }],
      [['in', 'ort', ['get', 'Zone']], { op: 'like', args: [p('Zone'), '%ort%'] }],
      [
        ['==', ['get', 'ref'], '6f1c3a52-2b8e-4f0e-9a51-3d6a8f9c0b11'],
        { op: '=', args: [p('ref'), '6f1c3a52-2b8e-4f0e-9a51-3d6a8f9c0b11'] },
      ],
      [['has', 'atz'], { op: 'not', args: [isNull('atz')] }],
      [
        ['<', ['get', 'atz'], '2024-11-03T06:15:00+00:00'],
        { op: '<', args: [p('atz'), { timestamp: '2024-11-03T06:15:00Z' }] },
      ],
      [
        ['==', ['get', 'atz'], '2024-11-03T06:15:00.5+00:00'],
        { op: '=', args: [p('atz'), { timestamp: '2024-11-03T06:15:00.5Z' }] },
      ],
      [
        ['>=', ['get', 'atz'], '2024-11-03T05:30:00+00:00'],
        { op: '>=', args: [p('atz'), { timestamp: '2024-11-03T05:30:00Z' }] },
      ],
      [['==', ['get', 'pop'], 5], { op: '=', args: [p('pop'), 5] }],
      [['has', 'seen'], { op: 'not', args: [isNull('seen')] }],
      // A column the layer does not list is sent untyped; the server decides.
      [['==', ['get', 'ghost'], '2024-01-01'], { op: '=', args: [p('ghost'), '2024-01-01'] }],
    ])('translates %j', (filter, expected) => {
      expect(convert(filter)).toEqual(expected);
    });

    it.each([
      ['a jsonb column', ['==', ['get', 'meta'], 'x']],
      ['a json column', ['has', 'props']],
      ['an array column', ['any', ['!', ['has', 'tags']], ['==', ['get', 'tags'], null]]],
      ['a name CQL2 cannot address', ['==', ['get', 'Odd Col'], 'x']],
      ['a date that is not a date', ['==', ['get', 'seen'], 'last week']],
      ['a date that is not on the calendar', ['==', ['get', 'seen'], '2024-02-30']],
      ['a date in another spelling', ['==', ['get', 'seen'], '2024-2-1']],
      // The map compares tile text: "2024-02-01" never equals "2024-02-01 00:00:00".
      ['a date compared with a timestamp', ['>', ['get', 'at'], '2024-02-01']],
      ['an RFC 3339 timestamp', ['==', ['get', 'at'], '2024-02-01T06:30:00Z']],
      ['a fraction with a trailing zero', ['==', ['get', 'at'], '2024-02-01 06:30:00.50']],
      // The tile carries "2024-02-01T06:30:00+00:00", so these never compare equal on the map.
      ['a timestamptz in PostgreSQL text form', ['<', ['get', 'atz'], '2024-02-01 06:30:00+00']],
      ['a timestamptz written with Z', ['==', ['get', 'atz'], '2024-02-01T06:30:00Z']],
      ['a timestamptz with another offset', ['==', ['get', 'atz'], '2024-02-01T01:30:00-05:00']],
      ['a timestamptz fraction with a trailing zero', ['==', ['get', 'atz'], '2024-02-01T06:30:00.50+00:00']],
      ['a timestamptz off the calendar', ['==', ['get', 'atz'], '2024-02-30T06:30:00+00:00']],
      ['an uppercase uuid', ['==', ['get', 'ref'], '6F1C3A52-2B8E-4F0E-9A51-3D6A8F9C0B11']],
      ['a value that is not a uuid', ['==', ['get', 'ref'], 'abc']],
      ['a date list with a bad entry', ['in', ['get', 'seen'], ['literal', ['2024-01-01', 'x']]]],
      ['a substring test on a uuid', ['in', 'ab', ['get', 'ref']]],
      ['one json condition among others', ['all', ['==', ['get', 'Zone'], 'n'], ['has', 'meta']]],
    ])('refuses %s', (_label, filter) => {
      expect(convert(filter)).toBe('unsupported');
    });
  });
});

describe('utcTimestampText', () => {
  it.each([
    ['2024-11-03T06:15:00+00:00', '2024-11-03T06:15:00+00:00'],
    ['2024-11-03 06:15', '2024-11-03T06:15:00+00:00'],
    ['2024-11-03T06:15:00Z', '2024-11-03T06:15:00+00:00'],
    ['2024-11-03t06:15:00z', '2024-11-03T06:15:00+00:00'],
    ['2024-11-03 01:15:00-05', '2024-11-03T06:15:00+00:00'],
    ['2024-11-03 01:30:00-04:00', '2024-11-03T05:30:00+00:00'],
    ['2024-11-03 11:45:00+0530', '2024-11-03T06:15:00+00:00'],
    ['2024-12-31 23:30:00-01:00', '2025-01-01T00:30:00+00:00'],
    ['2024-11-03 06:15:00.500', '2024-11-03T06:15:00.5+00:00'],
    ['2024-11-03 06:15:00.000', '2024-11-03T06:15:00+00:00'],
    ['2024-11-03 06:15:00.123456', '2024-11-03T06:15:00.123456+00:00'],
    ['  0099-01-01 00:00  ', '0099-01-01T00:00:00+00:00'],
  ])('reads %j as %j', (typed, expected) => {
    expect(utcTimestampText(typed)).toBe(expected);
  });

  it.each([
    ['a date alone', '2024-11-03'],
    ['a date off the calendar', '2024-02-30 06:00'],
    ['an hour past the day', '2024-11-03 24:00'],
    ['free text', 'yesterday'],
    ['seven fraction digits', '2024-11-03 06:15:00.1234567'],
    ['offset minutes past the hour', '2024-01-01 00:00+00:99'],
    ['an offset past the range PostgreSQL accepts', '2024-01-01 00:00+16:00'],
  ])('rejects %s', (_label, typed) => {
    expect(utcTimestampText(typed)).toBeNull();
  });

  it('writes text the map orders the way time is ordered across a DST change', () => {
    // 05:30Z is 01:30 EDT and 06:15Z is 01:15 EST: local text sorts these backwards.
    const earlier = utcTimestampText('2024-11-03 01:30:00-04:00')!;
    const later = utcTimestampText('2024-11-03 01:15:00-05:00')!;
    const laterFraction = utcTimestampText('2024-11-03 01:15:00.5-05:00')!;
    expect([laterFraction, later, earlier].sort()).toEqual([earlier, later, laterFraction]);
  });
});
