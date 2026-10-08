import { render, waitFor } from '@/test/test-utils';
import { ApiError } from '@/api/client';
import { OAuthCallbackPage } from '@/pages/OAuthCallbackPage';
import { useAuthStore } from '@/stores/auth-store';
import { denySessionStorage } from '@/test/deny-storage';
import { otherTab } from '@/test/broadcast-channel';
import { wireSessionSync } from '@/lib/session-sync';
import type { TokenResponse, UserResponse } from '@/types/api';

const mockNavigate = vi.fn();
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockGetMe = vi.fn<() => Promise<UserResponse>>();
const mockLogoutSession = vi.fn<() => Promise<void>>();
const mockRevokeCurrentSession = vi.fn<(token: string) => Promise<void>>();
const mockRefreshAccessToken = vi.fn();
type Install = (session: TokenResponse) => unknown;
const mockExchangeSignInCode = vi.fn<(code: string, install: Install) => Promise<unknown>>();
vi.mock('@/api/auth', () => ({
  exchangeSignInCode: (code: string, install: Install) => mockExchangeSignInCode(code, install),
  getMe: () => mockGetMe(),
  logoutSession: () => mockLogoutSession(),
  revokeCurrentSession: (token: string) => mockRevokeCurrentSession(token),
  refreshAccessToken: () => mockRefreshAccessToken(),
}));

const userA = { id: 'a', username: 'someone', roles: ['viewer'] } as UserResponse;
const userB = { id: 'b', username: 'someone-else', roles: ['viewer'] } as UserResponse;
const exchanged: TokenResponse = {
  access_token: 'access-1',
  refresh_token: null,
  token_type: 'bearer',
  expires_in: 900,
};

function deferProfile() {
  const settle: { resolve: (user: UserResponse) => void; reject: (err: unknown) => void } = {
    resolve: () => {},
    reject: () => {},
  };
  mockGetMe.mockImplementationOnce(
    () => new Promise<UserResponse>((resolve, reject) => {
      settle.resolve = resolve;
      settle.reject = reject;
    }),
  );
  return settle;
}

/** Another tab's sign-in or logout, as this tab receives it. */
async function peerTab(message: { type: 'login' | 'logout'; sessionId: string | null }) {
  const unwire = wireSessionSync();
  const peer = otherTab();
  try {
    const epoch = useAuthStore.getState().sessionEpoch;
    peer.post(message);
    await waitFor(() => expect(useAuthStore.getState().sessionEpoch).not.toBe(epoch));
  } finally {
    peer.close();
    unwire();
  }
}

function setHash(hash: string) {
  window.history.replaceState({}, '', `/oauth/callback${hash}`);
}

describe('OAuthCallbackPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLogoutSession.mockResolvedValue(undefined);
    mockRevokeCurrentSession.mockResolvedValue(undefined);
    mockExchangeSignInCode.mockImplementation(async (_code, install) => install(exchanged));
    useAuthStore.getState().logout();
  });

  // The callback redirect carries only a one-time code; the session cookie
  // comes from exchanging it, inside the cross-tab cookie lock.
  it('exchanges the fragment code for the session', async () => {
    mockGetMe.mockResolvedValueOnce(userA);
    setHash('#code=one-time-code');
    let hashAtExchange: string | null = null;
    mockExchangeSignInCode.mockImplementationOnce(async (_code, install) => {
      hashAtExchange = window.location.hash;
      return install(exchanged);
    });

    render(<OAuthCallbackPage />);

    await waitFor(() => expect(useAuthStore.getState().user).toEqual(userA));
    expect(mockExchangeSignInCode).toHaveBeenCalledExactlyOnceWith('one-time-code', expect.any(Function));
    expect(hashAtExchange).toBe('');
    expect(useAuthStore.getState().token).toBe('access-1');
    expect(useAuthStore.getState().refreshToken).toBeNull();
    expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true });
  });

  it('installs the exchanged session before the exchange gives up the cookie lock', async () => {
    deferProfile();
    let tokenWhenInstallReturned: string | null = null;
    mockExchangeSignInCode.mockImplementationOnce(async (_code, install) => {
      const installed = install(exchanged);
      tokenWhenInstallReturned = useAuthStore.getState().token;
      return installed;
    });
    setHash('#code=one-time-code');

    render(<OAuthCallbackPage />);

    await waitFor(() => expect(mockGetMe).toHaveBeenCalled());
    expect(tokenWhenInstallReturned).toBe('access-1');
  });

  it('returns to /login without revoking when the exchange is refused', async () => {
    mockExchangeSignInCode.mockRejectedValueOnce(new ApiError('unauthorized', 401));
    setHash('#code=spent-code');

    render(<OAuthCallbackPage />);

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true }),
    );
    expect(mockGetMe).not.toHaveBeenCalled();
    expect(mockLogoutSession).not.toHaveBeenCalled();
    expect(mockRevokeCurrentSession).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBeNull();
  });

  it('still accepts the cookie-mode token fragment of an API that predates the exchange', async () => {
    mockGetMe.mockResolvedValueOnce(userA);
    setHash('#token=access-1&expires_in=900&auth_mode=cookie');

    render(<OAuthCallbackPage />);

    await waitFor(() => expect(useAuthStore.getState().user).toEqual(userA));
    expect(mockExchangeSignInCode).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe('access-1');
    expect(useAuthStore.getState().refreshToken).toBeNull();
  });

  it('does not sign in from a token fragment with neither a refresh token nor cookie mode', async () => {
    setHash('#token=access-1&expires_in=900');

    render(<OAuthCallbackPage />);

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true }),
    );
    expect(mockGetMe).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBeNull();
  });

  it.each([
    ['an in-app path', '/maps/1?tab=layers', '/maps/1?tab=layers'],
    ['a protocol-relative URL', '//evil.example/x', '/'],
    ['a backslash-relative URL', '/\\evil.example/x', '/'],
    ['an absolute URL', 'https://evil.example/x', '/'],
  ])('lands on %s only when it stays in the app', async (_label, stored, expected) => {
    mockGetMe.mockResolvedValueOnce(userA);
    sessionStorage.setItem('geolens-login-redirect', stored);
    setHash('#code=one-time-code');

    render(<OAuthCallbackPage />);

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith(expected, { replace: true }));
    expect(sessionStorage.getItem('geolens-login-redirect')).toBeNull();
  });

  it('still accepts a legacy fragment refresh token (cross-origin fallback)', async () => {
    const user = { id: '1', username: 'someone', roles: ['viewer'] } as UserResponse;
    mockGetMe.mockResolvedValueOnce(user);
    setHash('#token=access-1&refresh_token=legacy-r1&expires_in=900');

    render(<OAuthCallbackPage />);

    await waitFor(() => expect(useAuthStore.getState().user).toEqual(user));
    expect(useAuthStore.getState().refreshToken).toBe('legacy-r1');
  });

  // A profile that failed without a rejection says nothing against the
  // credential, so the user lands signed in and the app reloads the profile.
  it.each([
    ['a server error', new ApiError('server error', 500)],
    ['a timeout', new ApiError('request timed out', 0)],
    ['an unconfirmed 401', Object.assign(new ApiError('unauthorized', 401), { unconfirmed: true })],
  ])('keeps the session when getMe fails with %s', async (_label, profileError) => {
    mockGetMe.mockRejectedValueOnce(profileError);
    setHash('#code=one-time-code');

    render(<OAuthCallbackPage />);

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true }));
    expect(useAuthStore.getState().token).toBe('access-1');
    expect(mockLogoutSession).not.toHaveBeenCalled();
    expect(mockRevokeCurrentSession).not.toHaveBeenCalled();
  });

  // The exchange has installed the cookie by then, so a rejected credential
  // must be revoked: clearing the store cannot reach it.
  it('revokes only the issued session when getMe rejects the credential', async () => {
    mockGetMe.mockRejectedValueOnce(new ApiError('unauthorized', 403));
    setHash('#code=one-time-code');

    render(<OAuthCallbackPage />);

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true }),
    );
    expect(mockRevokeCurrentSession).toHaveBeenCalledExactlyOnceWith('access-1');
    expect(mockLogoutSession).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBeNull();
  });

  it('does not restore a session that was logged out while the profile loaded', async () => {
    const profile = deferProfile();
    setHash('#code=one-time-code');

    const view = render(<OAuthCallbackPage />);
    await waitFor(() => expect(mockGetMe).toHaveBeenCalled());
    view.unmount();
    useAuthStore.getState().logout();
    profile.resolve(userA);

    await waitFor(() => expect(mockRevokeCurrentSession).toHaveBeenCalledWith('access-1'));
    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
    expect(localStorage.getItem('geolens-auth')).not.toContain('access-1');
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('leaves a newer sign-in alone when the older one is rejected late', async () => {
    const profile = deferProfile();
    setHash('#code=one-time-code');

    render(<OAuthCallbackPage />);
    await waitFor(() => expect(mockGetMe).toHaveBeenCalled());
    useAuthStore.getState().logout();
    useAuthStore.getState().setAuth('access-b', null, 900, userB);
    profile.reject(new ApiError('unauthorized', 401));

    await waitFor(() => expect(mockRevokeCurrentSession).toHaveBeenCalled());
    expect(mockRevokeCurrentSession).not.toHaveBeenCalledWith('access-b');
    expect(mockLogoutSession).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe('access-b');
    expect(useAuthStore.getState().user).toEqual(userB);
  });

  it('does not overwrite a newer sign-in of the same user', async () => {
    const profile = deferProfile();
    setHash('#code=one-time-code');

    render(<OAuthCallbackPage />);
    await waitFor(() => expect(mockGetMe).toHaveBeenCalled());
    useAuthStore.getState().setAuth('access-2', null, 900, userA);
    profile.resolve(userA);

    await waitFor(() => expect(mockRevokeCurrentSession).toHaveBeenCalledWith('access-1'));
    expect(useAuthStore.getState().token).toBe('access-2');
  });

  it('does not restore a session another tab logged out', async () => {
    const profile = deferProfile();
    setHash('#code=one-time-code');

    render(<OAuthCallbackPage />);
    await waitFor(() => expect(mockGetMe).toHaveBeenCalled());
    await peerTab({ type: 'logout', sessionId: useAuthStore.getState().sessionId });
    profile.resolve(userA);

    await waitFor(() => expect(mockRevokeCurrentSession).toHaveBeenCalledWith('access-1'));
    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
  });

  it('does not overwrite a session another tab signed in', async () => {
    const profile = deferProfile();
    setHash('#code=one-time-code');

    render(<OAuthCallbackPage />);
    await waitFor(() => expect(mockGetMe).toHaveBeenCalled());
    window.localStorage.setItem(
      'geolens-auth',
      JSON.stringify({ state: { sessionId: 'peer-session', user: userB }, version: 2 }),
    );
    mockRefreshAccessToken.mockResolvedValueOnce({ access_token: 'access-b', refresh_token: null, expires_in: 900 });
    await peerTab({ type: 'login', sessionId: 'peer-session' });
    await waitFor(() => expect(useAuthStore.getState().token).toBe('access-b'));
    profile.resolve(userA);

    await waitFor(() => expect(mockRevokeCurrentSession).toHaveBeenCalledWith('access-1'));
    expect(useAuthStore.getState().token).toBe('access-b');
    expect(useAuthStore.getState().user).toEqual(userB);
  });

  it('keeps the session but does not navigate once the user has left the page', async () => {
    const profile = deferProfile();
    setHash('#code=one-time-code');

    const view = render(<OAuthCallbackPage />);
    await waitFor(() => expect(mockGetMe).toHaveBeenCalled());
    view.unmount();
    profile.resolve(userA);

    await waitFor(() => expect(useAuthStore.getState().user).toEqual(userA));
    expect(useAuthStore.getState().token).toBe('access-1');
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  // A fragment too incomplete to finish sign-in is no evidence the
  // credential was rejected, and revoking would end every other session.
  it('does not revoke when an incomplete fragment goes back to /login', async () => {
    setHash('#expires_in=900');

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
    setHash('#code=one-time-code');

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
