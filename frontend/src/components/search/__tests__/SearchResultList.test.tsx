import { render, screen, within } from '@/test/test-utils';
import { SearchResultList } from '@/components/search/SearchResultList';
import type { OGCRecordResponse } from '@/types/api';

function makeFeature(id: string, title: string): OGCRecordResponse {
  return {
    type: 'Feature',
    id,
    time: {},
    geometry: null,
    properties: { title, record_type: 'vector_dataset', geometry_type: 'Point', feature_count: 3 },
    links: [],
  } as unknown as OGCRecordResponse;
}

const features = [makeFeature('dataset-1', 'Roads'), makeFeature('dataset-2', 'Parcels')];

describe('SearchResultList', () => {
  it('lists comfortable cards without column heads', () => {
    render(<SearchResultList features={features} density="comfortable" />);

    const rows = within(screen.getByRole('list')).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(screen.getAllByTestId('search-result-card').map((c) => c.getAttribute('data-density'))).toEqual([
      'comfortable',
      'comfortable',
    ]);
    expect(screen.queryByTestId('search-result-columns')).not.toBeInTheDocument();
  });

  it('lists compact rows under column heads that assistive tech skips', () => {
    render(<SearchResultList features={features} density="compact" />);

    const heads = screen.getByTestId('search-result-columns');
    expect(heads).toHaveAttribute('aria-hidden', 'true');
    expect(heads).toHaveTextContent('Name');
    expect(heads).toHaveTextContent('Details');
    expect(heads).toHaveTextContent('Updated');
    const list = screen.getByRole('list');
    expect(list).not.toContainElement(heads);
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getAllByTestId('search-result-card').map((c) => c.getAttribute('data-density'))).toEqual([
      'compact',
      'compact',
    ]);
  });
});
