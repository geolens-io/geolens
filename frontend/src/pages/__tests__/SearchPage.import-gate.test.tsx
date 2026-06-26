/**
 * GLUX-006 regression test: the catalog Import CTA must be gated on the
 * 'upload' capability, not on token presence. A guest or viewer-role user
 * must not see an Import link that dead-ends at the editor-gated /import route.
 *
 * Gate: SearchPage derives `canImport = can('upload')`, matching the Navbar
 * pattern. can() returns false when permissions is null (hook disabled with
 * no token), so a token-bearing viewer is also excluded.
 */

import { act } from 'react';
import { render, screen } from '@/test/test-utils';
import { SearchPage } from '@/pages/SearchPage';
import { useSearchResults } from '@/components/search/hooks/use-search';
import { useAuthStore } from '@/stores/auth-store';
import { useSearchStore } from '@/stores/search-store';
import type { UserResponse } from '@/types/api';

// Control can() per test
const mockUsePermissions = vi.fn();
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => mockUsePermissions(),
}));

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
  SearchBar: () => <div data-testid="search-bar" />,
}));

vi.mock('@/components/search/SavedSearches', () => ({
  SavedSearches: () => <div data-testid="saved-searches" />,
}));

vi.mock('@/components/search/FilterPanel', () => ({
  FilterPanel: () => <div data-testid="filter-panel" />,
}));

vi.mock('@/components/search/SearchResultCard', () => ({
  SearchResultCard: () => <div data-testid="search-result-card" />,
}));

vi.mock('@/components/search/DatasetCardSkeleton', () => ({
  DatasetCardSkeleton: () => <div data-testid="dataset-card-skeleton" />,
}));

vi.mock('@/components/layout/Pagination', () => ({
  Pagination: () => <div data-testid="pagination" />,
}));

const mockUseSearchResults = vi.mocked(useSearchResults);
const initialAuthState = useAuthStore.getState();
const initialSearchState = useSearchStore.getState();

// An empty catalog (no results, no active query) triggers the Import CTA branch.
const EMPTY_CATALOG = {
  data: {
    type: 'FeatureCollection' as const,
    numberMatched: 0,
    numberReturned: 0,
    features: [],
  },
  isLoading: false,
  error: null,
  isFetching: false,
} as unknown as ReturnType<typeof useSearchResults>;

function makeUser(overrides: Partial<UserResponse> = {}): UserResponse {
  return {
    id: 'u1',
    username: 'testuser',
    email: 'test@example.com',
    is_active: true,
    status: 'active',
    last_login_at: null,
    created_at: '2026-01-01T00:00:00Z',
    roles: ['viewer'],
    ...overrides,
  };
}

describe('SearchPage — Import CTA capability gate (GLUX-006)', () => {
  beforeEach(() => {
    mockUsePermissions.mockReset();
    act(() => {
      useAuthStore.setState(initialAuthState, true);
      useSearchStore.setState(initialSearchState, true);
    });
    mockUseSearchResults.mockReturnValue(EMPTY_CATALOG);
  });

  it('guest (no token, upload capability false) — no Import CTA', () => {
    act(() => {
      useAuthStore.setState({ ...initialAuthState, token: null, user: null }, true);
    });
    mockUsePermissions.mockReturnValue({
      can: () => false,
      isLoading: false,
      permissions: null,
    });

    render(<SearchPage />, { route: '/' });

    expect(
      screen.queryByRole('link', { name: /import your first dataset/i }),
    ).not.toBeInTheDocument();
  });

  it('viewer (token present, upload capability false) — no Import CTA', () => {
    act(() => {
      useAuthStore.setState(
        { ...initialAuthState, token: 'viewer-token', user: makeUser({ roles: ['viewer'] }) },
        true,
      );
    });
    mockUsePermissions.mockReturnValue({
      can: () => false,
      isLoading: false,
      permissions: { upload: false },
    });

    render(<SearchPage />, { route: '/' });

    expect(
      screen.queryByRole('link', { name: /import your first dataset/i }),
    ).not.toBeInTheDocument();
  });

  it('editor (upload capability true) — Import CTA present and links to /import', () => {
    act(() => {
      useAuthStore.setState(
        { ...initialAuthState, token: 'editor-token', user: makeUser({ roles: ['editor'] }) },
        true,
      );
    });
    mockUsePermissions.mockReturnValue({
      can: (cap: string) => cap === 'upload',
      isLoading: false,
      permissions: { upload: true },
    });

    render(<SearchPage />, { route: '/' });

    const cta = screen.getByRole('link', { name: /import your first dataset/i });
    expect(cta).toBeInTheDocument();
    expect(cta).toHaveAttribute('href', '/import');
  });
});
