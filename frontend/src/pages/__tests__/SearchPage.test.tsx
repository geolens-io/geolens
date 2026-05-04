import { act } from 'react';
import { render, screen } from '@/test/test-utils';
import { SearchPage } from '@/pages/SearchPage';
import { useSearchResults } from '@/components/search/hooks/use-search';
import { useSearchStore } from '@/components/search/search-store';
import { useAuthStore } from '@/stores/auth-store';
import type { OGCRecordResponse } from '@/types/api';

vi.mock('@/components/search/hooks/use-search', () => ({
  useSearchResults: vi.fn(),
}));

vi.mock('@/components/search/hooks/use-url-search-sync', () => ({
  useUrlSearchSync: vi.fn(),
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

vi.mock('@/components/search/SearchBar', () => ({
  SearchBar: ({ mode = 'hero' }: { mode?: 'hero' | 'compact' }) => (
    <div data-testid="search-bar" data-mode={mode} />
  ),
}));

vi.mock('@/components/search/SavedSearches', () => ({
  SavedSearches: () => <div data-testid="saved-searches">Saved searches</div>,
}));

vi.mock('@/components/search/FilterPanel', () => ({
  FilterPanel: ({ totalResults }: { totalResults: number | undefined }) => (
    <div data-testid="filter-panel">{totalResults ?? 'none'}</div>
  ),
}));

vi.mock('@/components/search/SearchResultCard', () => ({
  SearchResultCard: ({ feature }: { feature: OGCRecordResponse }) => (
    <article data-testid="search-result-card">{feature.properties.title}</article>
  ),
}));

vi.mock('@/components/search/DatasetCardSkeleton', () => ({
  DatasetCardSkeleton: () => <div data-testid="dataset-card-skeleton" />,
}));

vi.mock('@/components/layout/Pagination', () => ({
  Pagination: ({ total }: { total: number }) => <div data-testid="pagination">{total}</div>,
}));

const mockUseSearchResults = vi.mocked(useSearchResults);
const initialSearchState = useSearchStore.getState();
const initialAuthState = useAuthStore.getState();

function makeFeature(id: string, title: string): OGCRecordResponse {
  return {
    type: 'Feature',
    id,
    geometry: null,
    properties: {
      type: 'dataset',
      title,
      description: 'Dataset description',
      keywords: [],
      created: '2026-04-01T00:00:00Z',
      updated: '2026-04-02T00:00:00Z',
      updated_by_display: 'editor',
      never_edited: false,
      crs: null,
      geometry_type: null,
      feature_count: 10,
      contacts: null,
      license: null,
      source_organization: 'GeoLens',
      quality_detail: null,
      record_type: 'vector_dataset',
      has_quicklook: false,
      record_status: 'ready',
    },
    links: [],
  };
}

function setAnonymousUser() {
  act(() => {
    useAuthStore.setState({
      ...initialAuthState,
      token: null,
      refreshToken: null,
      expiresAt: null,
      user: null,
    });
  });
}

function setAuthenticatedUser() {
  act(() => {
    useAuthStore.setState({
      ...initialAuthState,
      token: 'token',
      refreshToken: 'refresh-token',
      expiresAt: Date.now() + 60_000,
      user: {
        id: 'user-1',
        username: 'demo',
        email: 'demo@example.com',
        is_active: true,
        status: 'active',
        last_login_at: null,
        created_at: '2026-04-01T00:00:00Z',
        roles: ['editor'],
      },
    });
  });
}

describe('SearchPage', () => {
  beforeEach(() => {
    act(() => {
      useSearchStore.setState(initialSearchState, true);
      useAuthStore.setState(initialAuthState, true);
    });

    mockUseSearchResults.mockReturnValue({
      data: {
        type: 'FeatureCollection',
        numberMatched: 12,
        numberReturned: 2,
        features: [
          makeFeature('dataset-1', 'California Watersheds'),
          makeFeature('dataset-2', 'Road Centerlines'),
        ],
      },
      isLoading: false,
      error: null,
      isFetching: false,
    } as ReturnType<typeof useSearchResults>);
  });

  it('renders a compact search workspace for anonymous users', () => {
    setAnonymousUser();

    render(<SearchPage />, { route: '/' });

    expect(screen.getByTestId('search-bar')).toHaveAttribute('data-mode', 'compact');
    expect(screen.getAllByTestId('filter-panel')).toHaveLength(2);
    screen.getAllByTestId('filter-panel').forEach((panel) => {
      expect(panel).toHaveTextContent('12');
    });
    expect(screen.getByRole('heading', { level: 1, name: /search the geolens catalog/i, hidden: true })).toHaveClass('sr-only');
    expect(screen.queryByTestId('saved-searches')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /view on github/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/datasets in the catalog/i)).not.toBeInTheDocument();
  });

  it('shows saved searches for authenticated users in the workspace header', () => {
    setAuthenticatedUser();

    render(<SearchPage />, { route: '/' });

    expect(screen.getByTestId('search-bar')).toHaveAttribute('data-mode', 'compact');
    expect(screen.getByTestId('saved-searches')).toBeInTheDocument();
    expect(screen.getAllByTestId('filter-panel')).toHaveLength(2);
    screen.getAllByTestId('filter-panel').forEach((panel) => {
      expect(panel).toHaveTextContent('12');
    });
  });

  it('renders skeletons while loading with no cached data', () => {
    setAnonymousUser();
    mockUseSearchResults.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      isFetching: true,
    } as ReturnType<typeof useSearchResults>);

    render(<SearchPage />, { route: '/' });

    // The skeleton container is announced via role=status / aria-live
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.getAllByTestId('dataset-card-skeleton').length).toBeGreaterThan(0);
    // No results or error visible yet
    expect(screen.queryByTestId('search-result-card')).not.toBeInTheDocument();
  });

  it('renders error state when the query fails', () => {
    setAnonymousUser();
    mockUseSearchResults.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Catalog unreachable'),
      isFetching: false,
    } as ReturnType<typeof useSearchResults>);

    render(<SearchPage />, { route: '/' });

    // ErrorState includes the error message
    expect(screen.getByText(/Catalog unreachable/)).toBeInTheDocument();
    expect(screen.queryByTestId('search-result-card')).not.toBeInTheDocument();
    expect(screen.queryByTestId('dataset-card-skeleton')).not.toBeInTheDocument();
  });

  it('renders empty state when no results match', () => {
    setAnonymousUser();
    mockUseSearchResults.mockReturnValue({
      data: {
        type: 'FeatureCollection',
        numberMatched: 0,
        numberReturned: 0,
        features: [] as OGCRecordResponse[],
      },
      isLoading: false,
      error: null,
      isFetching: false,
    } as unknown as ReturnType<typeof useSearchResults>);

    render(<SearchPage />, { route: '/' });

    // EmptyState from layout renders an accessible heading with the title
    // and no result cards are visible.
    expect(screen.queryByTestId('search-result-card')).not.toBeInTheDocument();
    expect(screen.queryByTestId('dataset-card-skeleton')).not.toBeInTheDocument();
  });
});
