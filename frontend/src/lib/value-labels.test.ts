import { describe, expect, it } from 'vitest';
import type { AttributeMetadataResponse } from '@/types/api';
import { valueLabelFor, valueLabelsByField } from '@/lib/value-labels';

describe('valueLabelFor', () => {
  const labels = { '1': 'Active', '2': 'Retired' };

  it('finds a label by the code as text, for a number or a string', () => {
    expect(valueLabelFor(labels, 1)).toBe('Active');
    expect(valueLabelFor(labels, '2')).toBe('Retired');
  });

  it('has no label for an unlisted, null or missing code', () => {
    expect(valueLabelFor(labels, 3)).toBeUndefined();
    expect(valueLabelFor(labels, null)).toBeUndefined();
    expect(valueLabelFor(undefined, 1)).toBeUndefined();
  });

  it('does not read inherited object keys as codes', () => {
    expect(valueLabelFor(labels, 'constructor')).toBeUndefined();
    expect(valueLabelFor(labels, '__proto__')).toBeUndefined();
  });
});

describe('valueLabelsByField', () => {
  const attribute = (over: Partial<AttributeMetadataResponse>) =>
    ({ field_name: 'a', is_current: true, value_labels: null, ...over }) as AttributeMetadataResponse;

  it('keeps current columns that have labels', () => {
    const map = valueLabelsByField([
      attribute({ field_name: 'status', value_labels: { '1': 'Active' } }),
      attribute({ field_name: 'plain' }),
      attribute({ field_name: 'old', is_current: false, value_labels: { '1': 'x' } }),
    ]);
    expect([...map.keys()]).toEqual(['status']);
  });
});
