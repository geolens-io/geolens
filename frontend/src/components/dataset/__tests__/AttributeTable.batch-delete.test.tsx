/**
 * Rows of an editable table can be selected and deleted in one request.
 *
 * `useVirtualizer` is stubbed because jsdom computes no layout (see
 * AttributeTable.cell-editor.test.tsx).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@/test/test-utils';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { ApiError } from '@/api/client';

const getDatasetRows = vi.hoisted(() => vi.fn());
const deleteFeatures = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('@/api/datasets', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/datasets')>()),
  getDatasetRows,
}));
vi.mock('@/api/features', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/features')>()),
  deleteFeatures,
}));
vi.mock('sonner', () => ({ toast }));
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

const columns = [
  { name: 'gid', type: 'integer' },
  { name: 'name', type: 'text' },
];

function page(after: number, gids: number[]) {
  return {
    columns,
    rows: gids.map((gid) => ({ gid, name: `row ${gid}` })),
    next_cursor: after + 3,
    approximate_total: 9,
    sortable_columns: ['gid'],
    table_id: '4242',
  };
}

describe('AttributeTable batch delete', () => {
  beforeEach(() => {
    getDatasetRows.mockReset();
    deleteFeatures.mockReset();
    toast.success.mockReset();
    toast.error.mockReset();
    getDatasetRows.mockImplementation(async (_id: string, params: { after?: number }) => {
      const after = params.after ?? 0;
      return page(after, [after + 1, after + 2, after + 3]);
    });
  });

  it('offers no row selection when the table is not editable', async () => {
    render(<AttributeTable datasetId="ds-1" />);
    await screen.findByText('row 1');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('selects the page from the header checkbox and counts the selection', async () => {
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1" canEdit />);
    const selectPage = await screen.findByRole('checkbox', { name: 'Select all rows on this page' });

    await user.click(selectPage);
    for (const gid of [1, 2, 3]) {
      expect(screen.getByRole('checkbox', { name: `Select row ${gid}` })).toBeChecked();
    }
    expect(screen.getByRole('button', { name: 'Delete 3 rows' })).toBeInTheDocument();

    // Space on a focused row checkbox clears it, leaving the header mixed.
    screen.getByRole('checkbox', { name: 'Select row 2' }).focus();
    await user.keyboard(' ');
    expect(selectPage).toHaveAttribute('aria-checked', 'mixed');
    expect(screen.getByRole('button', { name: 'Delete 2 rows' })).toBeInTheDocument();
  });

  it('confirms the count, deletes with the table id, then clears and refetches', async () => {
    deleteFeatures.mockResolvedValue({ deleted: 2, tile_cache_version: 7 });
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1" canEdit />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select row 1' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select row 3' }));

    await user.click(screen.getByRole('button', { name: 'Delete 2 rows' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Delete 2 selected rows? This cannot be undone.');
    expect(deleteFeatures).not.toHaveBeenCalled();
    const fetchesBefore = getDatasetRows.mock.calls.length;

    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(deleteFeatures).toHaveBeenCalledWith('ds-1', [1, 3], '4242'));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('2 rows deleted'));
    await waitFor(() => expect(getDatasetRows.mock.calls.length).toBeGreaterThan(fetchesBefore));
    expect(screen.queryByRole('button', { name: /^Delete \d+ rows?$/ })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Select row 1' })).not.toBeChecked();
  });

  it('shows the replaced-table message when the table changed under the page', async () => {
    deleteFeatures.mockRejectedValue(
      new ApiError('conflict', 409, { code: 'dataset_replaced', tile_cache_version: 9 }),
    );
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1" canEdit />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select row 2' }));
    await user.click(screen.getByRole('button', { name: 'Delete 1 row' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
      "This dataset's data was replaced after you started editing, so your change was not saved.",
    ));
  });

  it('drops the selection when the page comes back from a replacement table', async () => {
    deleteFeatures.mockRejectedValue(
      new ApiError('conflict', 409, { code: 'dataset_replaced', tile_cache_version: 9 }),
    );
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1" canEdit />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select row 2' }));
    // The replacement reuses gids 1-3, so a kept selection would target its rows.
    getDatasetRows.mockImplementation(async () => ({ ...page(0, [1, 2, 3]), table_id: '5555' }));
    await user.click(screen.getByRole('button', { name: 'Delete 1 row' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }));

    await waitFor(() =>
      expect(screen.getByRole('checkbox', { name: 'Select row 2' })).not.toBeChecked(),
    );
    expect(screen.queryByRole('button', { name: 'Delete 1 row' })).not.toBeInTheDocument();
  });

  it('reports rows that no longer exist and refetches the page', async () => {
    deleteFeatures.mockRejectedValue(
      new ApiError('not found', 404, { code: 'feature_not_found', gids: [2], message: 'x' }),
    );
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1" canEdit />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select row 2' }));
    const fetchesBefore = getDatasetRows.mock.calls.length;
    await user.click(screen.getByRole('button', { name: 'Delete 1 row' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
      'Some selected rows no longer exist, so nothing was deleted.',
    ));
    await waitFor(() => expect(getDatasetRows.mock.calls.length).toBeGreaterThan(fetchesBefore));
  });

  it('offers no selection for a gid past 2^53, which arrives rounded', async () => {
    const unsafe = 2 ** 53 + 2;
    getDatasetRows.mockImplementation(async () => page(0, [1, 2, unsafe]));
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1" canEdit />);

    await user.click(await screen.findByRole('checkbox', { name: 'Select all rows on this page' }));

    expect(screen.getByRole('checkbox', { name: `Select row ${unsafe}` })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Delete 2 rows' })).toBeInTheDocument();
  });

  it('returns focus to the table after a confirmed delete', async () => {
    deleteFeatures.mockResolvedValue({ deleted: 1, tile_cache_version: 7 });
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1" canEdit />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select row 1' }));
    await user.click(screen.getByRole('button', { name: 'Delete 1 row' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByRole('region', { name: 'Feature attributes' })).toHaveFocus(),
    );
  });

  it('closes the confirmation when the selected rows are gone', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <AttributeTable datasetId="ds-1" canEdit />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole('checkbox', { name: 'Select row 2' }));
    await user.click(screen.getByRole('button', { name: 'Delete 1 row' }));
    await screen.findByRole('alertdialog');

    // Someone else deleted row 2.
    getDatasetRows.mockImplementation(async () => page(0, [1, 3, 4]));
    await act(() => queryClient.invalidateQueries());

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(deleteFeatures).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole('region', { name: 'Feature attributes' })).toHaveFocus(),
    );
  });

  it('drops the selection when the page changes', async () => {
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1" canEdit />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select row 1' }));
    expect(screen.getByRole('button', { name: 'Delete 1 row' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /next/i }));
    await screen.findByText('row 4');
    await user.click(screen.getByRole('button', { name: /previous/i }));
    await screen.findByText('row 1');
    expect(screen.getByRole('checkbox', { name: 'Select row 1' })).not.toBeChecked();
    expect(screen.queryByRole('button', { name: 'Delete 1 row' })).not.toBeInTheDocument();
  });
});
