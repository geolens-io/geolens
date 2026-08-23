import { describe, it, expect } from 'vitest';
import { formatFeaturePropertyValue } from '../feature-property-value';

describe('formatFeaturePropertyValue', () => {
  it('returns null for null/undefined so callers can render their own empty text', () => {
    expect(formatFeaturePropertyValue(null, 'en', 'True', 'False')).toBeNull();
    expect(formatFeaturePropertyValue(undefined, 'en', 'True', 'False')).toBeNull();
  });

  it('renders booleans using the caller-supplied, locale-aware labels', () => {
    expect(formatFeaturePropertyValue(true, 'en', 'Yes', 'No')).toBe('Yes');
    expect(formatFeaturePropertyValue(false, 'en', 'Yes', 'No')).toBe('No');
  });

  it('formats integers without decimals and floats to 4 fraction digits', () => {
    expect(formatFeaturePropertyValue(1234, 'en', 'True', 'False')).toBe('1,234');
    expect(formatFeaturePropertyValue(1.23456789, 'en', 'True', 'False')).toBe('1.2346');
  });

  it('fix(#1627): renders a plain object as its JSON text, not [object Object]', () => {
    const result = formatFeaturePropertyValue({ a: 1, b: 'two' }, 'en', 'True', 'False');
    expect(result).toBe('{"a":1,"b":"two"}');
    expect(result).not.toContain('[object Object]');
  });

  it('fix(#1627): renders a nested array as its JSON text', () => {
    const result = formatFeaturePropertyValue([1, { x: 'y' }, [2, 3]], 'en', 'True', 'False');
    expect(result).toBe('[1,{"x":"y"},[2,3]]');
  });

  it('falls back to String(value) when the object is circular', () => {
    const circular: Record<string, unknown> = { name: 'loop' };
    circular.self = circular;
    const result = formatFeaturePropertyValue(circular, 'en', 'True', 'False');
    expect(result).toBe(String(circular));
    expect(result).not.toBeNull();
  });

  it('renders plain strings unchanged via String()', () => {
    expect(formatFeaturePropertyValue('hello', 'en', 'True', 'False')).toBe('hello');
  });
});
