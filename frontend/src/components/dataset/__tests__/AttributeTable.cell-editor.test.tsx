/**
 * fix(#1628): an in-progress inline cell edit must survive an unrelated
 * re-render of AttributeTable.
 *
 * TanStack's `<table.FlexRender cell={cell} />` renders `columnDef.cell` as the
 * React component TYPE, so rebuilding the `columns` array gives every cell a
 * new element type and React remounts the cell subtree instead of re-rendering
 * it — wiping InlineCellEditor's `value` state back to the stored cell value.
 * `columns` used to list `handleCellSave`, whose dep list carries the object
 * react-query's `useMutation` returns, and that object is rebuilt on every
 * render. So any re-render at all discarded what the user had typed, and the
 * following Enter took commit()'s `value === initialValue` branch: no PATCH,
 * no validation message, editor silently closed. That is the intermittent
 * failure e2e/feature-editing.spec.ts kept hitting.
 *
 * `useUpdateFeature` is deliberately NOT mocked here — the real react-query
 * `useMutation` identity churn is the trigger under test, and a hand-stubbed
 * hook returning one frozen object would make this pass against the bug.
 *
 * `useVirtualizer` IS mocked: jsdom computes no layout, so the real
 * virtualizer's measured viewport is 0px tall and it renders no body rows at
 * all (see the note at the top of AttributeTable.test.tsx). The stub windows
 * nothing and hands back every row, which is what this suite needs to reach a
 * body cell.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetRows: vi.fn(),
}));
// Pass the debounced value straight through, as AttributeTable.test.tsx does.
vi.mock('@/hooks/use-debounce', () => ({
  useDebouncedValue: (value: unknown) => value,
}));
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count, estimateSize }: { count: number; estimateSize: () => number }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        key: index,
        start: index * estimateSize(),
        size: estimateSize(),
      })),
    getTotalSize: () => count * estimateSize(),
    measure: () => {},
  }),
}));

const ROWS_RESPONSE = {
  columns: [{ name: 'population', type: 'integer' }],
  rows: [{ gid: 1, population: 100 }],
  next_cursor: null,
  approximate_total: 1,
};

describe('fix(#1628): inline cell editor survives an unrelated re-render', () => {
  beforeEach(() => {
    vi.mocked(useDatasetRows).mockReturnValue({
      data: ROWS_RESPONSE,
      isLoading: false,
      isFetching: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetRows>);
  });

  it('keeps the typed value, and the same input element, across a re-render', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<AttributeTable datasetId="ds-1628" canEdit />);

    await user.click(screen.getByRole('button', { name: '100' }));

    const editor = screen.getByRole('textbox', { name: 'Edit population for feature 1' });
    await user.clear(editor);
    await user.type(editor, '250');
    expect(editor).toHaveValue('250');

    // Any render of AttributeTable at all — a sibling query settling, the map
    // above finishing its load, a parent state change.
    rerender(<AttributeTable datasetId="ds-1628" canEdit />);

    const afterRerender = screen.getByRole('textbox', {
      name: 'Edit population for feature 1',
    });
    // Identity: a remount is the mechanism, so pin the element itself, not
    // just the symptom.
    expect(afterRerender).toBe(editor);
    expect(afterRerender).toHaveValue('250');
  });
});
