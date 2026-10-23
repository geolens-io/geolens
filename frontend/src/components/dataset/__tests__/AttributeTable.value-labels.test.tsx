/**
 * A column with coded-value labels shows the label and keeps the code
 * reachable by focus. `useVirtualizer` is stubbed because jsdom computes no
 * layout and the real one renders no body rows (see AttributeTable.test.tsx).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetRows: vi.fn(),
}));
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

const LABELS = new Map([['status', { '1': 'Active' }]]);

describe('AttributeTable coded values', () => {
  beforeEach(() => {
    useAuthStore.setState({ sessionEpoch: 0, user: null });
    vi.mocked(useDatasetRows).mockReturnValue({
      data: {
        columns: [
          { name: 'status', type: 'integer' },
          { name: 'size', type: 'integer' },
        ],
        rows: [
          { gid: 1, status: 1, size: 1 },
          { gid: 2, status: 7, size: 2 },
        ],
        next_cursor: null,
        approximate_total: 2,
      },
      isLoading: false,
      isFetching: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetRows>);
  });

  it('shows the label in a read-only cell and leaves unlabelled values alone', () => {
    render(<AttributeTable datasetId="ds" valueLabels={LABELS} />);

    expect(screen.getByRole('button', { name: 'Active' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '7' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '2' })).toBeInTheDocument();
  });

  it('shows the code when the read-only label takes keyboard focus', async () => {
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds" valueLabels={LABELS} />);

    const label = screen.getByRole('button', { name: 'Active' });
    for (let i = 0; i < 20 && document.activeElement !== label; i += 1) await user.tab();

    expect(label).toHaveFocus();
    expect(await screen.findByRole('tooltip')).toHaveTextContent('1');
  });

  it('shows the label and the code together in an editable cell, and edits the code', async () => {
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds" canEdit valueLabels={LABELS} />);

    const cell = screen.getByText('(1)').closest('button')!;
    expect(cell).toHaveTextContent('Active (1)');
    await user.click(cell);

    expect(screen.getByRole('textbox', { name: 'Edit status for feature 1' })).toHaveValue('1');
  });
});
