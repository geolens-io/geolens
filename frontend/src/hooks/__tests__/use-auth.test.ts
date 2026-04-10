import { renderHook, act } from '@/test/test-utils';
import { useAuth } from '@/hooks/use-auth';
import { useAuthStore } from '@/stores/auth-store';
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
});
