import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import { UserResetPasswordDialog } from '@/components/admin/UserResetPasswordDialog';
import { useResetUserPassword } from '@/hooks/use-admin';
import type { UserResponse } from '@/types/api';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('@/hooks/use-admin', () => ({
  useResetUserPassword: vi.fn(),
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
});
