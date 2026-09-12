import { render, waitFor } from '@/test/test-utils';
import { ApiError } from '@/api/client';
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

  // With auth_mode=cookie, the refresh token arrives as an httpOnly
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

  // A transient /auth/me/ failure after SSO must not revoke the user's other sessions.
  it('keeps the other sessions when getMe fails transiently after sign-in', async () => {
    mockGetMe.mockRejectedValueOnce(new ApiError('server error', 500));
    setHash('#token=access-1&expires_in=900&auth_mode=cookie');

    render(<OAuthCallbackPage />);

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true }),
    );
    expect(mockLogoutSession).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBeNull();
  });

  // An unconfirmed 401 is not a credential rejection and must not revoke other sessions.
  it('keeps the other sessions when getMe answers an unconfirmed 401', async () => {
    const unconfirmed = new ApiError('unauthorized', 401);
    unconfirmed.unconfirmed = true;
    mockGetMe.mockRejectedValueOnce(unconfirmed);
    setHash('#token=access-1&expires_in=900&auth_mode=cookie');

    render(<OAuthCallbackPage />);

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true }),
    );
    expect(mockLogoutSession).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBeNull();
  });

  // The cookie is already installed by the time this page runs, so a
  // rejected credential must be revoked — clearing the store cannot reach it.
  it('revokes the session when getMe rejects the credential', async () => {
    mockGetMe.mockRejectedValueOnce(new ApiError('unauthorized', 401));
    setHash('#token=access-1&expires_in=900&auth_mode=cookie');

    render(<OAuthCallbackPage />);

    await waitFor(() => expect(mockLogoutSession).toHaveBeenCalledTimes(1));
    expect(useAuthStore.getState().token).toBeNull();
    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true }),
    );
  });

  // A fragment too incomplete to finish sign-in is no evidence the
  // credential was rejected, and revoking would end every other session.
  it('does not revoke when an incomplete fragment goes back to /login', async () => {
    setHash('#expires_in=900&auth_mode=cookie');

    render(<OAuthCallbackPage />);

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true }),
    );
    expect(mockGetMe).not.toHaveBeenCalled();
    expect(mockLogoutSession).not.toHaveBeenCalled();
  });

  /**
   * The redirect key is read and cleared between a successful
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
