import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';

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

describe('useAuthStore', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
  });

  it('setAuth stores token, refreshToken, expiresAt, and user', () => {
    const user = mockUser();
    const before = Date.now();
    useAuthStore.getState().setAuth('token-123', 'refresh-456', 900, user);
    const after = Date.now();

    expect(useAuthStore.getState().token).toBe('token-123');
    expect(useAuthStore.getState().refreshToken).toBe('refresh-456');
    // expiresAt should be roughly (now + 900s). Allow for execution time
    // between capturing `before`/`after` and the store call.
    const expiresAt = useAuthStore.getState().expiresAt!;
    expect(expiresAt).toBeGreaterThanOrEqual(before + 900_000 - 1000);
    expect(expiresAt).toBeLessThanOrEqual(after + 900_000 + 1000);
    expect(useAuthStore.getState().user).toEqual(user);
  });

  it('starts a new session generation on every sign-in and logout, not on refresh', () => {
    const user = mockUser();
    useAuthStore.getState().setAuth('token-a', null, 900, user);
    const signedIn = useAuthStore.getState();

    useAuthStore.getState().setTokens('token-a2', null, 900);
    expect(useAuthStore.getState().sessionEpoch).toBe(signedIn.sessionEpoch);
    expect(useAuthStore.getState().sessionId).toBe(signedIn.sessionId);

    useAuthStore.getState().setAuth('token-b', null, 900, user);
    const again = useAuthStore.getState();
    expect(again.sessionEpoch).toBe(signedIn.sessionEpoch + 1);
    expect(again.sessionId).not.toBe(signedIn.sessionId);

    useAuthStore.getState().logout();
    expect(useAuthStore.getState().sessionEpoch).toBe(again.sessionEpoch + 1);
    expect(useAuthStore.getState().sessionId).toBeNull();
  });

  it('setTokens updates tokens without changing user', () => {
    const user = mockUser();
    useAuthStore.setState({ token: 'old', refreshToken: 'old-refresh', expiresAt: 1, user });
    useAuthStore.getState().setTokens('new-token', 'new-refresh', 900);

    expect(useAuthStore.getState().token).toBe('new-token');
    expect(useAuthStore.getState().refreshToken).toBe('new-refresh');
    expect(useAuthStore.getState().user).toEqual(user);
  });

  it('logout clears all auth state', () => {
    useAuthStore.setState({ token: 'abc', refreshToken: 'ref', expiresAt: 999, user: mockUser() });
    useAuthStore.getState().logout();

    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().refreshToken).toBeNull();
    expect(useAuthStore.getState().expiresAt).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
  });

  it('isAdmin returns true for admin role', () => {
    useAuthStore.setState({ token: 'abc', refreshToken: null, expiresAt: null, user: mockUser({ roles: ['admin'] }) });

    expect(useAuthStore.getState().isAdmin()).toBe(true);
  });

  it('isAdmin returns false for non-admin role', () => {
    useAuthStore.setState({ token: 'abc', refreshToken: null, expiresAt: null, user: mockUser({ roles: ['viewer'] }) });

    expect(useAuthStore.getState().isAdmin()).toBe(false);
  });

  it('isEditor returns true for editor role', () => {
    useAuthStore.setState({ token: 'abc', refreshToken: null, expiresAt: null, user: mockUser({ roles: ['editor'] }) });

    expect(useAuthStore.getState().isEditor()).toBe(true);
  });

  it('isEditor returns true for admin role', () => {
    useAuthStore.setState({ token: 'abc', refreshToken: null, expiresAt: null, user: mockUser({ roles: ['admin'] }) });

    expect(useAuthStore.getState().isEditor()).toBe(true);
  });

  it('isEditor returns false for viewer-only', () => {
    useAuthStore.setState({ token: 'abc', refreshToken: null, expiresAt: null, user: mockUser({ roles: ['viewer'] }) });

    expect(useAuthStore.getState().isEditor()).toBe(false);
  });

  it('isAdmin returns false when user is null', () => {
    expect(useAuthStore.getState().isAdmin()).toBe(false);
  });
});

describe('useAuthStore persistence', () => {
  const STORAGE_KEY = 'geolens-auth';

  beforeEach(() => {
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null, sessionId: null });
    window.localStorage.removeItem(STORAGE_KEY);
  });

  afterEach(() => {
    window.localStorage.removeItem(STORAGE_KEY);
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null, sessionId: null });
  });

  function stored(): string {
    return window.localStorage.getItem(STORAGE_KEY) ?? '';
  }

  it('declares persist version 2', () => {
    expect(useAuthStore.persist.getOptions().version).toBe(2);
  });

  it('persists a cookie session as its id and user, never its access token', () => {
    const user = mockUser();
    useAuthStore.getState().setAuth('access-secret', null, 900, user);
    useAuthStore.getState().setTokens('rotated-secret', null, 900);

    const state = JSON.parse(stored()).state;
    expect(state).toEqual({ sessionId: useAuthStore.getState().sessionId, user });
    expect(stored()).not.toContain('secret');
    expect(useAuthStore.getState().token).toBe('rotated-secret');
  });

  it('persists nothing about a body-token session', () => {
    useAuthStore.getState().setAuth('access-secret', 'refresh-secret', 900, mockUser());

    expect(JSON.parse(stored()).state).toEqual({ sessionId: null, user: null });
    expect(stored()).not.toContain('secret');
    expect(useAuthStore.getState().refreshToken).toBe('refresh-secret');
  });

  it('drops the tokens of a legacy un-versioned blob and keeps its refresh token in memory only', async () => {
    const legacyUser = mockUser({ id: 'legacy-1' });
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        state: { token: 'legacy-access', refreshToken: 'legacy-refresh', expiresAt: 1234567890, user: legacyUser },
      }),
    );

    await useAuthStore.persist.rehydrate();

    const state = useAuthStore.getState();
    expect(state.token).toBeNull();
    expect(state.refreshToken).toBe('legacy-refresh');
    expect(state.user).toEqual(legacyUser);
    expect(state.sessionId).toEqual(expect.any(String));
    expect(stored()).not.toContain('legacy-access');
    expect(stored()).not.toContain('legacy-refresh');
  });

  it('drops the access token of a version 1 cookie session and keeps it recoverable', async () => {
    const user = mockUser();
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        state: { token: 'v1-access', expiresAt: 9999999999, user, sessionId: 'session-1' },
        version: 1,
      }),
    );

    await useAuthStore.persist.rehydrate();

    expect(useAuthStore.getState()).toMatchObject({ token: null, refreshToken: null, sessionId: 'session-1', user });
    expect(stored()).not.toContain('v1-access');
  });

  it('rehydration drops a persisted user without roles and keeps role checks callable', async () => {
    const { roles: _roles, ...userWithoutRoles } = mockUser();
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ state: { sessionId: 'session-1', user: userWithoutRoles }, version: 2 }),
    );

    await useAuthStore.persist.rehydrate();

    expect(useAuthStore.getState().sessionId).toBe('session-1');
    expect(useAuthStore.getState().user).toBeNull();
    expect(() => useAuthStore.getState().isAdmin()).not.toThrow();
    expect(useAuthStore.getState().isAdmin()).toBe(false);
    expect(useAuthStore.getState().isEditor()).toBe(false);
  });

  it('ignores a token planted in a current-version blob', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ state: { sessionId: 'session-1', user: null, token: 'planted' }, version: 2 }),
    );

    await useAuthStore.persist.rehydrate();

    expect(useAuthStore.getState().token).toBeNull();
  });
});
