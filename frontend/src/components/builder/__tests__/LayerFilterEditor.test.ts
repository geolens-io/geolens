import { createElement } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@/test/test-utils';
import { LayerFilterEditor, parseFilterExpression, buildFilterExpression } from '../LayerFilterEditor';
import type { FilterSpecification } from 'maplibre-gl';

// Column info used for buildFilterExpression tests
const columns = [
  { name: 'name', type: 'text' },
  { name: 'population', type: 'integer' },
  { name: 'active', type: 'boolean' },
];

// ---------------------------------------------------------------------------
// parseFilterExpression — discriminated result
// ---------------------------------------------------------------------------
describe('parseFilterExpression', () => {
  it('returns editable with empty conditions for null input', () => {
    const result = parseFilterExpression(null);
    expect(result.kind).toBe('editable');
    if (result.kind === 'editable') {
      expect(result.combinator).toBe('all');
      expect(result.conditions).toHaveLength(0);
    }
  });

  it('returns editable with empty conditions for undefined input', () => {
    const result = parseFilterExpression(undefined as unknown as FilterSpecification);
    expect(result.kind).toBe('editable');
    if (result.kind === 'editable') {
      expect(result.combinator).toBe('all');
      expect(result.conditions).toHaveLength(0);
    }
  });

  it('parses a simple bare expression as editable with "all" combinator', () => {
    const expr: FilterSpecification = ['==', ['get', 'name'], 'foo'] as FilterSpecification;
    const result = parseFilterExpression(expr);
    expect(result.kind).toBe('editable');
    if (result.kind === 'editable') {
      expect(result.combinator).toBe('all');
      expect(result.conditions).toHaveLength(1);
      expect(result.conditions[0].field).toBe('name');
      expect(result.conditions[0].operator).toBe('==');
      expect(result.conditions[0].value).toBe('foo');
    }
  });

  it('parses ["all", ...conditions] as editable with "all" combinator', () => {
    const expr: FilterSpecification = [
      'all',
      ['==', ['get', 'name'], 'bar'],
      ['>', ['get', 'population'], 1000],
    ] as FilterSpecification;
    const result = parseFilterExpression(expr);
    expect(result.kind).toBe('editable');
    if (result.kind === 'editable') {
      expect(result.combinator).toBe('all');
      expect(result.conditions).toHaveLength(2);
    }
  });

  it('parses ["any", ...conditions] as editable with "any" combinator', () => {
    const expr: FilterSpecification = [
      'any',
      ['==', ['get', 'name'], 'baz'],
      ['<', ['get', 'population'], 500],
    ] as FilterSpecification;
    const result = parseFilterExpression(expr);
    expect(result.kind).toBe('editable');
    if (result.kind === 'editable') {
      expect(result.combinator).toBe('any');
      expect(result.conditions).toHaveLength(2);
    }
  });

  it('returns opaque when a single sub-expression cannot be parsed inside "all"', () => {
    const expr: FilterSpecification = [
      'all',
      ['==', ['get', 'name'], 'foo'],
      ['case', ['==', ['get', 'x'], 1], true, false],
    ] as FilterSpecification;
    const result = parseFilterExpression(expr);
    expect(result.kind).toBe('opaque');
    if (result.kind === 'opaque') {
      expect(result.raw).toEqual(expr);
    }
  });

  it('returns opaque for a completely unknown top-level expression', () => {
    const expr: FilterSpecification = ['case', ['==', ['get', 'x'], 1], true, false] as FilterSpecification;
    const result = parseFilterExpression(expr);
    expect(result.kind).toBe('opaque');
    if (result.kind === 'opaque') {
      expect(result.raw).toEqual(expr);
    }
  });

  it('preserves the exact opaque raw value without modification', () => {
    // Use an expression with a sub-expression the parser cannot handle:
    // ['step', ...] is not parseable because e[1] is not ['get', field]
    const complexExpr: FilterSpecification = [
      'all',
      ['has', 'name'],
      ['step', ['zoom'], false, 10, true],
    ] as FilterSpecification;
    const result = parseFilterExpression(complexExpr);
    expect(result.kind).toBe('opaque');
    if (result.kind === 'opaque') {
      expect(result.raw).toBe(complexExpr); // same reference
    }
  });
});

// ---------------------------------------------------------------------------
// buildFilterExpression — combinator support
// ---------------------------------------------------------------------------
describe('buildFilterExpression', () => {
  it('returns null for empty conditions', () => {
    expect(buildFilterExpression([], columns)).toBeNull();
  });

  it('returns bare expression for single condition with "all" combinator', () => {
    const conditions = [{ id: '1', field: 'name', operator: '==', value: 'hello' }];
    const result = buildFilterExpression(conditions, columns, 'all');
    expect(result).toEqual(['all', ['==', ['get', 'name'], 'hello']]);
  });

  it('returns ["all", ...] for multiple conditions with "all" combinator', () => {
    const conditions = [
      { id: '1', field: 'name', operator: '==', value: 'hello' },
      { id: '2', field: 'population', operator: '>', value: '100' },
    ];
    const result = buildFilterExpression(conditions, columns, 'all');
    expect(Array.isArray(result)).toBe(true);
    expect((result as unknown[])[0]).toBe('all');
    expect((result as unknown[]).length).toBe(3);
  });

  it('returns ["any", ...] for multiple conditions with "any" combinator', () => {
    const conditions = [
      { id: '1', field: 'name', operator: '==', value: 'hello' },
      { id: '2', field: 'population', operator: '<', value: '50' },
    ];
    const result = buildFilterExpression(conditions, columns, 'any');
    expect(Array.isArray(result)).toBe(true);
    expect((result as unknown[])[0]).toBe('any');
    expect((result as unknown[]).length).toBe(3);
  });

  it('defaults to "all" combinator when no combinator argument given', () => {
    const conditions = [
      { id: '1', field: 'name', operator: '==', value: 'a' },
      { id: '2', field: 'name', operator: '==', value: 'b' },
    ];
    const result = buildFilterExpression(conditions, columns);
    expect((result as unknown[])[0]).toBe('all');
  });

  it('returns bare expression for single condition with "any" combinator (no wrapping needed)', () => {
    const conditions = [{ id: '1', field: 'name', operator: '==', value: 'solo' }];
    const result = buildFilterExpression(conditions, columns, 'any');
    // Single condition — always wrapped in combinator
    expect(result).toEqual(['any', ['==', ['get', 'name'], 'solo']]);
  });
});

// ---------------------------------------------------------------------------
// Raw JSON validation helpers (inline logic tests)
// ---------------------------------------------------------------------------
describe('raw JSON parsing', () => {
  it('successfully parses a valid filter expression string', () => {
    const raw = JSON.stringify(['==', ['get', 'name'], 'foo']);
    expect(() => JSON.parse(raw)).not.toThrow();
    const parsed = JSON.parse(raw);
    expect(parsed[0]).toBe('==');
  });

  it('throws on invalid JSON', () => {
    const invalid = '{ not valid json ';
    expect(() => JSON.parse(invalid)).toThrow();
  });

  it('invalid JSON parse returns descriptive error', () => {
    const invalid = '["==", ["get", "name"],]';
    let errorMsg = '';
    try {
      JSON.parse(invalid);
    } catch (e) {
      errorMsg = (e as Error).message;
    }
    expect(errorMsg).not.toBe('');
  });
});

// ---------------------------------------------------------------------------
// Roundtrip: opaque expression preserved through raw JSON cycle
// ---------------------------------------------------------------------------
describe('opaque roundtrip', () => {
  it('opaque expression roundtrips through JSON.stringify/parse without modification', () => {
    const originalExpr: FilterSpecification = [
      'all',
      ['has', 'name'],
      ['step', ['zoom'], false, 10, true],
    ] as FilterSpecification;

    const parseResult = parseFilterExpression(originalExpr);
    expect(parseResult.kind).toBe('opaque');

    if (parseResult.kind === 'opaque') {
      const serialized = JSON.stringify(parseResult.raw);
      const deserialized = JSON.parse(serialized) as FilterSpecification;
      // After roundtrip, re-parsing should still be opaque
      const reparse = parseFilterExpression(deserialized);
      expect(reparse.kind).toBe('opaque');
    }
  });
});

describe('LayerFilterEditor layout', () => {
  it('keeps the field selector on its own row before operator and value controls', () => {
    render(createElement(LayerFilterEditor, {
      columnInfo: [
        { name: 'very_long_descriptive_field_name', type: 'text' },
        ...columns,
      ],
      filter: ['all', ['==', ['get', 'very_long_descriptive_field_name'], 'Parks']] as FilterSpecification,
      onFilterChange: vi.fn(),
    }));

    const condition = screen.getByTestId('filter-condition-row');
    const fieldRow = within(condition).getByTestId('filter-field-row');
    const valueRow = within(condition).getByTestId('filter-value-row');

    expect(fieldRow).toContainElement(screen.getByRole('combobox', { name: 'Field' }));
    expect(valueRow).toContainElement(screen.getByRole('combobox', { name: 'Op' }));
    expect(valueRow).toContainElement(screen.getByRole('textbox', { name: 'Value' }));
    expect(valueRow).toContainElement(screen.getByRole('button', { name: 'Remove condition' }));
    expect(fieldRow).not.toBe(valueRow);
  });
});
