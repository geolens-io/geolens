import { login, refreshAccessToken } from '@/api/auth';
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
