import { act } from 'react';
import { render, screen } from '@/test/test-utils';
import { SearchPage } from '@/pages/SearchPage';
import { useSearchStore } from '@/stores/search-store';

vi.mock('@/components/search/hooks/use-search', () => ({
  useSearchResults: vi.fn(() => ({ data: { features: [], numberMatched: 0 }, isLoading: false })),
  useMapSearchResults: vi.fn(() => ({ data: undefined })),
  useAllTypesTotal: (total: number | undefined) => total,
  useFacets: () => ({ data: undefined, isLoading: false }),
  useCatalogSummary: () => ({ data: undefined, isLoading: false }),
}));
vi.mock('@/components/search/hooks/use-url-search-sync', () => ({ useUrlSearchSync: vi.fn() }));
vi.mock('@/hooks/use-document-title', () => ({ useDocumentTitle: vi.fn() }));
vi.mock('@/components/search/SearchBar', () => ({ SearchBar: () => null }));
vi.mock('@/components/search/SavedSearches', () => ({ SavedSearches: () => null }));
vi.mock('@/components/search/SpatialFilterPanel', () => ({
  SpatialFilterPanel: () => <div role="dialog" aria-label="Search area" />,
}));

it('mounts the search-area sheet once and leaves it exposed to assistive tech', async () => {
  render(<SearchPage />);
  act(() => {
    useSearchStore.getState().setSpatialPanelOpen(true);
  });
  const dialogs = await screen.findAllByRole('dialog');
  expect(dialogs).toHaveLength(1);
  expect(dialogs[0]).not.toHaveAttribute('aria-hidden', 'true');
});
