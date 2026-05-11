import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('@/api/auth', () => ({
  getMyPermissions: vi.fn(),
}));

import { getMyPermissions } from '@/api/auth';
import { usePermissions } from '@/hooks/use-permissions';

const mockGetMyPermissions = vi.mocked(getMyPermissions);

describe('usePermissions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
  });

  it('returns null permissions when not authenticated', () => {
    const { result } = renderHook(() => usePermissions());

    expect(result.current.permissions).toBeNull();
    expect(result.current.can('upload')).toBe(false);
    expect(mockGetMyPermissions).not.toHaveBeenCalled();
  });

  it('fetches permissions when authenticated', async () => {
    useAuthStore.setState({ token: 'test-token', refreshToken: null, expiresAt: null, user: null });
    const mockData = { permissions: { upload: true, manage_users: false, edit_metadata: true } };
    mockGetMyPermissions.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => usePermissions());

    await waitFor(() => expect(result.current.permissions).not.toBeNull());
    expect(result.current.can('upload')).toBe(true);
    expect(result.current.can('manage_users')).toBe(false);
    const unknownCapability = 'nonexistent' as Parameters<typeof result.current.can>[0];
    expect(result.current.can(unknownCapability)).toBe(false);
  });

  it('returns false for all capabilities on error', async () => {
    useAuthStore.setState({ token: 'test-token', refreshToken: null, expiresAt: null, user: null });
    mockGetMyPermissions.mockRejectedValueOnce(new Error('Unauthorized'));

    const { result } = renderHook(() => usePermissions());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.can('upload')).toBe(false);
  });

  it('returns error state on network failure', async () => {
    useAuthStore.setState({ token: 'test-token', refreshToken: null, expiresAt: null, user: null });
    mockGetMyPermissions.mockRejectedValueOnce(new Error('Network error'));

    const { result } = renderHook(() => usePermissions());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.permissions).toBeNull();
    expect(result.current.can('edit_metadata')).toBe(false);
  });

  it('starts in loading state when authenticated', () => {
    useAuthStore.setState({ token: 'test-token', refreshToken: null, expiresAt: null, user: null });
    mockGetMyPermissions.mockReturnValueOnce(new Promise(() => {}) as never);

    const { result } = renderHook(() => usePermissions());

    expect(result.current.isLoading).toBe(true);
  });
});
