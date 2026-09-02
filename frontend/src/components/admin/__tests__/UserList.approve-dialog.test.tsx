// fix(#1778): the Approve-user role combobox had a bare <label> with no
// htmlFor and RoleSelect was called without its id prop, so the combobox
// that decides a pending signup's role (viewer/editor/admin) announced as
// unnamed. Both sibling dialogs (UserCreateDialog, UserEditDialog) already
// pass id + <Label htmlFor>; this pins the same pattern here.
import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { UserList } from '../UserList';
import type { UserResponse } from '@/types/api';

const { mockUseUserList } = vi.hoisted(() => ({ mockUseUserList: vi.fn() }));

vi.mock('@/hooks/use-admin', () => ({
  useUserList: (...args: unknown[]) => mockUseUserList(...args),
  useApproveUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useRejectUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useDeactivateUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
}));

vi.mock('../UserCreateDialog', () => ({ UserCreateDialog: () => null }));
vi.mock('../UserEditDialog', () => ({ UserEditDialog: () => null }));
vi.mock('../UserDeleteDialog', () => ({ UserDeleteDialog: () => null }));

const pendingUser: UserResponse = {
  id: 'u1',
  username: 'pending-alice',
  email: 'alice@example.com',
  is_active: false,
  status: 'pending',
  last_login_at: null,
  created_at: '2026-08-01T00:00:00Z',
  roles: [],
};

beforeEach(() => {
  mockUseUserList.mockReset();
  mockUseUserList.mockReturnValue({
    data: { users: [pendingUser], total: 1 },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
});

describe('UserList approve dialog', () => {
  it('#1778 — the role combobox has an accessible name', async () => {
    const user = userEvent.setup();
    render(<UserList />);

    await user.click(screen.getByRole('button', { name: /pending-alice/i }));
    await user.click(await screen.findByRole('menuitem', { name: /approve/i }));

    expect(screen.getByRole('combobox', { name: /role/i })).toBeInTheDocument();
  });
});
