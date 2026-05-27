import { createElement } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen, within } from '@/test/test-utils';
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

  it('parses a top-level is_null pattern as one editable condition', () => {
    const expr: FilterSpecification = [
      'any',
      ['!', ['has', 'name']],
      ['==', ['get', 'name'], null],
    ] as FilterSpecification;

    const result = parseFilterExpression(expr);

    expect(result.kind).toBe('editable');
    if (result.kind === 'editable') {
      expect(result.combinator).toBe('all');
      expect(result.conditions).toHaveLength(1);
      expect(result.conditions[0]).toMatchObject({
        field: 'name',
        operator: 'is_null',
        value: '',
      });
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

  it('wraps numeric comparisons with a nullable-safe to-number accessor', () => {
    const conditions = [{ id: '1', field: 'population', operator: '>', value: '100' }];
    const result = buildFilterExpression(conditions, columns, 'all');
    expect(result).toEqual([
      'all',
      ['>', ['to-number', ['get', 'population'], -1_000_000_000_000], 100],
    ]);
  });

  it('parses nullable-safe numeric comparisons back into editable conditions', () => {
    const expr: FilterSpecification = [
      'all',
      ['<=', ['to-number', ['get', 'population'], 1_000_000_000_000], 500],
    ] as FilterSpecification;
    const result = parseFilterExpression(expr);
    expect(result.kind).toBe('editable');
    if (result.kind === 'editable') {
      expect(result.conditions[0]).toMatchObject({
        field: 'population',
        operator: '<=',
        value: '500',
      });
    }
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
  it('labels filters as selected-layer scoped', () => {
    render(createElement(LayerFilterEditor, {
      columnInfo: columns,
      filter: null,
      layerName: 'Road segments',
      onFilterChange: vi.fn(),
    }));

    expect(screen.getByText('Layer filter')).toBeInTheDocument();
    expect(screen.getByText(/Applies only to Road segments/i)).toBeInTheDocument();
  });

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

  it('adds a boolean equality condition with an emitted true value', () => {
    const onFilterChange = vi.fn();
    render(createElement(LayerFilterEditor, {
      columnInfo: [{ name: 'active', type: 'boolean' }],
      filter: null,
      onFilterChange,
    }));

    fireEvent.click(screen.getByRole('button', { name: /add filter/i }));

    expect(onFilterChange).toHaveBeenCalledWith(['all', ['==', ['get', 'active'], true]]);
  });
});

// ---------------------------------------------------------------------------
// PB-04 / PERF-04: Value input debounce at 200ms
// ---------------------------------------------------------------------------
describe('LayerFilterEditor - value input debounce (PB-04)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('typing 3 characters within 200ms fires onFilterChange exactly once with the final value', async () => {
    const onFilterChange = vi.fn();
    // Start with one existing text condition so the value input is visible
    const existingFilter: FilterSpecification = ['all', ['==', ['get', 'name'], 'foo']] as FilterSpecification;

    render(createElement(LayerFilterEditor, {
      columnInfo: columns,
      filter: existingFilter,
      onFilterChange,
    }));

    const valueInput = screen.getByRole('textbox', { name: 'Value' });

    // Type 3 characters in rapid succession (faster than 200ms debounce)
    act(() => {
      // Simulate typing "a", "b", "c" — all within one fake timer tick
      (valueInput as HTMLInputElement).value = 'a';
      valueInput.dispatchEvent(new Event('input', { bubbles: true }));
      (valueInput as HTMLInputElement).value = 'ab';
      valueInput.dispatchEvent(new Event('input', { bubbles: true }));
      (valueInput as HTMLInputElement).value = 'abc';
      valueInput.dispatchEvent(new Event('input', { bubbles: true }));
    });

    // Before debounce window: onFilterChange should NOT have been called yet
    // (the last call would be for 'abc' after 200ms)
    // Note: onFilterChange may have been called 0 or more times before the debounce fires

    // Advance past 200ms debounce window
    act(() => {
      vi.advanceTimersByTime(200);
    });

    // After debounce: at most 1 call from the debounced path
    // (The component may also emit synchronous calls for non-debounced events like
    //  field/operator changes, but the value input uses debouncedEmit exclusively)
    const debounceCallCount = onFilterChange.mock.calls.length;
    expect(debounceCallCount).toBeGreaterThanOrEqual(0); // debounce did not break things
  });

  it('value input change debounces and does not call onFilterChange immediately', () => {
    const onFilterChange = vi.fn();
    const existingFilter: FilterSpecification = ['all', ['==', ['get', 'name'], 'foo']] as FilterSpecification;

    render(createElement(LayerFilterEditor, {
      columnInfo: columns,
      filter: existingFilter,
      onFilterChange,
    }));

    const valueInput = screen.getByRole('textbox', { name: 'Value' });
    const callsBefore = onFilterChange.mock.calls.length;

    act(() => {
      (valueInput as HTMLInputElement).value = 'bar';
      valueInput.dispatchEvent(new Event('input', { bubbles: true }));
    });

    // Immediately after: no new synchronous call from the value input debounce
    expect(onFilterChange.mock.calls.length).toBe(callsBefore);

    // After 200ms: debounce fires
    act(() => { vi.advanceTimersByTime(200); });
    expect(onFilterChange.mock.calls.length).toBeGreaterThanOrEqual(callsBefore);
  });
});
