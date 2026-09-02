/**
 * fix(#1715 codex r2 P2): a self-reset must end the session the way every other
 * deliberate sign-out does.
 *
 * The store's own `logout()` bumps `sessionEpoch`, which stops a late refresh
 * writing rotated tokens back, but it does NOT stop the browser processing that
 * response's `Set-Cookie`. A refresh still in flight during the reset could
 * therefore land after the admin signs in again and overwrite the new refresh
 * cookie with the one the reset revoked, breaking the next refresh.
 * `abortInflightRefresh()` is what closes that window, and it has to run before
 * the epoch advances.
 *
 * This file drives the REAL useAuth (the other dialog test file stubs it), so
 * the ordering is asserted against the shared teardown rather than a mock.
 */
import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import { UserResetPasswordDialog } from '@/components/admin/UserResetPasswordDialog';
import { useResetUserPassword } from '@/hooks/use-admin';
import type { UserResponse } from '@/types/api';
import { useAuthStore } from '@/stores/auth-store';
import { abortInflightRefresh } from '@/api/client';

vi.mock('@/hooks/use-admin', () => ({
  useResetUserPassword: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('@/api/auth', () => ({
  login: vi.fn(),
  getMe: vi.fn().mockResolvedValue(null),
  logoutSession: vi.fn().mockResolvedValue(undefined),
}));

// The epoch as it stood each time the abort was called, so the ordering can be
// asserted rather than inferred from the end state.
const epochAtAbort: number[] = [];

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return {
    ...actual,
    abortInflightRefresh: vi.fn(() => {
      epochAtAbort.push(useAuthStore.getState().sessionEpoch);
    }),
  };
});

const admin: UserResponse = {
  id: '00000000-0000-0000-0000-000000000042',
  username: 'self-resetting-admin',
  email: 'admin@example.com',
  is_active: true,
  status: 'active',
  last_login_at: null,
  created_at: '2026-01-01T00:00:00Z',
  roles: ['admin'],
};

const SUBMITTED_VALUE = 'Aa1-not-a-real-password';

describe('self-reset session teardown', () => {
  beforeEach(() => {
    epochAtAbort.length = 0;
    vi.mocked(abortInflightRefresh).mockClear();
    vi.mocked(useResetUserPassword).mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(admin),
      isPending: false,
      error: null,
    } as unknown as ReturnType<typeof useResetUserPassword>);
  });

  afterEach(() => {
    useAuthStore.setState({ user: null, token: null } as never);
  });

  it('aborts an in-flight refresh before the session epoch advances', async () => {
    useAuthStore.setState({ user: admin, token: 'stale-token' } as never);
    const epochBefore = useAuthStore.getState().sessionEpoch;

    render(<UserResetPasswordDialog user={admin} open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: SUBMITTED_VALUE },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reset password' }));

    await waitFor(() => expect(abortInflightRefresh).toHaveBeenCalledTimes(1));

    // The abort saw the pre-teardown epoch, so it ran first. If the dialog went
    // back to the bare store logout, this would be epochBefore + 1 (or the
    // abort would not have happened at all).
    expect(epochAtAbort).toEqual([epochBefore]);

    await waitFor(() => expect(useAuthStore.getState().token).toBeNull());
    expect(useAuthStore.getState().sessionEpoch).toBe(epochBefore + 1);
  });

  it('does not touch the session when resetting a different account', async () => {
    useAuthStore.setState({ user: admin, token: 'live-token' } as never);
    const target: UserResponse = { ...admin, id: '00000000-0000-0000-0000-0000000000aa' };

    render(<UserResetPasswordDialog user={target} open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: SUBMITTED_VALUE },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reset password' }));

    await waitFor(() =>
      expect(vi.mocked(useResetUserPassword).mock.results.length).toBeGreaterThan(0),
    );
    expect(abortInflightRefresh).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe('live-token');
  });
});
