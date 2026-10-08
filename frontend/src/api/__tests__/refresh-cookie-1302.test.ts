import { awaitPendingLogout, exchangeSignInCode, login, logoutSession, refreshAccessToken, revokeCurrentSession } from '@/api/auth';
import { useAuthStore } from '@/stores/auth-store';
import { tryRefresh } from '@/api/client';
import { otherTab } from '@/test/broadcast-channel';

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

  it('revokes a captured family without attaching the current browser cookies', async () => {
    useAuthStore.setState({ token: 'new-login' });
    mockFetch.mockResolvedValueOnce({ ok: true, status: 204 } as Response);
    await revokeCurrentSession('old-family');
    expect(mockFetch).toHaveBeenCalledWith('/api/auth/logout/session/', expect.objectContaining({
      headers: { Authorization: 'Bearer old-family' }, credentials: 'omit', keepalive: true,
    }));
    expect(useAuthStore.getState().token).toBe('new-login');
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

  // fix(#2038): a 2xx whose body fails to parse leaves a live session behind a
  // failed sign-in, but /auth/logout/ revokes EVERY session of the user and a
  // malformed body is no evidence the credential was rejected.
  it('does not revoke every session when a successful login response fails to parse', async () => {
    document.cookie = 'geolens_csrf=csrf-abc; path=/';
    useAuthStore.setState({ token: null });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.reject(new SyntaxError('Unexpected end of JSON input')),
      headers: new Headers(),
    } as Response);

    await expect(login('someone', 'secret')).rejects.toThrow(SyntaxError);

    expect(
      mockFetch.mock.calls.find(([url]) => (url as string) === '/api/auth/logout/'),
    ).toBeUndefined();
  });

  // fix(#1446): logout revokes EVERY refresh token for the user and deletes
  // the cookies, so a request that lands after a fresh login revokes the new
  // session's row, and a delayed response erases its cookie. Login waits.
  it('does not let a new login overtake a logout still in flight', async () => {
    const order: string[] = [];
    let finishLogout: () => void = () => {};
    mockFetch.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishLogout = () => {
            order.push('logout');
            resolve({
              ok: true,
              status: 204,
              statusText: 'No Content',
              json: () => Promise.reject(new Error('no body')),
              headers: new Headers(),
            } as Response);
          };
        }),
    );
    mockFetch.mockImplementationOnce(() => {
      order.push('login');
      return Promise.resolve(
        jsonResponse({ access_token: 'a1', refresh_token: null, expires_in: 900 }),
      );
    });

    useAuthStore.setState({ token: 'old-access' });
    void logoutSession().catch(() => {});
    const loginPromise = login('someone', 'secret');

    // Login must still be parked on the pending revocation.
    await Promise.resolve();
    expect(order).toEqual([]);

    finishLogout();
    await loginPromise;

    expect(order).toEqual(['logout', 'login']);
  });

  // fix(#1446): two teardown paths can each dispatch a revocation (a terminal
  // getMe 401 and a login catch, say). A single last-write-wins slot let
  // awaitPendingLogout return once the LATER request settled, while the
  // earlier one was still holding the user lock server-side — free to revoke
  // rows a new sign-in just created. Every outstanding revocation must drain.
  it('waits for every concurrent logout, not just the latest', async () => {
    useAuthStore.setState({ token: 'live-access' });
    const done204 = () =>
      ({
        ok: true,
        status: 204,
        statusText: 'No Content',
        json: () => Promise.reject(new Error('no body')),
        headers: new Headers(),
      }) as Response;
    let resolveSlow: (r: Response) => void = () => {};
    mockFetch.mockImplementationOnce(
      () => new Promise<Response>((resolve) => (resolveSlow = resolve)),
    );
    mockFetch.mockImplementationOnce(() => Promise.resolve(done204()));

    const slowLogout = logoutSession();
    const fastLogout = logoutSession();
    await fastLogout;

    let drained = false;
    const drain = awaitPendingLogout().then(() => {
      drained = true;
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(drained).toBe(false);

    resolveSlow(done204());
    await slowLogout;
    await drain;
    expect(drained).toBe(true);
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

  // Tabs share one cookie jar, so a refresh another tab already sent must not
  // land its rotated cookie after this tab's sign-in. Web Locks hold the login
  // until that refresh has finished.
  it('holds a sign-in until a refresh holding the cookie lock has finished', async () => {
    let held: Promise<unknown> = Promise.resolve();
    const locks = {
      request: (_name: string, _options: unknown, callback: () => Promise<unknown>) => {
        const run = held.then(callback);
        held = run.catch(() => {});
        return run;
      },
    };
    Object.defineProperty(navigator, 'locks', { value: locks, configurable: true });
    try {
      let finishRefresh!: (r: Response) => void;
      mockFetch.mockImplementationOnce(() => new Promise<Response>((resolve) => { finishRefresh = resolve; }));
      const refresh = refreshAccessToken(null);
      await vi.waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));

      mockFetch.mockResolvedValueOnce(
        jsonResponse({ access_token: 'a1', refresh_token: null, expires_in: 900 }),
      );
      const signIn = login('someone', 'secret');
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(mockFetch).toHaveBeenCalledTimes(1);

      finishRefresh(jsonResponse({ access_token: 'r1', refresh_token: null, expires_in: 900 }));
      await refresh;
      await signIn;
      expect(mockFetch).toHaveBeenCalledTimes(2);
    } finally {
      Reflect.deleteProperty(navigator, 'locks');
    }
  });

  // An SSO sign-in sets its cookie through this exchange, so the same lock
  // keeps a refresh another tab already sent from landing after it.
  it('holds an SSO code exchange until a refresh holding the cookie lock has finished', async () => {
    let held: Promise<unknown> = Promise.resolve();
    const lockNames: string[] = [];
    let lockHeld = false;
    const locks = {
      request: (name: string, _options: unknown, callback: () => Promise<unknown>) => {
        lockNames.push(name);
        const run = held.then(async () => {
          lockHeld = true;
          try {
            return await callback();
          } finally {
            lockHeld = false;
          }
        });
        held = run.catch(() => {});
        return run;
      },
    };
    Object.defineProperty(navigator, 'locks', { value: locks, configurable: true });
    try {
      let finishRefresh!: (r: Response) => void;
      mockFetch.mockImplementationOnce(() => new Promise<Response>((resolve) => { finishRefresh = resolve; }));
      const refresh = refreshAccessToken(null);
      await vi.waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));

      mockFetch.mockResolvedValueOnce(
        jsonResponse({ access_token: 'sso-1', refresh_token: null, expires_in: 900 }),
      );
      let installedUnderLock: boolean | null = null;
      const exchange = exchangeSignInCode('one-time-code', (session) => {
        installedUnderLock = lockHeld;
        return session;
      });
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(mockFetch).toHaveBeenCalledTimes(1);

      finishRefresh(jsonResponse({ access_token: 'r1', refresh_token: null, expires_in: 900 }));
      await refresh;
      await expect(exchange).resolves.toMatchObject({ access_token: 'sso-1' });
      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(new Set(lockNames).size).toBe(1);
      expect(installedUnderLock).toBe(true);
      const [url, init] = mockFetch.mock.calls[1] as [string, RequestInit];
      expect(url).toBe('/api/auth/oauth/exchange/');
      expect(init).toMatchObject({ method: 'POST', credentials: 'same-origin' });
      expect(init.headers).toMatchObject({ 'X-GeoLens-Auth-Mode': 'cookie' });
      expect(JSON.parse(init.body as string)).toEqual({ code: 'one-time-code' });
    } finally {
      Reflect.deleteProperty(navigator, 'locks');
    }
  });

  // A 2xx exchange has already consumed the code and set the cookies, so a
  // body this tab cannot use must not leave that session behind.
  it('revokes the cookie session before giving up on an unreadable exchange body', async () => {
    let lockHeld = false;
    const locks = {
      request: async (_name: string, _options: unknown, callback: () => Promise<unknown>) => {
        lockHeld = true;
        try {
          return await callback();
        } finally {
          lockHeld = false;
        }
      },
    };
    Object.defineProperty(navigator, 'locks', { value: locks, configurable: true });
    try {
      document.cookie = 'geolens_csrf=csrf-new; path=/';
      useAuthStore.setState({ token: 'older-access' });
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.reject(new SyntaxError('Unexpected end of JSON input')),
      } as Response);
      let finishRevoke!: (r: Response) => void;
      let revokedUnderLock: boolean | null = null;
      mockFetch.mockImplementationOnce(() => {
        revokedUnderLock = lockHeld;
        return new Promise<Response>((resolve) => { finishRevoke = resolve; });
      });
      const install = vi.fn();
      let settled = false;
      const exchange = exchangeSignInCode('one-time-code', install).finally(() => { settled = true; });

      await vi.waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(settled).toBe(false);
      finishRevoke({ ok: true, status: 204 } as Response);

      await expect(exchange).rejects.toThrow(SyntaxError);
      expect(install).not.toHaveBeenCalled();
      expect(revokedUnderLock).toBe(true);
      const [url, init] = mockFetch.mock.calls[1] as [string, RequestInit];
      expect(url).toBe('/api/auth/logout/session/');
      expect(init).toMatchObject({ method: 'POST', credentials: 'same-origin' });
      expect(init.headers).toMatchObject({ 'X-CSRF-Token': 'csrf-new' });
      expect(init.headers).not.toHaveProperty('Authorization');
      expect(useAuthStore.getState().token).toBeNull();
    } finally {
      Reflect.deleteProperty(navigator, 'locks');
    }
  });

  it('rejects with the status when the exchange is refused', async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 401, json: () => Promise.resolve({}) } as Response);
    const install = vi.fn();
    await expect(exchangeSignInCode('spent-code', install)).rejects.toMatchObject({ status: 401 });
    expect(install).not.toHaveBeenCalled();
  });

  it('reads the CSRF cookie only once it holds the cookie lock', async () => {
    let held: Promise<unknown> = Promise.resolve();
    const locks = {
      request: (_name: string, _options: unknown, callback: () => Promise<unknown>) => {
        const run = held.then(callback);
        held = run.catch(() => {});
        return run;
      },
    };
    Object.defineProperty(navigator, 'locks', { value: locks, configurable: true });
    try {
      document.cookie = 'geolens_csrf=csrf-before; path=/';
      let finishFirst!: (r: Response) => void;
      mockFetch.mockImplementationOnce(() => new Promise<Response>((resolve) => { finishFirst = resolve; }));
      const first = refreshAccessToken(null);
      await vi.waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));

      mockFetch.mockResolvedValueOnce(
        jsonResponse({ access_token: 'r2', refresh_token: null, expires_in: 900 }),
      );
      const second = refreshAccessToken(null);
      // The first refresh rotates the CSRF cookie before the second is sent.
      document.cookie = 'geolens_csrf=csrf-after; path=/';
      finishFirst(jsonResponse({ access_token: 'r1', refresh_token: null, expires_in: 900 }));
      await first;
      await second;

      expect(lastInit().headers).toMatchObject({ 'X-CSRF-Token': 'csrf-after' });
    } finally {
      Reflect.deleteProperty(navigator, 'locks');
    }
  });

  // A recovery that outlived its render budget can still be running when the
  // user signs in, and its rotated cookie would replace the new session's.
  it('abandons an in-flight refresh before signing in', async () => {
    useAuthStore.setState({ token: 'old-access', refreshToken: null, sessionId: 'old-session' });
    let refreshSignal: AbortSignal | undefined;
    mockFetch.mockImplementationOnce((_url: string, init: RequestInit) => {
      refreshSignal = init.signal ?? undefined;
      return new Promise(() => {});
    });
    void tryRefresh();
    await vi.waitFor(() => expect(refreshSignal).toBeDefined());
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ access_token: 'a1', refresh_token: null, expires_in: 900 }),
    );

    await login('someone', 'secret');

    expect(refreshSignal?.aborted).toBe(true);
    useAuthStore.setState({ token: null, sessionId: null });
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

  // sessionEpoch is per-tab, so another tab's logout reaches this one as a
  // message. Without it, this tab's in-flight refresh writes its rotated token
  // back and keeps a session the user ended.
  it('discards rotated tokens when another tab logged out', async () => {
    let resolveRefresh: (value: unknown) => void = () => {};
    let capturedSignal: AbortSignal | undefined;
    vi.doMock('@/api/auth', () => ({
      refreshAccessToken: vi.fn((_token: string | null, signal?: AbortSignal) => {
        capturedSignal = signal;
        return new Promise((resolve) => { resolveRefresh = resolve; });
      }),
      logoutSession: vi.fn(() => Promise.resolve()),
    }));

    const { tryRefresh } = await import('@/api/client');
    const { useAuthStore: store } = await import('@/stores/auth-store');
    const { wireSessionSync } = await import('@/lib/session-sync');
    const unwire = wireSessionSync();
    const peer = otherTab();

    try {
      store.getState().setAuth('live-access', null, 60, null);
      const pending = tryRefresh();

      peer.post({ type: 'logout', sessionId: store.getState().sessionId });
      await vi.waitFor(() => expect(store.getState().token).toBeNull());

      // The request is abandoned too, not just its store write: a response the
      // browser never processes cannot apply a stale Set-Cookie over a cookie
      // a later login issued.
      expect(capturedSignal?.aborted).toBe(true);

      resolveRefresh({ access_token: 'rotated', refresh_token: null, expires_in: 900 });
      await pending;

      expect(store.getState().token).toBeNull();
      expect(window.localStorage.getItem('geolens-auth') ?? '').not.toContain('rotated');
    } finally {
      peer.close();
      unwire();
    }
  });

  // fix(#1446): the epoch guard stops the store write, but the browser applies
  // a response's Set-Cookie regardless. If the user signs in again before a
  // stale refresh response lands, that cookie would replace the new session's
  // credential with the one the logout revoked. Aborting means the response is
  // never processed at all.
  it('aborts an in-flight refresh so its Set-Cookie can never land', async () => {
    let capturedSignal: AbortSignal | undefined;
    vi.doMock('@/api/auth', () => ({
      refreshAccessToken: vi.fn((_token: string | null, signal?: AbortSignal) => {
        capturedSignal = signal;
        return new Promise(() => {});
      }),
      logoutSession: vi.fn(() => Promise.resolve()),
    }));

    const { tryRefresh, abortInflightRefresh } = await import('@/api/client');
    const { useAuthStore: store } = await import('@/stores/auth-store');

    store.setState({ token: 'live-access', refreshToken: null, expiresAt: Date.now() + 60_000 });
    void tryRefresh();

    expect(capturedSignal?.aborted).toBe(false);
    abortInflightRefresh();
    expect(capturedSignal?.aborted).toBe(true);
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
    // Pre-GH-1302 shape: rehydrated into memory, kept until spent.
    useAuthStore.setState({ refreshToken: 'legacy-refresh-token' });
    useAuthStore.getState().setTokens('access-2', null, 900);

    const raw = window.localStorage.getItem('geolens-auth');
    expect(raw).not.toContain('legacy-refresh-token');
    expect(useAuthStore.getState().refreshToken).toBeNull();
  });

  it('never writes an unspent legacy refresh token to storage', () => {
    useAuthStore.setState({ token: 'access-1', refreshToken: 'legacy-refresh-token' });
    useAuthStore.setState({ expiresAt: Date.now() + 900_000 });

    expect(window.localStorage.getItem('geolens-auth') ?? '').not.toContain('legacy-refresh-token');
    expect(useAuthStore.getState().refreshToken).toBe('legacy-refresh-token');
  });
});
