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
import { act } from '@testing-library/react';
import { render, screen } from '@/test/test-utils';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';
import { useAuthStore } from '@/stores/auth-store';

const updateFeature = vi.hoisted(() => vi.fn());
vi.mock('@/api/features', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/features')>()),
  updateFeature,
}));

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
    updateFeature.mockReset();
    updateFeature.mockResolvedValue({});
    useAuthStore.setState({ sessionEpoch: 0, user: null });
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

  // fix(#458 E-03/E-39) says a rejected value stays in the box to be
  // corrected. Setting editError re-rendered AttributeTable, which rebuilt
  // `columns`, which remounted the editor — so the rejected text was replaced
  // by the old value and only the message survived.
  it('keeps a rejected value in the editor and marks the field invalid', async () => {
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1628" canEdit />);

    await user.click(screen.getByRole('button', { name: '100' }));

    const editor = screen.getByRole('textbox', { name: 'Edit population for feature 1' });
    await user.clear(editor);
    await user.type(editor, 'not-a-number');
    await user.keyboard('{Enter}');

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Not a valid integer value',
    );
    const afterReject = screen.getByRole('textbox', {
      name: 'Edit population for feature 1',
    });
    expect(afterReject).toBe(editor);
    expect(afterReject).toHaveValue('not-a-number');
    expect(afterReject).toHaveAttribute('aria-invalid', 'true');
  });

  it('associates a backend rejection with the cell editor', async () => {
    updateFeature.mockRejectedValueOnce(new Error('Backend rejected value'));
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1628" canEdit />);

    await user.click(screen.getByRole('button', { name: '100' }));
    const editor = screen.getByRole('textbox', { name: 'Edit population for feature 1' });
    await user.clear(editor);
    await user.type(editor, '250');
    await user.keyboard('{Enter}');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Backend rejected value');
    expect(screen.getByRole('textbox', { name: 'Edit population for feature 1' }))
      .toHaveAttribute('aria-describedby', alert.id);
  });

  it('does not let a dataset A completion close an editor after A is reopened', async () => {
    let resolveUpdate!: (value: unknown) => void;
    updateFeature.mockReturnValueOnce(new Promise((resolve) => {
      resolveUpdate = resolve;
    }));
    const user = userEvent.setup();
    const { rerender } = render(<AttributeTable datasetId="dataset-a" canEdit />);

    await user.click(screen.getByRole('button', { name: '100' }));
    const firstEditor = screen.getByRole('textbox', { name: 'Edit population for feature 1' });
    await user.clear(firstEditor);
    await user.type(firstEditor, '250');
    await user.keyboard('{Enter}');

    rerender(<AttributeTable datasetId="dataset-b" canEdit />);
    rerender(<AttributeTable datasetId="dataset-a" canEdit />);
    await user.click(await screen.findByRole('button', { name: '100' }));
    await act(async () => {
      resolveUpdate({});
    });

    expect(await screen.findByRole('textbox', {
      name: 'Edit population for feature 1',
    })).toBeInTheDocument();
  });

  it('does not let an older cell save close a newer editor in the same dataset', async () => {
    let resolveUpdate!: (value: unknown) => void;
    updateFeature.mockReturnValueOnce(new Promise((resolve) => {
      resolveUpdate = resolve;
    }));
    vi.mocked(useDatasetRows).mockReturnValue({
      data: {
        ...ROWS_RESPONSE,
        rows: [
          { gid: 1, population: 100 },
          { gid: 2, population: 200 },
        ],
        approximate_total: 2,
      },
      isLoading: false,
      isFetching: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetRows>);
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1628" canEdit />);

    await user.click(screen.getByRole('button', { name: '100' }));
    const firstEditor = screen.getByRole('textbox', { name: 'Edit population for feature 1' });
    await user.clear(firstEditor);
    await user.type(firstEditor, '250');
    await user.keyboard('{Enter}');
    await user.click(screen.getByRole('button', { name: '200' }));

    await act(async () => {
      resolveUpdate({});
    });

    expect(await screen.findByRole('textbox', {
      name: 'Edit population for feature 2',
    })).toBeInTheDocument();
  });

  it('does not let a prior auth session close the current cell editor', async () => {
    let resolveUpdate!: (value: unknown) => void;
    updateFeature.mockReturnValueOnce(new Promise((resolve) => {
      resolveUpdate = resolve;
    }));
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1628" canEdit />);

    await user.click(screen.getByRole('button', { name: '100' }));
    const editor = screen.getByRole('textbox', { name: 'Edit population for feature 1' });
    await user.clear(editor);
    await user.type(editor, '250');
    await user.keyboard('{Enter}');
    useAuthStore.setState({ sessionEpoch: 1 });
    await act(async () => {
      resolveUpdate({});
    });

    expect(await screen.findByRole('textbox', {
      name: 'Edit population for feature 1',
    })).toBeInTheDocument();
  });
});
