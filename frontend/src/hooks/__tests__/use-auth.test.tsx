import { renderHook, act, waitFor } from '@/test/test-utils';
import { useAuth } from '@/hooks/use-auth';
import { useAuthStore } from '@/stores/auth-store';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { MemoryRouter } from 'react-router';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { TokenResponse, UserResponse } from '@/types/api';

const mockNavigate = vi.fn();

vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockLogin = vi.fn<(u: string, p: string) => Promise<TokenResponse>>();
const mockGetMe = vi.fn<() => Promise<UserResponse>>();
const mockRefresh = vi.fn();

vi.mock('@/api/auth', () => ({
  login: (...args: unknown[]) => mockLogin(...(args as [string, string])),
  getMe: () => mockGetMe(),
  refreshAccessToken: (...args: unknown[]) => mockRefresh(...args),
}));

function mockUser(overrides?: Partial<UserResponse>): UserResponse {
  return {
    id: '1',
    username: 'testuser',
    email: 'test@example.com',
    is_active: true,
    status: 'approved',
    last_login_at: null,
    created_at: '2025-01-01T00:00:00Z',
    roles: ['viewer'],
    ...overrides,
  };
}

describe('useAuth', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetMe.mockResolvedValue(mockUser());
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
  });

  it('returns null token and user when not authenticated', () => {
    const { result } = renderHook(() => useAuth());

    expect(result.current.token).toBeNull();
    expect(result.current.user).toBeNull();
    expect(result.current.isAdmin).toBe(false);
    expect(result.current.isEditor).toBe(false);
  });

  it('login calls API and stores auth state', async () => {
    const tokenRes: TokenResponse = {
      access_token: 'new-token',
      refresh_token: 'new-refresh',
      token_type: 'bearer',
      expires_in: 900,
    };
    const user = mockUser();

    mockLogin.mockResolvedValueOnce(tokenRes);
    mockGetMe.mockResolvedValueOnce(user);

    const { result } = renderHook(() => useAuth());

    await act(async () => {
      await result.current.login('admin', 'password');
    });

    expect(mockLogin).toHaveBeenCalledWith('admin', 'password');
    expect(mockGetMe).toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe('new-token');
    expect(useAuthStore.getState().refreshToken).toBe('new-refresh');
    expect(useAuthStore.getState().user).toEqual(user);
  });

  it('login throws when API login fails', async () => {
    mockLogin.mockRejectedValueOnce(new Error('Invalid credentials'));

    const { result } = renderHook(() => useAuth());

    await expect(
      act(async () => {
        await result.current.login('bad', 'creds');
      }),
    ).rejects.toThrow('Invalid credentials');
  });

  it('logout clears store and navigates to /login', () => {
    useAuthStore.setState({ token: 'abc', refreshToken: 'ref', expiresAt: 999, user: mockUser() });

    const { result } = renderHook(() => useAuth());

    act(() => {
      result.current.logout();
    });

    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
    expect(mockNavigate).toHaveBeenCalledWith('/login');
  });

  it('reflects admin role from store', () => {
    useAuthStore.setState({
      token: 'abc',
      refreshToken: null,
      expiresAt: null,
      user: mockUser({ roles: ['admin'] }),
    });

    const { result } = renderHook(() => useAuth());

    expect(result.current.isAdmin).toBe(true);
    expect(result.current.isEditor).toBe(true);
  });

  it('reflects editor role from store', () => {
    useAuthStore.setState({
      token: 'abc',
      refreshToken: null,
      expiresAt: null,
      user: mockUser({ roles: ['editor'] }),
    });

    const { result } = renderHook(() => useAuth());

    expect(result.current.isAdmin).toBe(false);
    expect(result.current.isEditor).toBe(true);
  });

  // BUG-021: query cache must be cleared on logout and invalidated on login
  // so a new login never shows the previous user's stale identity.
  describe('BUG-021: auth query cache management', () => {
    /** Helper — renders useAuth with a shared, observable queryClient. */
    function renderWithQueryClient(queryClient: QueryClient) {
      function Wrapper({ children }: { children: React.ReactNode }) {
        return (
          <QueryClientProvider client={queryClient}>
            <TooltipProvider>
              <MemoryRouter>
                {children}
              </MemoryRouter>
            </TooltipProvider>
          </QueryClientProvider>
        );
      }
      return renderHook(() => useAuth(), { wrapper: Wrapper });
    }

    it('invalidates [auth,me] query on login so cached stale identity is not used', async () => {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      });

      const userA = mockUser({ id: 'A', username: 'userA' });
      const userB = mockUser({ id: 'B', username: 'userB' });

      // Seed stale user A into the cache
      queryClient.setQueryData(queryKeys.auth.me, userA);

      const tokenRes: TokenResponse = {
        access_token: 'token-B',
        refresh_token: 'refresh-B',
        token_type: 'bearer',
        expires_in: 900,
      };
      mockLogin.mockResolvedValueOnce(tokenRes);
      // getMe is called twice: once inside login() for setAuth, once by the
      // meQuery refetch triggered by invalidateQueries.
      mockGetMe.mockResolvedValue(userB);

      const { result } = renderWithQueryClient(queryClient);

      await act(async () => {
        await result.current.login('userB', 'pw');
      });

      // The cache for ['auth','me'] must either be empty (invalidated + no
      // in-flight refetch completed) or contain user B — NEVER user A.
      const cached = queryClient.getQueryData(queryKeys.auth.me);
      if (cached !== undefined) {
        expect((cached as UserResponse).id).toBe('B');
      }
      // Auth store must reflect user B
      expect(useAuthStore.getState().user?.id).toBe('B');
    });

    it('removes [auth,me] from cache on logout', async () => {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      });

      const user = mockUser();
      queryClient.setQueryData(queryKeys.auth.me, user);
      useAuthStore.setState({ token: 'tok', refreshToken: 'ref', expiresAt: 999, user });

      const { result } = renderWithQueryClient(queryClient);

      act(() => {
        result.current.logout();
      });

      // Cache for ['auth','me'] must be gone after logout
      expect(queryClient.getQueryData(queryKeys.auth.me)).toBeUndefined();
    });
  });

  it('restores user state when a persisted token validates successfully', async () => {
    const user = mockUser({ roles: ['editor'] });
    mockGetMe.mockResolvedValueOnce(user);
    useAuthStore.setState({
      token: 'persisted-token',
      refreshToken: 'persisted-refresh',
      expiresAt: Date.now() + 900_000,
      user: null,
    });

    renderHook(() => useAuth());

    await waitFor(() => {
      expect(useAuthStore.getState().user).toEqual(user);
    });
    expect(useAuthStore.getState().isEditor()).toBe(true);
  });
});
