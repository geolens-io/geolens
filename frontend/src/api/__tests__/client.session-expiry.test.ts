import { apiFetch, ApiError, onSessionExpired } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';
import { refreshAccessToken, logoutSession } from '@/api/auth';
import type { TokenResponse } from '@/types/api';

// fix(#628): the fetch core must treat "401 + the follow-up refresh is also
// dead" as a single session-death event: clear the persisted auth state and
// invoke the registered handler exactly ONCE, no matter how many in-flight
// requests fail together. Anonymous 401s (no session to expire) must never
// raise the handler.

vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(),
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
  });

  // fix(#1446): the refresh may have failed transiently (429, 5xx, dropped
  // connection), leaving a perfectly valid httpOnly refresh cookie behind a UI
  // that says "signed out". Clearing the store cannot reach that credential,
  // so revocation is dispatched on the way out.
  it('revokes server-side when the refresh failed transiently rather than definitively', async () => {
    signIn();
    mockFetch.mockResolvedValue(errorResponse(401));
    vi.mocked(refreshAccessToken).mockRejectedValue(new ApiError('rate limited', 429));

    await expect(apiFetch('/a/')).rejects.toMatchObject({ status: 401 });

    expect(logoutSession).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().token).toBeNull();
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
