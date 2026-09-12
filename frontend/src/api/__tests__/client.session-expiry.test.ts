import { abortInflightRefresh, apiFetch, ApiError, onSessionExpired } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';
import { refreshAccessToken, logoutSession, revokeCurrentSession } from '@/api/auth';
import type { TokenResponse } from '@/types/api';

// fix(#628): the fetch core must treat "401 + the follow-up refresh is also
// dead" as a single session-death event: clear the persisted auth state and
// invoke the registered handler exactly ONCE, no matter how many in-flight
// requests fail together. Anonymous 401s (no session to expire) must never
// raise the handler.

vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(),
  revokeCurrentSession: vi.fn(() => Promise.resolve()),
  logoutSession: vi.fn(() => Promise.resolve()),
}));

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function errorResponse(status: number): Response {
  return {
    ok: false,
    status,
    statusText: 'Unauthorized',
    json: () => Promise.reject(new Error('not json')),
    headers: new Headers(),
  } as Response;
}

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'OK',
    json: () => Promise.resolve(data),
    headers: new Headers(),
  } as Response;
}

// fix(#1302): the latch is keyed on the ACCESS token now that the refresh token
// is an httpOnly cookie JS cannot read. Access tokens rotate on every login and
// every refresh (each is a fresh JWT with its own jti), so each session's value
// is unique — which is the property the latch needs.
let sessionCounter = 0;
function signIn() {
  sessionCounter += 1;
  useAuthStore.setState({
    token: `stale-access-token-${sessionCounter}`,
    refreshToken: `dead-refresh-token-${sessionCounter}`,
    // Far enough out that the proactive-refresh branch does not fire.
    expiresAt: Date.now() + 120_000,
  });
}

describe('session-expiry notification (fix #628)', () => {
  let handler: ReturnType<typeof vi.fn<() => void>>;
  let unregister: () => void;

  beforeEach(() => {
    vi.clearAllMocks();
    handler = vi.fn<() => void>();
    unregister = onSessionExpired(handler);
  });

  afterEach(() => {
    unregister();
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
    // fix(#2038): the transient refresh back-off is module state; end signed out.
    abortInflightRefresh();
  });

  // fix(#2038): a rate-limited refresh in one client used to revoke every
  // session of the user, so every other client then revoked in turn.
  it('keeps the session and revokes nothing when the refresh is rate-limited', async () => {
    signIn();
    const live = useAuthStore.getState().token;
    mockFetch.mockResolvedValue(errorResponse(401));
    vi.mocked(refreshAccessToken).mockRejectedValue(new ApiError('rate limited', 429));

    // fix(#2038): flagged unconfirmed so a sign-in catch downstream cannot read
    // it as a rejected credential and revoke every session.
    await expect(apiFetch('/a/')).rejects.toMatchObject({ status: 401, unconfirmed: true });

    expect(logoutSession).not.toHaveBeenCalled();
    expect(handler).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe(live);
  });

  // fix(#2038): refreshAccessToken issues a bare fetch, so a real offline
  // failure arrives as a TypeError, not an ApiError.
  it('keeps the session and revokes nothing when the refresh cannot reach the server', async () => {
    signIn();
    const live = useAuthStore.getState().token;
    mockFetch.mockResolvedValue(errorResponse(401));
    vi.mocked(refreshAccessToken).mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(apiFetch('/a/')).rejects.toMatchObject({ status: 401 });

    expect(logoutSession).not.toHaveBeenCalled();
    expect(handler).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe(live);
  });

  // fix(#2038): a rejected refresh row has nothing left to revoke server-side.
  it('clears local state without a server revocation when the refresh is rejected', async () => {
    signIn();
    mockFetch.mockResolvedValue(errorResponse(401));
    vi.mocked(refreshAccessToken).mockRejectedValue(new ApiError('unauthorized', 401));

    const err = await apiFetch('/a/').catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 401 });
    expect((err as ApiError).unconfirmed).toBeUndefined();

    expect(logoutSession).not.toHaveBeenCalled();
    expect(handler).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().token).toBeNull();
  });

  // fix(#2038): 403 on refresh is a rejection too, and ends the session the
  // same way 401 does.
  it('clears local state and prompts when the refresh is answered 403', async () => {
    signIn();
    mockFetch.mockResolvedValue(errorResponse(401));
    vi.mocked(refreshAccessToken).mockRejectedValue(new ApiError('forbidden', 403));

    await expect(apiFetch('/a/')).rejects.toMatchObject({ status: 401 });

    expect(logoutSession).not.toHaveBeenCalled();
    expect(handler).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().token).toBeNull();
  });

  it('revokes the freshly rotated family when the retry still rejects it', async () => {
    signIn();
    mockFetch.mockResolvedValue(errorResponse(401));
    vi.mocked(refreshAccessToken).mockResolvedValue({ access_token: 'fresh-family-jwt', refresh_token: null, expires_in: 900, token_type: 'bearer' });
    await expect(apiFetch('/a/')).rejects.toMatchObject({ status: 401 });
    expect(revokeCurrentSession).toHaveBeenCalledWith('fresh-family-jwt');
    expect(logoutSession).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBeNull();
  });

  it('revokes the rejected retry family while preserving a login that arrived during the retry', async () => {
    signIn();
    mockFetch.mockResolvedValueOnce(errorResponse(401)).mockImplementationOnce(async () => {
      useAuthStore.getState().logout();
      useAuthStore.setState({ token: 'newer-login', expiresAt: Date.now() + 120_000 });
      return errorResponse(401);
    });
    vi.mocked(refreshAccessToken).mockResolvedValue({ access_token: 'retried-family-jwt', refresh_token: null, expires_in: 900, token_type: 'bearer' });
    await expect(apiFetch('/a/')).rejects.toMatchObject({ status: 401 });
    expect(revokeCurrentSession).toHaveBeenCalledWith('retried-family-jwt');
    expect(logoutSession).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe('newer-login');
    expect(handler).not.toHaveBeenCalled();
  });

  it('revokes a discarded rotation after an epoch change while preserving the new login', async () => {
    signIn();
    mockFetch.mockResolvedValue(errorResponse(401));
    vi.mocked(refreshAccessToken).mockImplementation(async () => {
      useAuthStore.getState().logout();
      useAuthStore.setState({ token: 'new-login', expiresAt: Date.now() + 120_000 });
      return { access_token: 'discarded-family-jwt', refresh_token: null, expires_in: 900, token_type: 'bearer' };
    });
    await expect(apiFetch('/a/')).rejects.toMatchObject({ status: 401 });
    expect(revokeCurrentSession).toHaveBeenCalledWith('discarded-family-jwt');
    expect(logoutSession).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe('new-login');
    expect(handler).not.toHaveBeenCalled();
  });

  it('401 + dead refresh: clears the store and invokes the handler exactly once across N concurrent requests', async () => {
    signIn();
    mockFetch.mockResolvedValue(errorResponse(401));
    vi.mocked(refreshAccessToken).mockRejectedValue(new ApiError('unauthorized', 401));

    const results = await Promise.allSettled([
      apiFetch('/a/'),
      apiFetch('/b/'),
      apiFetch('/c/'),
      apiFetch('/d/'),
      apiFetch('/e/'),
    ]);

    for (const r of results) {
      expect(r.status).toBe('rejected');
      expect((r as PromiseRejectedResult).reason).toBeInstanceOf(ApiError);
      expect(((r as PromiseRejectedResult).reason as ApiError).status).toBe(401);
    }
    expect(handler).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().refreshToken).toBeNull();
  });

  it('does not invoke the handler for an anonymous 401 (no session to expire)', async () => {
    mockFetch.mockResolvedValue(errorResponse(401));

    await expect(apiFetch('/private/')).rejects.toMatchObject({ status: 401 });

    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(handler).not.toHaveBeenCalled();
  });

  it('does not invoke the handler when the refresh succeeds and the retry passes', async () => {
    signIn();
    mockFetch
      .mockResolvedValueOnce(errorResponse(401))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    vi.mocked(refreshAccessToken).mockResolvedValue({
      access_token: 'fresh',
      refresh_token: 'fresh-refresh',
      expires_in: 900,
      token_type: 'bearer',
    });

    await expect(apiFetch('/a/')).resolves.toEqual({ ok: true });
    expect(handler).not.toHaveBeenCalled();
  });

  // fix(#1862 review P2): before the fix, tryRefresh reported failure here
  // regardless of what the store actually held, so this retried with a dead
  // token, got 401 again, and notified — logging out (and revoking) the
  // session the peer tab had just refreshed.
  it('does not invoke the handler when a peer tab rotates the token while this refresh fails', async () => {
    signIn();

    let rejectRefresh: (err: unknown) => void = () => {};
    vi.mocked(refreshAccessToken).mockImplementation(
      () =>
        new Promise<TokenResponse>((_resolve, reject) => {
          rejectRefresh = reject;
        }),
    );

    mockFetch
      .mockResolvedValueOnce(errorResponse(401))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    const pending = apiFetch('/a/');

    // Yield until the fetch mock's own resolution, the 401 branch, and the
    // tryRefresh call all clear their microtask hops and refreshAccessToken
    // is actually invoked (same pattern as the SP-09 concurrent-dedup test).
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    // auth-store.ts's cross-tab `storage` listener rehydrating a peer tab's
    // successful refresh into this tab's store while this attempt is still
    // in flight.
    useAuthStore.setState({ token: 'peer-rotated-token' });
    rejectRefresh(new ApiError('network error', 0));

    await expect(pending).resolves.toEqual({ ok: true });
    expect(handler).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe('peer-rotated-token');
  });

  it('notifies once per dead session, and again for the next dead session', async () => {
    signIn();
    mockFetch.mockResolvedValue(errorResponse(401));
    vi.mocked(refreshAccessToken).mockRejectedValue(new ApiError('unauthorized', 401));

    await expect(apiFetch('/a/')).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);

    // Signed out now — a further 401 is anonymous and must not re-notify.
    await expect(apiFetch('/b/')).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);

    // A fresh sign-in mints a NEW (rotated) access token; its death is a new event.
    signIn();
    await expect(apiFetch('/c/')).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(2);
  });
});
