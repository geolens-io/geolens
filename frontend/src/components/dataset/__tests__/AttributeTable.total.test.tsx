import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@/test/test-utils';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';
import type { DatasetRowsResponse } from '@/types/api';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetRows: vi.fn(),
}));
vi.mock('@/hooks/use-features', () => ({
  useUpdateFeature: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteFeatures: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

function renderWithTotal(total: Pick<DatasetRowsResponse, 'approximate_total' | 'total_kind'>) {
  vi.mocked(useDatasetRows).mockReturnValue({
    data: {
      columns: [{ name: 'title', type: 'text' }],
      rows: [{ gid: 1, title: 'Main St' }, { gid: 2, title: 'Mill Rd' }],
      next_cursor: 2,
      sortable_columns: [],
      ...total,
    },
    isLoading: false,
    isFetching: false,
    isError: false,
  } as unknown as ReturnType<typeof useDatasetRows>);
  render(<AttributeTable datasetId="test-ds" />);
}

describe('AttributeTable row total', () => {
  it('shows a counted total without the estimate mark', () => {
    renderWithTotal({ approximate_total: 37, total_kind: 'exact' });
    expect(screen.getByText('Showing 1-2 of 37 rows')).toBeInTheDocument();
  });

  it('shows a capped count as a floor', () => {
    renderWithTotal({ approximate_total: 10000, total_kind: 'at_least' });
    expect(screen.getByText('Showing 1-2 of 10,000+ rows')).toBeInTheDocument();
  });

  it('marks the table statistics as an estimate', () => {
    renderWithTotal({ approximate_total: 4200, total_kind: 'estimate' });
    expect(screen.getByText('Showing 1-2 of ~4,200 rows')).toBeInTheDocument();
  });
});
