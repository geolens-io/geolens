import { render, waitFor } from '@/test/test-utils';
import { OAuthCallbackPage } from '@/pages/OAuthCallbackPage';
import { useAuthStore } from '@/stores/auth-store';
import { denySessionStorage } from '@/test/deny-storage';
import type { UserResponse } from '@/types/api';

const mockNavigate = vi.fn();
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockGetMe = vi.fn<() => Promise<UserResponse>>();
const mockLogoutSession = vi.fn<() => Promise<void>>();
vi.mock('@/api/auth', () => ({
  getMe: () => mockGetMe(),
  logoutSession: () => mockLogoutSession(),
}));

function setHash(hash: string) {
  window.history.replaceState({}, '', `/oauth/callback${hash}`);
}

describe('OAuthCallbackPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLogoutSession.mockResolvedValue(undefined);
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
  });

  // fix(#1302): with auth_mode=cookie the refresh token arrives as an httpOnly
  // cookie on the redirect and never enters the fragment, which any script on
  // this page can read.
  it('completes sign-in from a cookie-mode fragment carrying no refresh token', async () => {
    const user = { id: '1', username: 'someone', roles: ['viewer'] } as UserResponse;
    mockGetMe.mockResolvedValueOnce(user);
    setHash('#token=access-1&expires_in=900&auth_mode=cookie');

    render(<OAuthCallbackPage />);

    await waitFor(() => expect(useAuthStore.getState().user).toEqual(user));
    expect(useAuthStore.getState().token).toBe('access-1');
    expect(useAuthStore.getState().refreshToken).toBeNull();
    expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true });
  });

  it('still accepts a legacy fragment refresh token (cross-origin fallback)', async () => {
    const user = { id: '1', username: 'someone', roles: ['viewer'] } as UserResponse;
    mockGetMe.mockResolvedValueOnce(user);
    setHash('#token=access-1&refresh_token=legacy-r1&expires_in=900');

    render(<OAuthCallbackPage />);

    await waitFor(() => expect(useAuthStore.getState().user).toEqual(user));
    expect(useAuthStore.getState().refreshToken).toBe('legacy-r1');
  });

  // fix(#1446): the cookie is already installed by the time this page runs, so
  // a failed setup must revoke server-side — clearing the store cannot reach an
  // httpOnly cookie, and the UI would send the user to /login while the
  // credential stayed replayable.
  it('revokes the session when getMe fails after the cookie was installed', async () => {
    mockGetMe.mockRejectedValueOnce(new Error('me failed'));
    setHash('#token=access-1&expires_in=900&auth_mode=cookie');

    render(<OAuthCallbackPage />);

    await waitFor(() => expect(mockLogoutSession).toHaveBeenCalledTimes(1));
    expect(useAuthStore.getState().token).toBeNull();
    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true }),
    );
  });

  // fix(#1446): the cookies were installed by the response that redirected
  // here, so a fragment too incomplete to finish sign-in still leaves a live
  // credential unless it is revoked.
  it('revokes before sending an incomplete fragment back to /login', async () => {
    setHash('#expires_in=900&auth_mode=cookie');

    render(<OAuthCallbackPage />);

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true }),
    );
    expect(mockGetMe).not.toHaveBeenCalled();
    expect(mockLogoutSession).toHaveBeenCalledTimes(1);
  });

  /**
   * fix(#1527): the redirect key is read and cleared between a successful
   * getMe() and the navigation that lands the user. Bare, a storage-denied
   * context threw into the sibling .catch(), which revokes the session and
   * bounces to /login — so a perfectly good SSO round-trip ended signed out.
   */
  it('completes sign-in when sessionStorage access throws', async () => {
    const user = { id: '1', username: 'someone', roles: ['viewer'] } as UserResponse;
    mockGetMe.mockResolvedValueOnce(user);
    setHash('#token=access-1&expires_in=900&auth_mode=cookie');

    const restore = denySessionStorage();
    try {
      render(<OAuthCallbackPage />);

      await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true }));
      expect(useAuthStore.getState().user).toEqual(user);
      expect(mockLogoutSession).not.toHaveBeenCalled();
    } finally {
      restore();
    }
  });
});
