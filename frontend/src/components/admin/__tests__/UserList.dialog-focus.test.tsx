import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { UserList } from '../UserList';

const { mockUseUserList } = vi.hoisted(() => ({ mockUseUserList: vi.fn() }));

vi.mock('../UserEditDialog', async () => {
  const { Dialog, DialogContent, DialogTitle } = await import('@/components/ui/dialog');
  return {
    UserEditDialog: ({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) => (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <DialogTitle>Edit</DialogTitle>
        </DialogContent>
      </Dialog>
    ),
  };
});

vi.mock('@/hooks/use-admin', () => ({
  useUserList: (...args: unknown[]) => mockUseUserList(...args),
  useCreateUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useApproveUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useRejectUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useDeactivateUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
}));

beforeEach(() => {
  mockUseUserList.mockReset();
  mockUseUserList.mockReturnValue({
    data: { users: [], total: 0 },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
});

describe('UserList Add User dialog focus', () => {
  it.each([
    ['Cancel', async (user: ReturnType<typeof userEvent.setup>) =>
      user.click(await screen.findByRole('button', { name: /^cancel$/i }))],
    ['Escape', async (user: ReturnType<typeof userEvent.setup>) => user.keyboard('{Escape}')],
  ])('returns focus to the Add User button on %s', async (_label, close) => {
    const user = userEvent.setup();
    render(<UserList />);
    const trigger = screen.getByRole('button', { name: /add user/i });

    await user.click(trigger);
    await screen.findByRole('dialog');
    await close(user);

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('returns focus to the row actions button when a menu-opened dialog closes', async () => {
    mockUseUserList.mockReturnValue({
      data: {
        users: [
          {
            id: 'u1',
            username: 'alice',
            email: 'a@example.com',
            is_active: true,
            status: 'active',
            last_login_at: null,
            created_at: '2026-08-01T00:00:00Z',
            roles: [],
          },
        ],
        total: 1,
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    const user = userEvent.setup();
    render(<UserList />);
    const rowMenu = screen.getByRole('button', { name: /alice/i });

    await user.click(rowMenu);
    await user.click(await screen.findByRole('menuitem', { name: /edit/i }));
    await screen.findByRole('dialog');
    await user.keyboard('{Escape}');

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(rowMenu).toHaveFocus());
  });
});
