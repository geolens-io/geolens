/**
 * A header click sorts the whole dataset on the server, not just the loaded
 * page, and starts paging over from the first page of the new order.
 *
 * `useVirtualizer` is stubbed because jsdom computes no layout (see
 * AttributeTable.cell-editor.test.tsx).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@/test/test-utils';
import { AttributeTable } from '@/components/dataset/AttributeTable';

const getDatasetRows = vi.hoisted(() => vi.fn());
vi.mock('@/api/datasets', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/datasets')>()),
  getDatasetRows,
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

const columns = [
  { name: 'gid', type: 'integer' },
  { name: 'pop', type: 'integer' },
  { name: 'meta', type: 'json' },
];

describe('AttributeTable server-side sort', () => {
  beforeEach(() => {
    getDatasetRows.mockReset();
    getDatasetRows.mockImplementation(async (_id: string, params: { after?: number }) => ({
      columns,
      rows: [
        { gid: (params.after ?? 0) + 1, pop: 10, meta: null },
        { gid: (params.after ?? 0) + 2, pop: 20, meta: null },
      ],
      next_cursor: (params.after ?? 0) + 2,
      approximate_total: 6,
      sortable_columns: ['gid', 'pop'],
    }));
  });

  it('requests the sorted first page when a header is clicked from a later page', async () => {
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds-1" />);

    await user.click(await screen.findByRole('button', { name: /next/i }));
    await waitFor(() =>
      expect(getDatasetRows).toHaveBeenLastCalledWith('ds-1', expect.objectContaining({ after: 2 })),
    );

    const popHeader = screen.getByRole('columnheader', { name: /pop/ });
    expect(popHeader).toHaveAttribute('aria-sort', 'none');
    await user.click(screen.getByRole('button', { name: /pop/ }));

    await waitFor(() =>
      expect(getDatasetRows).toHaveBeenLastCalledWith(
        'ds-1',
        expect.objectContaining({ after: 0, sort: { column: 'pop', desc: false } }),
      ),
    );
    expect(popHeader).toHaveAttribute('aria-sort', 'ascending');
    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled();
    // No request pairs the new order with the old page's cursor.
    expect(getDatasetRows).not.toHaveBeenCalledWith(
      'ds-1',
      expect.objectContaining({ after: 2, sort: expect.anything() }),
    );

    await user.click(screen.getByRole('button', { name: /pop/ }));
    await waitFor(() =>
      expect(getDatasetRows).toHaveBeenLastCalledWith(
        'ds-1',
        expect.objectContaining({ after: 0, sort: { column: 'pop', desc: true } }),
      ),
    );
    expect(popHeader).toHaveAttribute('aria-sort', 'descending');
  });

  it('offers no sort on a column the server does not list as sortable', async () => {
    render(<AttributeTable datasetId="ds-1" />);
    const metaHeader = await screen.findByRole('columnheader', { name: /meta/ });
    expect(metaHeader).not.toHaveAttribute('aria-sort');
    expect(screen.queryByRole('button', { name: /meta/ })).toBeNull();
  });

  it('offers no sort at all when the server does not list sortable columns', async () => {
    getDatasetRows.mockResolvedValue({
      columns,
      rows: [{ gid: 1, pop: 10, meta: null }],
      next_cursor: null,
      approximate_total: 1,
    });
    render(<AttributeTable datasetId="ds-1" />);
    const popHeader = await screen.findByRole('columnheader', { name: /pop/ });
    expect(popHeader).not.toHaveAttribute('aria-sort');
    expect(screen.queryByRole('button', { name: /pop/ })).toBeNull();
  });
});
