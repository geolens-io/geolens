import { featureFilter } from '@maplibre/maplibre-gl-style-spec';
import { describe, it, expect } from 'vitest';
import type { FilterSpecification } from 'maplibre-gl';
import {
  sanitizeNullableNumericFilter,
  parseCanonicalFilter,
  validateRawFilter,
  FilterValidationError,
  maplibreFilterToCql2,
  layerFilterToServerCql2,
  legacyFilterToExpression,
  isCql2LiteralCompatible,
  utcTimestampText,
} from '../maplibre-filter-utils';

// MapLibre's own filter evaluator, so the test sees what the map draws.
function drawn(filter: FilterSpecification | null, props: Record<string, unknown>): boolean {
  const test = featureFilter(filter ?? undefined, 'layers[0].filter').filter;
  return test({ zoom: 0 }, { type: 1, properties: props } as never);
}

// ---------------------------------------------------------------------------
// Empty-array -> null boundary hardening in sanitizeNullableNumericFilter
// ---------------------------------------------------------------------------
describe('sanitizeNullableNumericFilter', () => {
  it('EDIT-03 — returns null for an empty-array filter (never lets [] reach setFilter)', () => {
    expect(sanitizeNullableNumericFilter([] as unknown as FilterSpecification)).toBeNull();
  });

  it('returns null for null and undefined (regression guard — unchanged behavior)', () => {
    expect(sanitizeNullableNumericFilter(null)).toBeNull();
    expect(sanitizeNullableNumericFilter(undefined)).toBeNull();
  });

  it('guards a numeric comparison with a type check so a null value never satisfies it', () => {
    const filter = ['==', ['get', 'pop'], 5] as unknown as FilterSpecification;
    const result = sanitizeNullableNumericFilter(filter);
    expect(result).toEqual(['all', ['!=', ['typeof', ['get', 'pop']], 'null'], ['==', ['to-number', ['get', 'pop'], -1_000_000_000_000], 5]]);
  });

  it.each([
    ['==', 0],
    ['>=', -5],
    ['<', 3],
    ['!=', 0],
  ])('a null value does not match %s %s on the map', (operator, value) => {
    const result = sanitizeNullableNumericFilter([
      operator,
      ['get', 'n'],
      value,
    ] as unknown as FilterSpecification);

    expect(drawn(result, { n: null })).toBe(false);
    expect(drawn(result, {})).toBe(false);
    expect(drawn(result, { n: value })).toBe(operator === '==' || operator === '>=');
    // A value that satisfies the comparison still draws.
    expect(drawn(result, { n: operator === '<' ? value - 1 : value + 1 })).toBe(operator !== '==');
  });

  it('keeps a null out of a negated numeric comparison too', () => {
    const negated = ['!', ['==', ['to-number', ['get', 'n'], -1_000_000_000_000], 0]] as unknown as FilterSpecification;
    const result = sanitizeNullableNumericFilter(negated);

    expect(drawn(result, { n: null })).toBe(false);
    expect(drawn(result, {})).toBe(false);
    expect(drawn(result, { n: 0 })).toBe(false);
    expect(drawn(result, { n: 4 })).toBe(true);
    expect(sanitizeNullableNumericFilter(result)).toBe(result);
  });

  it('leaves a hand-authored to-number fallback as it is', () => {
    const authored = ['>=', ['to-number', ['get', 'score'], 100], 5] as unknown as FilterSpecification;
    const result = sanitizeNullableNumericFilter(authored);

    expect(result).toBe(authored);
    expect(drawn(result, { score: 'unknown' })).toBe(true);
  });

  it('still reads a numeric string as a number, as to-number always did', () => {
    const legacy = ['>=', ['to-number', ['get', 'score'], -1_000_000_000_000], 5] as unknown as FilterSpecification;
    const result = sanitizeNullableNumericFilter(legacy);

    expect(drawn(result, { score: '10' })).toBe(true);
    expect(drawn(result, { score: 10 })).toBe(true);
    expect(drawn(result, { score: null })).toBe(false);
    expect(drawn(result, {})).toBe(false);
  });

  it('rewrites a saved legacy to-number accessor to the guarded form', () => {
    const legacy = ['==', ['to-number', ['get', 'pop'], -1_000_000_000_000], 0] as unknown as FilterSpecification;
    expect(sanitizeNullableNumericFilter(legacy)).toEqual(['all', ['!=', ['typeof', ['get', 'pop']], 'null'], ['==', ['to-number', ['get', 'pop'], -1_000_000_000_000], 0]]);
  });

  it('keeps a guarded filter as it is, however often it is sanitized', () => {
    const once = sanitizeNullableNumericFilter(['all', ['<', ['get', 'pop'], 3]] as unknown as FilterSpecification);
    expect(sanitizeNullableNumericFilter(once)).toBe(once);
  });

  it('FL-01: returns the SAME reference for an already-sanitized filter (structurally unchanged)', () => {
    const filter = [
      'all',
      ['all', ['!=', ['typeof', ['get', 'pop']], 'null'], ['==', ['to-number', ['get', 'pop'], -1_000_000_000_000], 5]],
      ['all', ['!=', ['typeof', ['get', 'area']], 'null'], ['>', ['to-number', ['get', 'area'], -1_000_000_000_000], 10]],
    ] as unknown as FilterSpecification;
    const result = sanitizeNullableNumericFilter(filter);
    expect(result).toBe(filter);
  });

  it('FL-01: still transforms a genuinely-unsanitized bare-get numeric comparison, returning a new array', () => {
    const filter = ['==', ['get', 'pop'], 5] as unknown as FilterSpecification;
    const result = sanitizeNullableNumericFilter(filter);
    expect(result).not.toBe(filter);
    expect(result).toEqual(['all', ['!=', ['typeof', ['get', 'pop']], 'null'], ['==', ['to-number', ['get', 'pop'], -1_000_000_000_000], 5]]);
  });
});

// ---------------------------------------------------------------------------
// Canonical parser
// ---------------------------------------------------------------------------
describe('parseCanonicalFilter', () => {
  it('parses a bare comparison as one editable condition with rawValue', () => {
    const result = parseCanonicalFilter(['==', ['get', 'name'], 'foo'] as FilterSpecification);
    expect(result.kind).toBe('editable');
    if (result.kind === 'editable') {
      expect(result.combinator).toBe('all');
      expect(result.conditions[0]).toMatchObject({ field: 'name', operator: '==', value: 'foo', rawValue: 'foo' });
    }
  });

  it('parses the null-safe numeric comparison back to one condition', () => {
    const expr = ['all', ['!=', ['typeof', ['get', 'pop']], 'null'], ['>', ['to-number', ['get', 'pop'], -1_000_000_000_000], 5]] as FilterSpecification;
    expect(parseCanonicalFilter(expr)).toEqual({
      kind: 'editable',
      combinator: 'all',
      conditions: [{ field: 'pop', operator: '>', value: '5', rawValue: 5, toNumber: true, nullGuarded: true }],
    });
  });

  it('does not offer a guarded comparison with its own fallback to the editor', () => {
    const expr = ['all', ['!=', ['typeof', ['get', 'pop']], 'null'], ['>', ['to-number', ['get', 'pop'], 7], 5]] as FilterSpecification;
    expect(parseCanonicalFilter(expr).kind).toBe('opaque');
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
// Raw-JSON filter validator/normalizer
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

describe('isCql2LiteralCompatible', () => {
  it.each([
    ['non-scalar', {}, undefined, false],
    ['non-finite', Infinity, undefined, false],
    ['invalid date', 'last week', 'date', false],
    ['valid date', '2024-01-01', 'date', true],
    ['untyped scalar', '5', undefined, true],
  ] as const)('checks %s', (_label, value, pgType, compatible) => {
    expect(isCql2LiteralCompatible(value, pgType)).toBe(compatible);
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
    // The editor's own bare accessor is migrated to the null-guarded form, as on the map.
    [['<', ['to-number', ['get', 'mag'], 1e12], 5], { op: '<', args: [p('mag'), 5] }],
    // A hand-authored fallback is left alone: `to-number` reads a missing value as 0, which passes `< 5`.
    [
      ['<', ['to-number', ['get', 'mag'], 7], 5],
      { op: 'or', args: [isNull('mag'), { op: '<', args: [p('mag'), 5] }] },
    ],
    [['!=', ['to-number', ['get', 'mag'], -1e12], 0], { op: '<>', args: [p('mag'), 0] }],
    // Behind the null guard, a null never satisfies it, on the map or in SQL.
    [['all', ['!=', ['typeof', ['get', 'mag']], 'null'], ['<', ['to-number', ['get', 'mag'], 1_000_000_000_000], 5]], { op: '<', args: [p('mag'), 5] }],
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

  it('nests and/or for nested all/any groups, as a saved filter and a dashboard pick make', () => {
    const notNull = (field: string) => ({ op: 'not', args: [isNull(field)] });
    expect(
      maplibreFilterToCql2([
        'all',
        ['any', ['==', ['get', 'zone'], 'A'], ['==', ['get', 'zone'], 'B']],
        ['any', ['in', ['get', 'kind'], ['literal', ['park']]], ['any', ['!', ['has', 'kind']], ['==', ['get', 'kind'], null]]],
        ['all', ['has', 'a'], ['any', ['has', 'b'], ['has', 'c']]],
      ] as unknown as FilterSpecification),
    ).toEqual({
      op: 'and',
      args: [
        { op: 'or', args: [{ op: '=', args: [p('zone'), 'A'] }, { op: '=', args: [p('zone'), 'B'] }] },
        { op: 'or', args: [{ op: 'in', args: [p('kind'), ['park']] }, isNull('kind')] },
        { op: 'and', args: [notNull('a'), { op: 'or', args: [notNull('b'), notNull('c')] }] },
      ],
    });
    // A group with no conditions matches everything: dropped from an `all`, and it makes an `any` match everything.
    expect(maplibreFilterToCql2(['all', ['all'], ['has', 'a']] as unknown as FilterSpecification)).toEqual(notNull('a'));
    expect(maplibreFilterToCql2(['any', ['all'], ['has', 'a']] as unknown as FilterSpecification)).toBeNull();
  });

  it.each([
    ['an expression outside the editor subset', ['match', ['get', 'k'], 'a', true, false]],
    ['a nested combinator holding an unsupported member', ['all', ['any', ['has', 'a'], ['match', ['get', 'k'], 'a', true, false]]]],
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
      // Scalar compatibility for cluster tiles must not narrow shared analysis conversion.
      [['==', ['get', 'pop'], '5'], { op: '=', args: [p('pop'), '5'] }],
      [['==', ['get', 'Zone'], 5], { op: '=', args: [p('Zone'), 5] }],
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
      // The server's CQL2 timestamps cover years 1 to 9999 only.
      ['a BC timestamptz', ['==', ['get', 'atz'], '-0043-03-15T12:00:00+00:00']],
      ['an infinite timestamptz', ['<', ['get', 'atz'], 'infinity']],
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

describe('legacy saved filters', () => {
  const p = (field: string) => ({ property: field });
  const isNull = (field: string) => ({ op: 'isNull', args: [p(field)] });
  const columns = [
    { name: 'kind', type: 'text' },
    { name: 'pop', type: 'integer' },
    { name: 'seen', type: 'date' },
  ];
  const features = [
    { kind: 'a', pop: 5, seen: '2024-01-01' },
    { kind: 'b', pop: 12, seen: '2024-06-01' },
    { kind: 'c', pop: 7 },
    { pop: 0 },
    {},
  ];

  it.each([
    [['in', 'kind', 'a', 'b'], { op: 'in', args: [p('kind'), ['a', 'b']] }],
    [['in', 'pop', 5, 12], { op: 'in', args: [p('pop'), [5, 12]] }],
    [
      ['!in', 'kind', 'a'],
      { op: 'or', args: [isNull('kind'), { op: 'not', args: [{ op: 'in', args: [p('kind'), ['a']] }] }] },
    ],
    [['==', 'kind', 'a'], { op: 'in', args: [p('kind'), ['a']] }],
    [
      ['!=', 'pop', 5],
      { op: 'or', args: [isNull('pop'), { op: 'not', args: [{ op: 'in', args: [p('pop'), [5]] }] }] },
    ],
    [['>', 'pop', 6], { op: '>', args: [p('pop'), 6] }],
    [['!has', 'kind'], isNull('kind')],
    [
      ['all', ['in', 'kind', 'a', 'c'], ['>=', 'pop', 5]],
      { op: 'and', args: [{ op: 'in', args: [p('kind'), ['a', 'c']] }, { op: '>=', args: [p('pop'), 5] }] },
    ],
    [
      ['any', ['==', 'kind', 'a'], ['<', 'pop', 6]],
      { op: 'or', args: [{ op: 'in', args: [p('kind'), ['a']] }, { op: '<', args: [p('pop'), 6] }] },
    ],
  ])('translates %j to the CQL2 that keeps the features the map draws', (legacy, expected) => {
    const filter = legacy as unknown as FilterSpecification;
    expect(maplibreFilterToCql2(filter, columns)).toEqual(expected);
    const translated = legacyFilterToExpression(filter);
    expect(translated).not.toBe('unsupported');
    for (const feature of features) {
      expect(drawn(translated as FilterSpecification, feature)).toBe(drawn(filter, feature));
    }
  });

  it.each(['<', '<=', '>', '>='])('keeps a legacy %s order comparison strict about number values', (op) => {
    const filter = [op, 'pop', 6] as unknown as FilterSpecification;
    const translated = legacyFilterToExpression(filter) as FilterSpecification;
    for (const pop of [12, 6, 5, '12', '5', null, true]) {
      expect(drawn(translated, { pop })).toBe(drawn(filter, { pop }));
    }
    expect(drawn(translated, { pop: '12' })).toBe(false);
    expect(drawn(translated, { pop: '5' })).toBe(false);
  });

  it('types the values as the expression forms do', () => {
    // Text values can't be compared with an integer column, so the server would refuse them.
    const textOnInteger = ['in', 'pop', '5', '12'] as unknown as FilterSpecification;
    expect(layerFilterToServerCql2(textOnInteger, columns)).toBe(
      layerFilterToServerCql2(['in', ['get', 'pop'], ['literal', ['5', '12']]] as FilterSpecification, columns),
    );
    expect(layerFilterToServerCql2(textOnInteger, columns)).toBe('unsupported');
    expect(layerFilterToServerCql2(['in', 'kind', 'a'] as unknown as FilterSpecification, columns)).toEqual({
      op: 'in',
      args: [p('kind'), ['a']],
    });
  });

  it.each([
    ['none', ['none', ['==', 'kind', 'a']]],
    ['a $type test', ['==', '$type', 'Point']],
    ['an $id list', ['in', '$id', 1, 2]],
    ['a null comparison', ['==', 'kind', null]],
    ['a text order comparison', ['<', 'seen', '2024-03-01']],
  ])('refuses %s', (_label, legacy) => {
    const filter = legacy as unknown as FilterSpecification;
    expect(legacyFilterToExpression(filter)).toBe('unsupported');
    expect(maplibreFilterToCql2(filter, columns)).toBe('unsupported');
  });

  it('leaves an expression filter alone', () => {
    const filter = ['in', ['get', 'kind'], ['literal', ['a']]] as FilterSpecification;
    expect(legacyFilterToExpression(filter)).toBe(filter);
    expect(legacyFilterToExpression(null)).toBeNull();
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
