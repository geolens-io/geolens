import { apiFetch, ApiError, onSessionExpired } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';
import { refreshAccessToken } from '@/api/auth';

// fix(#628): the fetch core must treat "401 + the follow-up refresh is also
// dead" as a single session-death event: clear the persisted auth state and
// invoke the registered handler exactly ONCE, no matter how many in-flight
// requests fail together. Anonymous 401s (no session to expire) must never
// raise the handler.

vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(),
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

// Refresh tokens rotate, so every session's token value is unique — the
// notification latch is keyed on it.
let sessionCounter = 0;
function signIn() {
  sessionCounter += 1;
  useAuthStore.setState({
    token: 'stale-access-token',
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

  it('notifies once per dead session, and again for the next dead session', async () => {
    signIn();
    mockFetch.mockResolvedValue(errorResponse(401));
    vi.mocked(refreshAccessToken).mockRejectedValue(new ApiError('unauthorized', 401));

    await expect(apiFetch('/a/')).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);

    // Signed out now — a further 401 is anonymous and must not re-notify.
    await expect(apiFetch('/b/')).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);

    // A fresh sign-in mints a NEW (rotated) refresh token; its death is a new event.
    signIn();
    await expect(apiFetch('/c/')).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(2);
  });
});
