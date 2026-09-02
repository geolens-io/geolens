import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import { toast } from 'sonner';
import { UserResetPasswordDialog } from '@/components/admin/UserResetPasswordDialog';
import { useResetUserPassword } from '@/hooks/use-admin';
import type { UserResponse } from '@/types/api';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('@/hooks/use-admin', () => ({
  useResetUserPassword: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const user: UserResponse = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'locked-out-user',
  email: 'locked-out@example.com',
  is_active: true,
  status: 'active',
  last_login_at: null,
  created_at: '2026-01-01T00:00:00Z',
  roles: ['viewer'],
};

// Obviously synthetic: nothing here should read like a credential anyone uses.
const SUBMITTED_VALUE = 'Aa1-not-a-real-password';

function mockMutation(overrides: Record<string, unknown> = {}) {
  const mutateAsync = vi.fn().mockResolvedValue(user);
  vi.mocked(useResetUserPassword).mockReturnValue({
    mutateAsync,
    isPending: false,
    error: null,
    ...overrides,
  } as unknown as ReturnType<typeof useResetUserPassword>);
  return mutateAsync;
}

describe('UserResetPasswordDialog', () => {
  afterEach(() => {
    useAuthStore.setState({ user: null });
  });

  it('submits the entered value for the target user and closes', async () => {
    const mutateAsync = mockMutation();
    const onOpenChange = vi.fn();
    render(<UserResetPasswordDialog user={user} open onOpenChange={onOpenChange} />);

    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: SUBMITTED_VALUE },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reset password' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        userId: user.id,
        password: SUBMITTED_VALUE,
      });
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it('opts the field out of every password manager', () => {
    mockMutation();
    render(<UserResetPasswordDialog user={user} open onOpenChange={vi.fn()} />);

    const input = screen.getByLabelText('New password');
    expect(input).toHaveAttribute('type', 'password');
    expect(input).toHaveAttribute('autocomplete', 'new-password');
    expect(input).toHaveAttribute('data-1p-ignore');
    expect(input).toHaveAttribute('data-lpignore', 'true');
    expect(input).toHaveAttribute('data-bwignore');
  });

  it('warns only when the target is the signed-in admin', () => {
    mockMutation();
    const { rerender } = render(
      <UserResetPasswordDialog user={user} open onOpenChange={vi.fn()} />,
    );
    const warning = 'This is your own account, so saving signs you out here too.';
    expect(screen.queryByText(warning)).not.toBeInTheDocument();

    useAuthStore.setState({ user });
    rerender(<UserResetPasswordDialog user={user} open onOpenChange={vi.fn()} />);
    expect(screen.getByText(warning)).toBeInTheDocument();
  });

  it('keeps the dialog open and shows the reason when the reset is refused', async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error('boom'));
    vi.mocked(useResetUserPassword).mockReturnValue({
      mutateAsync,
      isPending: false,
      error: new Error('This account signs in through an identity provider'),
    } as unknown as ReturnType<typeof useResetUserPassword>);
    const onOpenChange = vi.fn();
    render(<UserResetPasswordDialog user={user} open onOpenChange={onOpenChange} />);

    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: SUBMITTED_VALUE },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reset password' }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(
      screen.getByText('This account signs in through an identity provider'),
    ).toBeInTheDocument();
  });

  it('refuses every close path while the reset is in flight, then still succeeds', async () => {
    // fix(#1715 codex r1 P2): a dismissal mid-request used to unmount the
    // dialog while the backend went on to change the password and revoke the
    // account's credentials, so the operation vanished from the UI without
    // ever showing that it had happened. The request is not aborted, so the
    // success path must still run once it resolves.
    let release: (value: unknown) => void = () => {};
    const mutateAsync = vi.fn(() =>
      new Promise((resolve) => {
        release = () => {
          // Stands in for the mutation's onSuccess, which owns the toast.
          toast.success('Password reset');
          resolve(user);
        };
      }),
    );
    const setPending = (isPending: boolean) =>
      vi.mocked(useResetUserPassword).mockReturnValue({
        mutateAsync,
        isPending,
        error: null,
      } as unknown as ReturnType<typeof useResetUserPassword>);

    setPending(false);
    const onOpenChange = vi.fn();
    const { rerender } = render(
      <UserResetPasswordDialog user={user} open onOpenChange={onOpenChange} />,
    );
    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: SUBMITTED_VALUE },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reset password' }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));

    // The request is now in flight.
    setPending(true);
    rerender(<UserResetPasswordDialog user={user} open onOpenChange={onOpenChange} />);

    // Cancel is inert and the X is not rendered at all.
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();

    // Escape does not dismiss it, and the dialog is still mounted.
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // It was never cancelled: it resolves, reports success and closes.
    setPending(false);
    release(user);
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Password reset'));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it('signs this session out after a successful self-reset', async () => {
    // fix(#1715 codex r1 P2): the backend revoked the acting admin's own
    // session, so leaving the token in the store would keep the UI looking
    // signed in until some later request happened to 401.
    useAuthStore.setState({ user, token: 'stale-token' } as never);
    const mutateAsync = mockMutation();
    render(<UserResetPasswordDialog user={user} open onOpenChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: SUBMITTED_VALUE },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reset password' }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    await waitFor(() => expect(useAuthStore.getState().token).toBeNull());
  });

  it('leaves the session alone when resetting someone else', async () => {
    const admin = { ...user, id: '00000000-0000-0000-0000-0000000000ff' };
    useAuthStore.setState({ user: admin, token: 'live-token' } as never);
    const mutateAsync = mockMutation();
    render(<UserResetPasswordDialog user={user} open onOpenChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: SUBMITTED_VALUE },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reset password' }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(useAuthStore.getState().token).toBe('live-token');
  });
});
