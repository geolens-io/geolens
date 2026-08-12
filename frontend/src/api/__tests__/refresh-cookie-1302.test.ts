import { login, logoutSession, refreshAccessToken } from '@/api/auth';
import { useAuthStore } from '@/stores/auth-store';

// fix(#1302): AC — after login the persisted `geolens-auth` value holds no
// refresh token, and the refresh call carries the cookie plus its double-submit
// CSRF header instead of a body token.

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function jsonResponse(data: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    json: () => Promise.resolve(data),
    headers: new Headers(),
  } as Response;
}

function lastInit(): RequestInit {
  return mockFetch.mock.calls[mockFetch.mock.calls.length - 1][1] as RequestInit;
}

describe('browser refresh transport', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.cookie = 'geolens_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
  });

  it('sends no body when the credential is the cookie', async () => {
    document.cookie = 'geolens_csrf=csrf-abc; path=/';
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ access_token: 'a1', refresh_token: null, expires_in: 900 }),
    );

    const result = await refreshAccessToken(null);

    expect(result.refresh_token).toBeNull();
    const init = lastInit();
    expect(init.body).toBeUndefined();
    expect(init.credentials).toBe('same-origin');
    expect(init.headers).toMatchObject({
      'X-GeoLens-Auth-Mode': 'cookie',
      'X-CSRF-Token': 'csrf-abc',
    });
  });

  it('sends a legacy body token once, under the cookie header, to migrate a session', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ access_token: 'a1', refresh_token: null, expires_in: 900 }),
    );

    await refreshAccessToken('legacy-refresh-token');

    const init = lastInit();
    expect(JSON.parse(init.body as string)).toEqual({
      refresh_token: 'legacy-refresh-token',
    });
    expect(init.headers).toMatchObject({ 'X-GeoLens-Auth-Mode': 'cookie' });
  });

  // fix(#1446): the request must be fully formed before the caller tears down
  // local state. Routing it through apiFetch would await a proactive refresh
  // first when the token is near expiry, and a caller that stopped waiting
  // during that window got a logout POST with no Authorization header — while
  // the refresh had already installed a rotated cookie.
  it('logout captures the bearer token synchronously and sends it', async () => {
    useAuthStore.setState({ token: 'live-access', expiresAt: Date.now() + 1_000 });
    mockFetch.mockImplementationOnce(() => {
      // Mid-flight teardown must not affect the request already dispatched.
      useAuthStore.getState().logout();
      return Promise.resolve({
        ok: true,
        status: 204,
        statusText: 'No Content',
        json: () => Promise.reject(new Error('no body')),
        headers: new Headers(),
      } as Response);
    });

    await logoutSession();

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/auth/logout/');
    expect(init.method).toBe('POST');
    expect(init.headers).toMatchObject({ Authorization: 'Bearer live-access' });
    expect(init.credentials).toBe('same-origin');
    // fix(#1446): survives an immediate close/navigate after clicking Logout.
    expect(init.keepalive).toBe(true);
    // Exactly one request: no proactive-refresh detour.
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  // fix(#1446): when the access token has already expired there is no bearer
  // token to send, and the refresh cookie authenticates the call server-side.
  // That path is CSRF-protected, so the double-submit token must ride along.
  it('logout carries the CSRF token so the cookie can authenticate it', async () => {
    document.cookie = 'geolens_csrf=csrf-abc; path=/';
    useAuthStore.setState({ token: null });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      statusText: 'No Content',
      json: () => Promise.reject(new Error('no body')),
      headers: new Headers(),
    } as Response);

    await logoutSession();

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toEqual({
      'X-GeoLens-Auth-Mode': 'cookie',
      'X-CSRF-Token': 'csrf-abc',
    });
  });

  it('opts login into the cookie flow', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ access_token: 'a1', refresh_token: null, expires_in: 900 }),
    );

    await login('someone', 'secret');

    const init = lastInit();
    expect(init.credentials).toBe('same-origin');
    expect(init.headers).toMatchObject({ 'X-GeoLens-Auth-Mode': 'cookie' });
  });
});

// fix(#1446): logout races its wait against a short timer, so a slow refresh
// can still be running when the store is torn down. If that refresh then wrote
// its rotated tokens back, the browser would be fully signed in again while
// sitting on /login.
describe('late refresh after logout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    window.localStorage.clear();
  });

  it('discards rotated tokens when a logout landed mid-flight', async () => {
    let resolveRefresh: (value: unknown) => void = () => {};
    vi.doMock('@/api/auth', () => ({
      refreshAccessToken: vi.fn(
        () => new Promise((resolve) => { resolveRefresh = resolve; }),
      ),
    }));

    const { tryRefresh } = await import('@/api/client');
    const { useAuthStore: store } = await import('@/stores/auth-store');

    store.setState({ token: 'live-access', refreshToken: null, expiresAt: Date.now() + 60_000 });
    const pending = tryRefresh();

    // The user logs out while the refresh is still in flight.
    store.getState().logout();

    resolveRefresh({ access_token: 'rotated', refresh_token: null, expires_in: 900 });
    expect(await pending).toBe(false);

    expect(store.getState().token).toBeNull();
    expect(window.localStorage.getItem('geolens-auth') ?? '').not.toContain('rotated');
  });

  // fix(#1446): sessionEpoch is per-tab, so a logout in ANOTHER tab cannot
  // reach it through the persisted blob. The storage listener bumps it on the
  // present->absent transition; without that, this tab's in-flight refresh
  // writes its rotated tokens back and re-persists the session for every tab.
  it('discards rotated tokens when another tab logged out', async () => {
    let resolveRefresh: (value: unknown) => void = () => {};
    vi.doMock('@/api/auth', () => ({
      refreshAccessToken: vi.fn(
        () => new Promise((resolve) => { resolveRefresh = resolve; }),
      ),
    }));

    const { tryRefresh } = await import('@/api/client');
    const { useAuthStore: store } = await import('@/stores/auth-store');

    store.setState({ token: 'live-access', refreshToken: null, expiresAt: Date.now() + 60_000 });
    const pending = tryRefresh();

    // Tab A logged out: it wrote a token-less blob, and this tab's `storage`
    // listener rehydrates from it.
    window.localStorage.setItem(
      'geolens-auth',
      JSON.stringify({ state: { token: null, expiresAt: null, user: null }, version: 1 }),
    );
    window.dispatchEvent(new StorageEvent('storage', { key: 'geolens-auth' }));
    await vi.waitFor(() => expect(store.getState().token).toBeNull());

    resolveRefresh({ access_token: 'rotated', refresh_token: null, expires_in: 900 });
    await pending;

    expect(store.getState().token).toBeNull();
    expect(window.localStorage.getItem('geolens-auth') ?? '').not.toContain('rotated');
  });

  it('still applies rotated tokens when no logout intervened', async () => {
    let resolveRefresh: (value: unknown) => void = () => {};
    vi.doMock('@/api/auth', () => ({
      refreshAccessToken: vi.fn(
        () => new Promise((resolve) => { resolveRefresh = resolve; }),
      ),
    }));

    const { tryRefresh } = await import('@/api/client');
    const { useAuthStore: store } = await import('@/stores/auth-store');

    store.setState({ token: 'live-access', refreshToken: null, expiresAt: Date.now() + 60_000 });
    const pending = tryRefresh();

    resolveRefresh({ access_token: 'rotated', refresh_token: null, expires_in: 900 });
    expect(await pending).toBe(true);

    expect(store.getState().token).toBe('rotated');
  });
});

describe('persisted auth state', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('writes no refresh token to localStorage', () => {
    useAuthStore.getState().setAuth('access-1', null, 900, {
      id: 'u1',
      username: 'someone',
      roles: ['admin'],
    } as never);

    const raw = window.localStorage.getItem('geolens-auth');
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw as string).state).not.toHaveProperty('refreshToken');
    expect(raw).not.toContain('refreshToken');
  });

  it('drops a legacy refresh token from storage once the migrating refresh spends it', () => {
    // Pre-GH-1302 shape: rehydrated into memory, but never written back.
    useAuthStore.setState({ refreshToken: 'legacy-refresh-token' });
    useAuthStore.getState().setTokens('access-2', null, 900);

    const raw = window.localStorage.getItem('geolens-auth');
    expect(raw).not.toContain('legacy-refresh-token');
    expect(useAuthStore.getState().refreshToken).toBeNull();
  });
});
