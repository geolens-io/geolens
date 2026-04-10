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
