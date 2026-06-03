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

describe('useAuthStore — persist version + migrate (CODE-04)', () => {
  it('declares persist version 1', () => {
    expect(useAuthStore.persist.getOptions().version).toBe(1);
  });

  it('migrate is defined and returns persistedState unchanged for fromVersion === 0', () => {
    const migrate = useAuthStore.persist.getOptions().migrate;
    expect(migrate).toBeDefined();
    const legacyBlob = {
      token: 'legacy-token',
      refreshToken: 'legacy-refresh',
      expiresAt: 1234567890,
      user: mockUser({ roles: ['admin'] }),
    };
    // Existing un-versioned (legacy) sessions arrive with fromVersion = 0.
    const result = migrate!(legacyBlob, 0);
    // Conservative default: legacy sessions pass through unchanged.
    expect(result).toEqual(legacyBlob);
  });

  it('migrate returns persistedState unchanged for fromVersion === 1 (current baseline)', () => {
    const migrate = useAuthStore.persist.getOptions().migrate;
    expect(migrate).toBeDefined();
    const v1Blob = {
      token: 'v1-token',
      refreshToken: 'v1-refresh',
      expiresAt: 9999999999,
      user: mockUser(),
    };
    const result = migrate!(v1Blob, 1);
    expect(result).toEqual(v1Blob);
  });

  it('localStorage rehydration of legacy un-versioned blob preserves token and user', async () => {
    // Simulate a pre-CODE-04 user session sitting in localStorage with no `version` field.
    const legacyUser = mockUser({ id: 'legacy-1', username: 'legacyuser' });
    const legacyState = {
      state: {
        token: 'legacy-token-xyz',
        refreshToken: 'legacy-refresh-abc',
        expiresAt: 1234567890,
        user: legacyUser,
      },
      // no `version` key — zustand treats this as version 0
    };

    // Order matters: write localStorage AFTER resetting in-memory state, because
    // `useAuthStore.setState({...})` triggers the persist middleware to save the
    // null state back to storage, which would overwrite our seeded blob.
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
    window.localStorage.setItem('geolens-auth', JSON.stringify(legacyState));

    await useAuthStore.persist.rehydrate();

    expect(useAuthStore.getState().token).toBe('legacy-token-xyz');
    expect(useAuthStore.getState().refreshToken).toBe('legacy-refresh-abc');
    expect(useAuthStore.getState().expiresAt).toBe(1234567890);
    expect(useAuthStore.getState().user).toEqual(legacyUser);

    // Cleanup so other tests aren't affected.
    window.localStorage.removeItem('geolens-auth');
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
  });
});
