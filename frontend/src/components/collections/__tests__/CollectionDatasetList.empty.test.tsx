import { render, screen } from '@/test/test-utils';
import { CollectionDatasetList } from '@/components/collections/CollectionDatasetList';
import { useCollectionDatasets } from '@/components/collections/hooks/use-collections';

vi.mock('@/components/collections/hooks/use-collections', () => ({
  useCollectionDatasets: vi.fn(),
}));

it('does not send people to another page to add datasets to an empty collection', () => {
  vi.mocked(useCollectionDatasets).mockReturnValue({
    data: { datasets: [], total: 0 },
    isLoading: false,
    error: null,
  } as unknown as ReturnType<typeof useCollectionDatasets>);
  render(<CollectionDatasetList collectionId="col-1" />);
  expect(screen.getByText('No datasets in this collection')).toBeInTheDocument();
  expect(screen.queryByText(/management page/i)).not.toBeInTheDocument();
});
