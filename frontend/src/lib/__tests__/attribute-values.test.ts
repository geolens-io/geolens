import { describe, it, expect } from 'vitest';
import { coerceAttributeValue, getAttributeInputType } from '../attribute-values';

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
});
