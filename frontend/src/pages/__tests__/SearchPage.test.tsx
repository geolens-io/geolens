import { act } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';

const statusTexts = () => screen.queryAllByRole('status').map((node) => node.textContent);
import { SearchPage } from '@/pages/SearchPage';
import { useSearchResults, useMapSearchResults } from '@/components/search/hooks/use-search';
import { useSearchStore } from '@/stores/search-store';
import { useAuthStore } from '@/stores/auth-store';
import type { OGCRecordResponse } from '@/types/api';

vi.mock('@/components/search/hooks/use-search', () => ({
  useSearchResults: vi.fn(),
  // SearchPage now also calls useMapSearchResults — stub it so
  // the parallel maps section is inert (no maps) unless a test overrides it.
  useMapSearchResults: vi.fn(() => ({ data: undefined })),
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
  FilterPanel: ({ totalResults, allTypesTotal }: { totalResults: number | undefined; allTypesTotal?: number }) => (
    <div data-testid="filter-panel" data-all-total={allTypesTotal ?? 'none'}>{totalResults ?? 'none'}</div>
  ),
}));

vi.mock('@/components/search/SearchResultCard', () => ({
  SearchResultCard: ({ feature, density }: { feature: OGCRecordResponse; density?: string }) => (
    <article data-testid="search-result-card" data-density={density ?? 'comfortable'}>{feature.properties.title}</article>
  ),
}));

vi.mock('@/components/search/DatasetCardSkeleton', () => ({
  DatasetCardSkeleton: () => <div data-testid="dataset-card-skeleton" />,
}));

vi.mock('@/components/layout/Pagination', () => ({
  Pagination: ({ total }: { total: number }) => <div data-testid="pagination">{total}</div>,
}));

vi.mock('@/components/maps/MapCard', () => ({
  MapCard: ({ map }: { map: { id: string; name: string } }) => (
    <article data-testid="map-card">{map.name}</article>
  ),
}));

const liveAnnouncementProps: { text: string; trigger?: string }[] = [];
vi.mock('@/components/ui/live-announcement', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/ui/live-announcement')>();
  return {
    LiveAnnouncement: (props: { text: string; trigger?: string }) => {
      liveAnnouncementProps.push({ text: props.text, trigger: props.trigger });
      return <actual.LiveAnnouncement {...props} />;
    },
  };
});

const mockUseSearchResults = vi.mocked(useSearchResults);
const mockUseMapSearchResults = vi.mocked(useMapSearchResults);
const initialSearchState = useSearchStore.getState();
const initialAuthState = useAuthStore.getState();

function makeFeature(id: string, title: string): OGCRecordResponse {
  return {
    type: 'Feature',
    id,
    geometry: null,
    time: {},
    properties: {
      type: 'dataset',
      title,
      description: 'Dataset description',
      keywords: [],
      created: '2026-04-01T00:00:00Z',
      updated: '2026-04-02T00:00:00Z',
      updated_by_display: 'editor',
      never_edited: false,
      themes: [],
      time: {},
      source_freshness: 'unknown',
      source_health: 'unknown',
      crs: null,
      geometry_type: null,
      feature_count: 10,
      contacts: [],
      license: 'proprietary',
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
        can_reset_password: true,
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

    // Inert maps lookup by default; individual tests override.
    mockUseMapSearchResults.mockReturnValue(
      { data: undefined } as unknown as ReturnType<typeof useMapSearchResults>,
    );

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

  describe('result density', () => {
    const densities = () => screen.getAllByTestId('search-result-card').map((c) => c.getAttribute('data-density'));

    beforeEach(() => {
      window.history.replaceState(null, '', '/');
      liveAnnouncementProps.length = 0;
    });

    it('defaults to comfortable rows and leaves the page size alone', () => {
      render(<SearchPage />, { route: '/' });

      expect(densities()).toEqual(['comfortable', 'comfortable']);
      expect(screen.getByRole('radio', { name: 'Comfortable' })).toBeChecked();
      expect(useSearchStore.getState().limit).toBe(10);
    });

    it('switches to compact, stores the choice and moves to 25 per page', async () => {
      act(() => useSearchStore.setState({ offset: 20 }));
      render(<SearchPage />, { route: '/' });

      await userEvent.click(screen.getByRole('radio', { name: 'Compact' }));

      expect(densities()).toEqual(['compact', 'compact']);
      expect(screen.getByRole('radio', { name: 'Compact' })).toBeChecked();
      expect(localStorage.getItem('geolens-search-view')).toBe('compact');
      expect(useSearchStore.getState().limit).toBe(25);
      expect(useSearchStore.getState().offset).toBe(0);
      expect(screen.getByRole('radio', { name: 'Compact' })).toHaveFocus();
    });

    it('returns to 10 per page when switching back to comfortable', async () => {
      localStorage.setItem('geolens-search-view', 'compact');
      render(<SearchPage />, { route: '/' });
      act(() => useSearchStore.setState({ offset: 25 }));

      await userEvent.click(screen.getByRole('radio', { name: 'Comfortable' }));

      expect(densities()).toEqual(['comfortable', 'comfortable']);
      expect(localStorage.getItem('geolens-search-view')).toBe('comfortable');
      expect(useSearchStore.getState().limit).toBe(10);
      // Result 26 was first on the page; the page of ten that holds it starts at 21.
      expect(useSearchStore.getState().offset).toBe(20);
    });

    it('stays on the page that holds the first result shown when the view changes', async () => {
      act(() => useSearchStore.setState({ offset: 60 }));
      render(<SearchPage />, { route: '/' });

      await userEvent.click(screen.getByRole('radio', { name: 'Compact' }));
      expect(useSearchStore.getState().offset).toBe(50);

      await userEvent.click(screen.getByRole('radio', { name: 'Comfortable' }));
      expect(useSearchStore.getState().offset).toBe(50);
    });

    it('trims the previous page to the chosen view while the next one loads, and shows a settled page whole', async () => {
      localStorage.setItem('geolens-search-view', 'compact');
      act(() => useSearchStore.getState().resetFilters());
      const page = (count: number, isFetching: boolean) =>
        ({
          data: {
            type: 'FeatureCollection',
            numberMatched: 60,
            numberReturned: count,
            features: Array.from({ length: count }, (_, i) => makeFeature(`dataset-${i + 1}`, `Dataset ${i + 1}`)),
          },
          isLoading: false,
          error: null,
          isFetching,
        }) as ReturnType<typeof useSearchResults>;
      mockUseSearchResults.mockReturnValue(page(25, false));
      const { rerender } = render(<SearchPage />, { route: '/' });
      expect(densities()).toHaveLength(25);

      // The 25 rows stay as placeholder data while the page of ten loads.
      mockUseSearchResults.mockReturnValue(page(25, true));
      await userEvent.click(screen.getByRole('radio', { name: 'Comfortable' }));
      expect(densities()).toEqual(Array.from({ length: 10 }, () => 'comfortable'));

      // The first page can end with collection matches beyond its size.
      mockUseSearchResults.mockReturnValue(page(15, false));
      rerender(<SearchPage />);
      expect(densities()).toHaveLength(15);
    });

    it('uses a stored compact choice on load, already on the first query', () => {
      localStorage.setItem('geolens-search-view', 'compact');
      act(() => useSearchStore.getState().resetFilters());
      const limitsSeen: number[] = [];
      mockUseSearchResults.mockImplementation(() => {
        limitsSeen.push(useSearchStore.getState().limit);
        return {
          data: { type: 'FeatureCollection', numberMatched: 1, numberReturned: 1, features: [makeFeature('dataset-1', 'A')] },
          isLoading: false,
          error: null,
          isFetching: false,
        } as unknown as ReturnType<typeof useSearchResults>;
      });
      render(<SearchPage />, { route: '/' });

      expect(densities()).toEqual(['compact']);
      expect(new Set(limitsSeen)).toEqual(new Set([25]));
    });

    it('keeps 25 per page when "Clear search & filters" is used in compact', async () => {
      localStorage.setItem('geolens-search-view', 'compact');
      act(() => useSearchStore.setState({ q: 'nothing here', limit: 25 }));
      mockUseSearchResults.mockReturnValue({
        data: { type: 'FeatureCollection', numberMatched: 0, numberReturned: 0, features: [] },
        isLoading: false,
        error: null,
        isFetching: false,
      } as unknown as ReturnType<typeof useSearchResults>);
      render(<SearchPage />, { route: '/' });

      await userEvent.click(screen.getByRole('button', { name: 'Clear search & filters' }));

      expect(useSearchStore.getState().q).toBe('');
      expect(useSearchStore.getState().limit).toBe(25);
    });

    it('still works when storage throws', async () => {
      const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('denied');
      });
      const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('denied');
      });
      try {
        render(<SearchPage />, { route: '/' });
        expect(densities()).toEqual(['comfortable', 'comfortable']);

        await userEvent.click(screen.getByRole('radio', { name: 'Compact' }));
        expect(densities()).toEqual(['compact', 'compact']);
        expect(useSearchStore.getState().limit).toBe(25);
      } finally {
        getItem.mockRestore();
        setItem.mockRestore();
      }
    });

    it('keeps the chosen view through "Clear search & filters" when storage is unavailable', async () => {
      const spies = (['getItem', 'setItem'] as const).map((m) =>
        vi.spyOn(Storage.prototype, m).mockImplementation(() => {
          throw new Error('denied');
        }),
      );
      try {
        const { rerender } = render(<SearchPage />, { route: '/' });
        await userEvent.click(screen.getByRole('radio', { name: 'Compact' }));
        const populated = mockUseSearchResults();

        act(() => useSearchStore.setState({ q: 'nothing here' }));
        mockUseSearchResults.mockReturnValue({
          data: { type: 'FeatureCollection', numberMatched: 0, numberReturned: 0, features: [] },
          isLoading: false,
          error: null,
          isFetching: false,
        } as unknown as ReturnType<typeof useSearchResults>);
        rerender(<SearchPage />);
        await userEvent.click(screen.getByRole('button', { name: 'Clear search & filters' }));
        expect(useSearchStore.getState().limit).toBe(25);

        mockUseSearchResults.mockReturnValue(populated);
        rerender(<SearchPage />);
        expect(densities()).toEqual(['compact', 'compact']);
        expect(screen.getByRole('radio', { name: 'Compact' })).toBeChecked();
      } finally {
        spies.forEach((spy) => spy.mockRestore());
      }
    });

    it('labels the group and is operable from the keyboard', async () => {
      render(<SearchPage />, { route: '/' });

      expect(screen.getByRole('radiogroup', { name: 'Result view' })).toBeInTheDocument();
      screen.getByRole('radio', { name: 'Comfortable' }).focus();
      await userEvent.keyboard('{ArrowRight}{Enter}');

      expect(screen.getByRole('radio', { name: 'Compact' })).toBeChecked();
    });

    it('never changes the announcement trigger or text when the view changes', async () => {
      render(<SearchPage />, { route: '/' });
      await waitFor(() => expect(statusTexts()).toContain('12 catalog results'));
      liveAnnouncementProps.length = 0;

      await userEvent.click(screen.getByRole('radio', { name: 'Compact' }));
      await userEvent.click(screen.getByRole('radio', { name: 'Comfortable' }));

      expect(liveAnnouncementProps.length).toBeGreaterThan(0);
      expect(new Set(liveAnnouncementProps.map((p) => p.trigger)).size).toBe(1);
      expect(new Set(liveAnnouncementProps.map((p) => p.text))).toEqual(new Set(['12 catalog results']));
    });

    it('keeps the announcement trigger when a view change moves the page start', async () => {
      act(() => useSearchStore.setState({ offset: 30 }));
      render(<SearchPage />, { route: '/' });
      await waitFor(() => expect(statusTexts()).toContain('12 catalog results'));
      const settledTrigger = liveAnnouncementProps.at(-1)?.trigger;
      liveAnnouncementProps.length = 0;

      await userEvent.click(screen.getByRole('radio', { name: 'Compact' }));
      expect(useSearchStore.getState().offset).toBe(25);
      await userEvent.click(screen.getByRole('radio', { name: 'Comfortable' }));
      expect(useSearchStore.getState().offset).toBe(20);

      expect(new Set(liveAnnouncementProps.map((p) => p.trigger))).toEqual(new Set([settledTrigger]));

      act(() => useSearchStore.getState().setPage(40));
      expect(liveAnnouncementProps.at(-1)?.trigger).not.toBe(settledTrigger);
    });

    it('holds the announcement through a pending refetch after a view change, but not a new query', async () => {
      const populated = mockUseSearchResults();
      const { rerender } = render(<SearchPage />, { route: '/' });
      await waitFor(() => expect(statusTexts()).toContain('12 catalog results'));
      const settledTrigger = liveAnnouncementProps.at(-1)?.trigger;
      liveAnnouncementProps.length = 0;

      mockUseSearchResults.mockReturnValue({ ...populated, isFetching: true } as ReturnType<typeof useSearchResults>);
      await userEvent.click(screen.getByRole('radio', { name: 'Compact' }));
      mockUseSearchResults.mockReturnValue(populated);
      rerender(<SearchPage />);

      expect(liveAnnouncementProps.length).toBeGreaterThan(1);
      expect(new Set(liveAnnouncementProps.map((p) => p.text))).toEqual(new Set(['12 catalog results']));
      expect(new Set(liveAnnouncementProps.map((p) => p.trigger))).toEqual(new Set([settledTrigger]));

      mockUseSearchResults.mockReturnValue({ ...populated, isFetching: true } as ReturnType<typeof useSearchResults>);
      await userEvent.click(screen.getByRole('radio', { name: 'Comfortable' }));
      act(() => useSearchStore.getState().setQuery('roads'));

      expect(liveAnnouncementProps.at(-1)?.text).toBe('Updating results...');
      expect(liveAnnouncementProps.at(-1)?.trigger).not.toBe(settledTrigger);
    });

    it('still re-triggers the announcement for a new query', async () => {
      render(<SearchPage />, { route: '/' });
      const before = liveAnnouncementProps.at(-1)?.trigger;

      act(() => useSearchStore.getState().setQuery('roads'));

      expect(liveAnnouncementProps.at(-1)?.trigger).not.toBe(before);
    });

    it('shows compact skeletons while loading in compact mode', () => {
      localStorage.setItem('geolens-search-view', 'compact');
      mockUseSearchResults.mockReturnValue({
        data: undefined, isLoading: true, error: null, isFetching: true,
      } as unknown as ReturnType<typeof useSearchResults>);
      render(<SearchPage />, { route: '/' });

      expect(screen.getAllByTestId('dataset-card-skeleton')).toHaveLength(12);
    });
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

  it('mounts the live region empty, then announces the count and the refetch', async () => {
    setAnonymousUser();
    const base = {
      data: {
        type: 'FeatureCollection',
        numberMatched: 12,
        numberReturned: 2,
        features: [makeFeature('dataset-1', 'California Watersheds'), makeFeature('dataset-2', 'Road Centerlines')],
      },
      isLoading: false,
      error: null,
    };
    mockUseSearchResults.mockReturnValue({ ...base, isFetching: false } as ReturnType<typeof useSearchResults>);
    const { rerender } = render(<SearchPage />, { route: '/' });
    // Cached data is present on the first render; the region must still start empty.
    expect(statusTexts()).not.toContain('12 catalog results');
    await waitFor(() => expect(statusTexts()).toContain('12 catalog results'));

    mockUseSearchResults.mockReturnValue({ ...base, isFetching: true } as ReturnType<typeof useSearchResults>);
    rerender(<SearchPage />);
    await waitFor(() => expect(statusTexts()).toContain('Updating results...'));
  });

  describe('live status for empty responses', () => {
    const populated = {
      type: 'FeatureCollection',
      numberMatched: 12,
      numberReturned: 2,
      features: [makeFeature('dataset-1', 'California Watersheds'), makeFeature('dataset-2', 'Road Centerlines')],
    };
    const empty = { type: 'FeatureCollection', numberMatched: 0, numberReturned: 0, features: [] as OGCRecordResponse[] };
    const setResults = (data: object, isFetching: boolean) =>
      mockUseSearchResults.mockReturnValue({
        data, isLoading: false, error: null, isFetching,
      } as unknown as ReturnType<typeof useSearchResults>);

    it('announces an empty result after a populated one', async () => {
      setAnonymousUser();
      setResults(populated, false);
      const { rerender } = render(<SearchPage />, { route: '/' });
      setResults(populated, true);
      rerender(<SearchPage />);
      setResults(empty, false);
      rerender(<SearchPage />);
      await waitFor(() => expect(statusTexts()).toContain('No catalog results found'));
    });

    it('re-announces when a different cached search has the same count', async () => {
      setAnonymousUser();
      setResults(populated, false);
      render(<SearchPage />, { route: '/' });
      await waitFor(() => expect(statusTexts()).toContain('12 catalog results'));

      act(() => {
        useSearchStore.getState().setQuery('other');
      });
      expect(statusTexts()).not.toContain('12 catalog results');
      await waitFor(() => expect(statusTexts()).toContain('12 catalog results'));
    });

    it('announces both the catalog and map counts when each matched', async () => {
      setAnonymousUser();
      act(() => {
        useSearchStore.getState().setQuery('Matterhorn');
      });
      setResults(populated, false);
      mockUseMapSearchResults.mockReturnValue({
        data: { maps: [{ id: 'm1', name: 'Alps' }], total: 2 },
        isLoading: false, isFetching: false, error: null,
      } as unknown as ReturnType<typeof useMapSearchResults>);
      render(<SearchPage />, { route: '/' });
      await waitFor(() =>
        expect(statusTexts()).toContain('12 catalog results, 2 matching maps'),
      );
    });

    it('announces the map count when the catalog query failed with no cache', async () => {
      setAnonymousUser();
      act(() => {
        useSearchStore.getState().setQuery('Matterhorn');
      });
      mockUseSearchResults.mockReturnValue({
        data: undefined, isLoading: false, error: new Error('Catalog unreachable'), isFetching: false,
      } as unknown as ReturnType<typeof useSearchResults>);
      mockUseMapSearchResults.mockReturnValue({
        data: { maps: [{ id: 'm1', name: 'Alps' }], total: 2 },
        isLoading: false, isFetching: false, error: null,
      } as unknown as ReturnType<typeof useMapSearchResults>);
      render(<SearchPage />, { route: '/' });
      await waitFor(() => expect(statusTexts()).toContain('2 matching maps'));
    });

    it('carries the empty outcome in exactly one live region', async () => {
      setAnonymousUser();
      act(() => {
        useSearchStore.getState().setQuery('Matterhorn');
      });
      setResults(empty, false);
      render(<SearchPage />, { route: '/' });
      await waitFor(() => expect(statusTexts()).toContain('No catalog results found'));
      // Let any second announcer finish filling before counting.
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(statusTexts().filter((text) => text?.includes('No catalog results found'))).toHaveLength(1);
    });

    it('still announces after a second empty search', async () => {
      setAnonymousUser();
      setResults(empty, false);
      const { rerender } = render(<SearchPage />, { route: '/' });
      await waitFor(() => expect(statusTexts()).toContain('No catalog results found'));
      setResults(empty, true);
      rerender(<SearchPage />);
      await waitFor(() => expect(statusTexts()).toContain('Updating results...'));
      setResults(empty, false);
      rerender(<SearchPage />);
      await waitFor(() => expect(statusTexts()).toContain('No catalog results found'));
    });

    it('announces the total map matches, not the page size', async () => {
      setAnonymousUser();
      act(() => {
        useSearchStore.getState().setQuery('Matterhorn');
      });
      setResults(empty, false);
      mockUseMapSearchResults.mockReturnValue({
        data: { maps: [{ id: 'm1', name: 'Alps' }, { id: 'm2', name: 'Alps 2' }], total: 10 },
        isLoading: false, isFetching: false, error: null,
      } as unknown as ReturnType<typeof useMapSearchResults>);
      render(<SearchPage />, { route: '/' });
      await waitFor(() =>
        expect(statusTexts()).toContain('No catalog results found. 10 matching maps'),
      );
    });
  });

  it('lists the results as a list of items', () => {
    setAnonymousUser();
    render(<SearchPage />, { route: '/' });

    const list = screen.getByRole('region', { name: 'Search results' }).querySelector('ul');
    expect(list).not.toBeNull();
    expect(within(list as HTMLElement).getAllByRole('listitem')).toHaveLength(2);
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
    expect(screen.getAllByRole('status').length).toBeGreaterThan(0);
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

  it('passes the all-types total of a typed response to the filter panel as the All count', () => {
    setAnonymousUser();
    mockUseSearchResults.mockReturnValue({
      data: {
        type: 'FeatureCollection',
        numberMatched: 3,
        numberMatchedAllTypes: 5,
        numberReturned: 0,
        features: [] as OGCRecordResponse[],
      },
      isLoading: false,
      error: null,
      isFetching: false,
    } as unknown as ReturnType<typeof useSearchResults>);

    render(<SearchPage />, { route: '/' });

    expect(screen.getAllByTestId('filter-panel')[0]).toHaveAttribute('data-all-total', '5');
  });

  it('passes a loaded zero total to the filter panel as the All count', () => {
    setAnonymousUser();
    mockUseSearchResults.mockReturnValue({
      data: { type: 'FeatureCollection', numberMatched: 0, numberReturned: 0, features: [] as OGCRecordResponse[] },
      isLoading: false,
      error: null,
      isFetching: false,
    } as unknown as ReturnType<typeof useSearchResults>);

    render(<SearchPage />, { route: '/' });

    expect(screen.getAllByTestId('filter-panel')[0]).toHaveAttribute('data-all-total', '0');
  });

  // A query matching maps but zero datasets must show the
  // map cards WITHOUT the contradictory dataset empty state below them.
  it('map-only match renders map cards and suppresses the empty state', () => {
    setAnonymousUser();
    act(() => {
      useSearchStore.getState().setQuery('Matterhorn');
    });
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
    mockUseMapSearchResults.mockReturnValue({
      data: { maps: [{ id: 'map-1', name: 'Matterhorn 3D' }], total: 1 },
    } as unknown as ReturnType<typeof useMapSearchResults>);

    render(<SearchPage />, { route: '/' });

    expect(screen.getByTestId('map-card')).toBeInTheDocument();
    expect(screen.queryByText(/your catalog is empty/i)).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /no catalog results found/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /clear search & filters/i })).toBeInTheDocument();
  });

  it('keeps the no-results state hidden while map text matches are loading', () => {
    setAnonymousUser();
    act(() => {
      useSearchStore.getState().setQuery('Matterhorn');
    });
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
    mockUseMapSearchResults.mockReturnValue({
      data: undefined,
      isLoading: true,
      isFetching: true,
      error: null,
    } as unknown as ReturnType<typeof useMapSearchResults>);

    render(<SearchPage />, { route: '/' });

    expect(screen.getByText('Maps matching "Matterhorn"')).toBeInTheDocument();
    expect(screen.getByText(/map matches use the search text only/i)).toBeInTheDocument();
    expect(screen.getByText(/loading map matches/i)).toBeInTheDocument();
    expect(screen.queryByText(/no catalog results found/i)).not.toBeInTheDocument();
  });

  it('shows a retryable map error separately from catalog results', () => {
    setAnonymousUser();
    const refetchMaps = vi.fn();
    act(() => {
      useSearchStore.getState().setQuery('Matterhorn');
    });
    mockUseMapSearchResults.mockReturnValue({
      data: { maps: [], total: 0 },
      isLoading: false,
      isFetching: false,
      error: new Error('Maps unreachable'),
      refetch: refetchMaps,
    } as unknown as ReturnType<typeof useMapSearchResults>);

    render(<SearchPage />, { route: '/' });

    expect(screen.getByRole('alert')).toHaveTextContent("Couldn't load map matches.");
    fireEvent.click(screen.getByRole('button', { name: /retry map search/i }));
    expect(refetchMaps).toHaveBeenCalledOnce();
    expect(screen.getByRole('heading', { name: '12 catalog results' })).toBeInTheDocument();
  });
});
