import { act } from 'react';
import { render, screen } from '@/test/test-utils';
import { MapsPage } from '@/pages/MapsPage';
import { SearchPage } from '@/pages/SearchPage';
import { useSearchResults } from '@/components/search/hooks/use-search';
import { useAuthStore } from '@/stores/auth-store';
import { useSearchStore } from '@/stores/search-store';
import type { UserResponse } from '@/types/api';

const permissions = vi.hoisted(() => ({ upload: false, editMetadata: false }));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: (cap: string) =>
      (cap === 'upload' && permissions.upload) || (cap === 'edit_metadata' && permissions.editMetadata),
    isLoading: false,
    permissions: null,
  }),
}));
vi.mock('@/components/search/hooks/use-search', () => ({
  useSearchResults: vi.fn(),
  useMapSearchResults: vi.fn(() => ({ data: undefined })),
}));
vi.mock('@/components/search/hooks/use-url-search-sync', () => ({ useUrlSearchSync: vi.fn() }));
vi.mock('@/hooks/use-document-title', () => ({ useDocumentTitle: vi.fn() }));
vi.mock('@/components/search/SearchBar', () => ({ SearchBar: () => <div /> }));
vi.mock('@/components/search/SavedSearches', () => ({ SavedSearches: () => <div /> }));
vi.mock('@/components/search/FilterPanel', () => ({ FilterPanel: () => <div /> }));
vi.mock('@/hooks/use-maps', () => ({
  useMaps: () => ({ data: { total: 0, maps: [] }, isLoading: false }),
  useDeleteMap: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('@/components/maps/MapCreateDialog', () => ({ MapCreateDialog: () => null }));

const initialAuth = useAuthStore.getState();
const initialSearch = useSearchStore.getState();

const user = {
  id: 'u1',
  username: 'viewer',
  email: 'v@example.com',
  is_active: true,
  status: 'active',
  last_login_at: null,
  created_at: '2026-01-01T00:00:00Z',
  roles: ['viewer'],
} as UserResponse;

function signedIn(signedInUser: UserResponse | null) {
  act(() => {
    useAuthStore.setState(
      { ...initialAuth, token: signedInUser ? 'tok' : null, user: signedInUser },
      true,
    );
  });
}

beforeEach(() => {
  permissions.upload = false;
  permissions.editMetadata = false;
  localStorage.clear();
  act(() => useSearchStore.setState(initialSearch, true));
  vi.mocked(useSearchResults).mockReturnValue({
    data: { type: 'FeatureCollection', numberMatched: 0, numberReturned: 0, features: [] },
    isLoading: false,
    error: null,
    isFetching: false,
  } as unknown as ReturnType<typeof useSearchResults>);
});

describe('empty catalog', () => {
  it('tells an anonymous visitor to sign in instead of to import', () => {
    signedIn(null);
    render(<SearchPage />, { route: '/' });
    expect(screen.getByText(/no public datasets yet/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login');
    expect(screen.queryByText(/Import a dataset/)).not.toBeInTheDocument();
  });

  it('shows a neutral message to a signed-in user without import access', () => {
    signedIn(user);
    render(<SearchPage />, { route: '/' });
    expect(screen.getByText(/No datasets are visible to you yet/)).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('keeps the import copy and button for a user who can import', () => {
    permissions.upload = true;
    signedIn(user);
    render(<SearchPage />, { route: '/' });
    expect(screen.getByText('Your catalog is empty')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /import your first dataset/i })).toHaveAttribute('href', '/import');
  });
});

describe('empty maps list', () => {
  it('tells an anonymous visitor to sign in instead of to create', () => {
    signedIn(null);
    render(<MapsPage />);
    expect(screen.getByText(/no public maps yet/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login');
    expect(screen.queryByRole('button', { name: /create/i })).not.toBeInTheDocument();
  });

  it('shows a neutral message to a signed-in user who cannot create maps', () => {
    signedIn(user);
    render(<MapsPage />);
    expect(screen.getByText(/No maps are visible to you yet/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Sign in' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /create/i })).not.toBeInTheDocument();
  });

  it('treats a session whose profile is still loading as signed in', () => {
    act(() => {
      useAuthStore.setState({ ...initialAuth, token: 'tok', user: null }, true);
    });
    render(<MapsPage />);
    expect(screen.getByText(/No maps are visible to you yet/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Sign in' })).not.toBeInTheDocument();
  });

  it('keeps the create copy and button for a user who can edit maps', () => {
    permissions.editMetadata = true;
    signedIn(user);
    render(<MapsPage />);
    expect(screen.getByText(/Create a map to start composing layers/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create your first map' })).toBeInTheDocument();
  });
});
