import { render, screen, within } from '@/test/test-utils';
import { SearchResultList } from '@/components/search/SearchResultList';
import type { OGCRecordResponse } from '@/types/api';

function makeFeature(id: string, title: string, recordType = 'vector_dataset'): OGCRecordResponse {
  return {
    type: 'Feature',
    id,
    time: {},
    geometry: null,
    properties: { title, record_type: recordType, geometry_type: 'Point', feature_count: 3 },
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
    expect(screen.queryByTestId('search-result-collections')).not.toBeInTheDocument();
  });

  it('marks where the collection matches begin after the datasets, hidden from assistive tech', () => {
    render(
      <SearchResultList
        features={[...features, makeFeature('coll-1', 'Parks', 'collection'), makeFeature('coll-2', 'Rivers', 'collection')]}
        density="compact"
      />,
    );

    const divider = screen.getByTestId('search-result-collections');
    expect(divider).toHaveTextContent('Collections');
    expect(divider).toHaveAttribute('aria-hidden', 'true');
    const items = within(screen.getByRole('list')).getAllByRole('listitem');
    expect(items).toHaveLength(4);
    const cards = screen.getAllByTestId('search-result-card');
    expect(divider.compareDocumentPosition(cards[1]) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    expect(divider.compareDocumentPosition(cards[2]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByTestId('search-result-collections')).toHaveLength(1);
  });

  it('adds no collection marker when the page holds only collections or none', () => {
    const { rerender } = render(
      <SearchResultList features={[makeFeature('coll-1', 'Parks', 'collection')]} density="compact" />,
    );
    expect(screen.queryByTestId('search-result-collections')).not.toBeInTheDocument();

    rerender(<SearchResultList features={features} density="comfortable" />);
    expect(screen.queryByTestId('search-result-collections')).not.toBeInTheDocument();
  });
});
