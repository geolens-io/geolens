import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import { UserEditDialog } from '@/components/admin/UserEditDialog';
import { useUpdateUser } from '@/hooks/use-admin';
import type { UserResponse } from '@/types/api';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('@/hooks/use-admin', () => ({
  useUpdateUser: vi.fn(),
}));

vi.mock('@/components/admin/ApiKeySection', () => ({
  ApiKeySection: () => null,
}));

const user: UserResponse = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'lifecycle-user',
  email: 'lifecycle@example.com',
  is_active: true,
  status: 'active',
  last_login_at: null,
  created_at: '2026-01-01T00:00:00Z',
  roles: ['viewer'],
};

describe('UserEditDialog lifecycle state', () => {
  beforeAll(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    useAuthStore.setState({ user: null });
  });

  it('submits an explicit suspended status instead of a contradictory boolean', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useUpdateUser).mockReturnValue({
      mutateAsync,
      isPending: false,
      error: null,
    } as unknown as ReturnType<typeof useUpdateUser>);
    const onOpenChange = vi.fn();
    render(
      <UserEditDialog
        user={user}
        open
        onOpenChange={onOpenChange}
      />,
    );

    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Status' }), {
      key: 'ArrowDown',
    });
    fireEvent.click(screen.getByRole('option', { name: 'Suspended' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        userId: user.id,
        data: { status: 'suspended' },
      });
    });
  });

  it('keeps self role and status read-only while allowing email updates', async () => {
    const self = { ...user, roles: ['admin'] };
    useAuthStore.setState({ user: self });
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useUpdateUser).mockReturnValue({
      mutateAsync,
      isPending: false,
      error: null,
    } as unknown as ReturnType<typeof useUpdateUser>);

    render(<UserEditDialog user={self} open onOpenChange={vi.fn()} />);

    expect(screen.queryByRole('combobox', { name: 'Role' })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Status' })).not.toBeInTheDocument();
    expect(screen.getByText('admin')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
      target: { value: 'updated@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        userId: self.id,
        data: { email: 'updated@example.com' },
      });
    });
  });

  it('keeps pending-user authority read-only and submits only an email update', async () => {
    const pendingUser = {
      ...user,
      email: 'pending@example.com',
      is_active: false,
      status: 'pending' as const,
      roles: [],
    };
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useUpdateUser).mockReturnValue({
      mutateAsync,
      isPending: false,
      error: null,
    } as unknown as ReturnType<typeof useUpdateUser>);

    render(<UserEditDialog user={pendingUser} open onOpenChange={vi.fn()} />);

    expect(screen.queryByRole('combobox', { name: 'Role' })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Status' })).not.toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
      target: { value: 'approved-address@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        userId: pendingUser.id,
        data: { email: 'approved-address@example.com' },
      });
    });
  });
});
