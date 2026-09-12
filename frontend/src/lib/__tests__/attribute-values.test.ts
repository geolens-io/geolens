import { afterAll, beforeAll, describe, it, expect } from 'vitest';
import {
  coerceAttributeValue,
  formatAttributeInputValue,
  getAttributeInputType,
  serializeAttributeInputValue,
} from '../attribute-values';

const originalTimezone = process.env.TZ;

beforeAll(() => {
  process.env.TZ = 'America/New_York';
});

afterAll(() => {
  if (originalTimezone === undefined) delete process.env.TZ;
  else process.env.TZ = originalTimezone;
});

describe('getAttributeInputType', () => {
  it('maps postgres types to input kinds', () => {
    expect(getAttributeInputType('integer')).toBe('number-int');
    expect(getAttributeInputType('bigint')).toBe('number-int');
    expect(getAttributeInputType('double precision')).toBe('number-float');
    expect(getAttributeInputType('numeric')).toBe('number-float');
    expect(getAttributeInputType('boolean')).toBe('checkbox');
    expect(getAttributeInputType('date')).toBe('date');
    expect(getAttributeInputType('timestamp with time zone')).toBe('datetime-local');
    expect(getAttributeInputType('text')).toBe('text');
    expect(getAttributeInputType('character varying')).toBe('text');
  });
});

describe('coerceAttributeValue', () => {
  it('empty input means NULL for every type', () => {
    for (const type of ['integer', 'double precision', 'boolean', 'date', 'text']) {
      expect(coerceAttributeValue('', type)).toEqual({ ok: true, value: null });
      expect(coerceAttributeValue('   ', type)).toEqual({ ok: true, value: null });
    }
  });

  it('coerces integers and rejects non-integers', () => {
    expect(coerceAttributeValue('42', 'integer')).toEqual({ ok: true, value: 42 });
    expect(coerceAttributeValue(' -7 ', 'bigint')).toEqual({ ok: true, value: -7 });
    expect(coerceAttributeValue('1.5', 'integer')).toEqual({ ok: false });
    expect(coerceAttributeValue('abc', 'integer')).toEqual({ ok: false });
  });

  it('rejects integers beyond Number precision instead of rounding them', () => {
    expect(coerceAttributeValue('9007199254740991', 'bigint')).toEqual({
      ok: true,
      value: 9007199254740991,
    });
    expect(coerceAttributeValue('9007199254740993', 'bigint')).toEqual({ ok: false });
    expect(coerceAttributeValue('-9007199254740993', 'bigint')).toEqual({ ok: false });
  });

  it('coerces floats and rejects garbage', () => {
    expect(coerceAttributeValue('3.14', 'double precision')).toEqual({ ok: true, value: 3.14 });
    expect(coerceAttributeValue('1e3', 'numeric')).toEqual({ ok: true, value: 1000 });
    expect(coerceAttributeValue('12abc', 'real')).toEqual({ ok: false });
  });

  it('coerces boolean words and rejects others', () => {
    expect(coerceAttributeValue('true', 'boolean')).toEqual({ ok: true, value: true });
    expect(coerceAttributeValue('Yes', 'boolean')).toEqual({ ok: true, value: true });
    expect(coerceAttributeValue('0', 'boolean')).toEqual({ ok: true, value: false });
    expect(coerceAttributeValue('nope', 'boolean')).toEqual({ ok: false });
  });

  it('trims date strings but keeps text verbatim', () => {
    expect(coerceAttributeValue(' 2026-07-11 ', 'date')).toEqual({ ok: true, value: '2026-07-11' });
    expect(coerceAttributeValue(' padded ', 'text')).toEqual({ ok: true, value: ' padded ' });
  });

  it('adds the browser offset to local timezone-aware timestamp edits', () => {
    expect(coerceAttributeValue('2026-07-11T10:30', 'timestamp with time zone')).toEqual({
      ok: true,
      value: '2026-07-11T10:30-04:00',
    });
    expect(coerceAttributeValue('2026-07-11T14:30:00+02:00', 'timestamptz')).toEqual({
      ok: true,
      value: '2026-07-11T14:30:00+02:00',
    });
    expect(coerceAttributeValue('2026-07-11T10:30', 'timestamp without time zone')).toEqual({
      ok: true,
      value: '2026-07-11T10:30',
    });
  });

  it('rejects local timestamps that JavaScript normalizes across a DST gap', () => {
    expect(coerceAttributeValue('2026-03-08T02:30', 'timestamp with time zone'))
      .toEqual({ ok: false });
  });
});

describe('timestamp form values', () => {
  it('displays aware instants in browser-local time and submits changed values as instants', () => {
    expect(formatAttributeInputValue('2026-07-11T14:30:00Z', 'timestamp with time zone'))
      .toBe('2026-07-11T10:30');
    expect(serializeAttributeInputValue('2026-07-11T11:30', 'timestamp with time zone'))
      .toBe('2026-07-11T11:30-04:00');
  });

  it('retains an unchanged aware instant through an ambiguous local time', () => {
    const original = '2026-11-01T06:30:00Z';
    const local = formatAttributeInputValue(original, 'timestamp with time zone');

    expect(local).toBe('2026-11-01T01:30');
    expect(new Date(local).toISOString()).toBe('2026-11-01T05:30:00.000Z');
    expect(serializeAttributeInputValue(local, 'timestamp with time zone', original)).toBe(original);
  });

  it('keeps timezone-free timestamps as wall-clock values', () => {
    const original = '2026-07-11T14:30:00';
    expect(formatAttributeInputValue(original, 'timestamp without time zone'))
      .toBe('2026-07-11T14:30');
    expect(serializeAttributeInputValue(
      '2026-07-11T14:30',
      'timestamp without time zone',
      original,
    )).toBe(original);
  });

  it('limits display precision while preserving unchanged API precision', () => {
    const aware = '2026-07-11T14:30:00.123456Z';
    const naive = '2026-07-11T10:30:00.123456';
    expect(formatAttributeInputValue(aware, 'timestamp with time zone'))
      .toBe('2026-07-11T10:30:00.123');
    expect(formatAttributeInputValue(naive, 'timestamp without time zone'))
      .toBe('2026-07-11T10:30:00.123');
    expect(serializeAttributeInputValue('2026-07-11T10:30:00.123', 'timestamp with time zone', aware))
      .toBe(aware);
    expect(serializeAttributeInputValue('2026-07-11T10:30:00.123', 'timestamp without time zone', naive))
      .toBe(naive);

    const subMillisecond = '2026-07-11T14:30:00.000456Z';
    expect(formatAttributeInputValue(subMillisecond, 'timestamp with time zone'))
      .toBe('2026-07-11T10:30');
    expect(serializeAttributeInputValue('2026-07-11T10:30', 'timestamp with time zone', subMillisecond))
      .toBe(subMillisecond);
    const naiveSubMillisecond = '2026-07-11T10:30:00.000456';
    expect(formatAttributeInputValue(naiveSubMillisecond, 'timestamp without time zone'))
      .toBe('2026-07-11T10:30');
    expect(serializeAttributeInputValue(
      '2026-07-11T10:30',
      'timestamp without time zone',
      naiveSubMillisecond,
    )).toBe(naiveSubMillisecond);
  });
});
