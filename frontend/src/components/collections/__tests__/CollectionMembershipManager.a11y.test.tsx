/**
 * GLUX-002 (Phase 1248): accessible-name regression gate for the collection
 * membership search input.
 *
 * Asserts that the search input inside CollectionMembershipManager is
 * queryable by its accessible name. A placeholder-only control fails WCAG
 * 4.1.2 and would not be caught by getByLabelText — so this test is the
 * automated enforcement mechanism.
 */
import { render, screen } from '@/test/test-utils';
import { vi } from 'vitest';
import { searchDatasets } from '@/api/search';
import { CollectionMembershipManager } from '@/components/collections/CollectionMembershipManager';
import {
  useAddDatasetsToCollection,
  useCollectionDatasets,
} from '@/components/collections/hooks/use-collections';

vi.mock('@/components/collections/hooks/use-collections', () => ({
  useAddDatasetsToCollection: vi.fn(),
  useCollectionDatasets: vi.fn(),
}));

vi.mock('@/api/search', () => ({
  searchDatasets: vi.fn(),
}));

describe('GLUX-002: CollectionMembershipManager search input accessible name', () => {
  beforeEach(() => {
    vi.mocked(useCollectionDatasets).mockReturnValue({
      data: { datasets: [], total: 0 },
      isLoading: false,
    } as unknown as ReturnType<typeof useCollectionDatasets>);

    vi.mocked(useAddDatasetsToCollection).mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useAddDatasetsToCollection>);
  });

  it('collection search input is queryable by its accessible name', () => {
    render(<CollectionMembershipManager collectionId="col-1" />);
    // The search input exposes an accessible name via FieldLabel (sr-only
    // label bound via htmlFor="collection-membership-search"). Removing the
    // FieldLabel + id pairing will make getByLabelText fail here.
    const searchInput = screen.getByLabelText(/search datasets/i);
    expect(searchInput).toBeInTheDocument();
    expect(searchInput.tagName.toLowerCase()).toBe('input');
  });

  it('names each checkbox after its dataset', async () => {
    vi.mocked(searchDatasets).mockResolvedValue({
      features: [
        { id: 'a', properties: { title: 'Alpha Parcels' } },
        { id: 'b', properties: { title: 'Beta Roads' } },
      ],
      numberMatched: 2,
    } as unknown as Awaited<ReturnType<typeof searchDatasets>>);
    render(<CollectionMembershipManager collectionId="col-1" />);

    expect(await screen.findByRole('checkbox', { name: 'Select Alpha Parcels' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Select Beta Roads' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Datasets available to add' })).toBeInTheDocument();
  });
});
