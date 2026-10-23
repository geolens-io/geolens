import { render, screen, waitFor, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ApiError } from '@/api/client';
import * as adminApi from '@/api/admin';
import { GroupList } from '../GroupList';

vi.mock('@/api/admin', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/admin')>()),
  listGroups: vi.fn(),
  createGroup: vi.fn(),
  renameGroup: vi.fn(),
  deleteGroup: vi.fn(),
  listGroupMembers: vi.fn(),
  addGroupMembers: vi.fn(),
  removeGroupMember: vi.fn(),
  listUserNames: vi.fn(),
}));

const permissions = vi.hoisted(() => ({ manageUsers: true }));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: (capability: string) => capability === 'manage_users' && permissions.manageUsers,
    isLoading: false,
    permissions: {},
  }),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const api = vi.mocked(adminApi);

const GROUP = {
  id: 'g1',
  name: 'Planning',
  member_count: 2,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

function listOf(...groups: (typeof GROUP)[]) {
  return { groups, total: groups.length };
}

beforeEach(() => {
  vi.resetAllMocks();
  permissions.manageUsers = true;
  api.listGroups.mockResolvedValue(listOf(GROUP));
  api.listGroupMembers.mockResolvedValue([
    { id: 'u1', username: 'alice' },
    { id: 'u2', username: 'bob' },
  ]);
  api.listUserNames.mockResolvedValue([
    { id: 'u1', username: 'alice' },
    { id: 'u2', username: 'bob' },
    { id: 'u3', username: 'carol' },
  ]);
});

describe('GroupList', () => {
  it('lists groups with their member counts', async () => {
    render(<GroupList />);
    const row = (await screen.findByRole('cell', { name: 'Planning' })).closest('tr')!;
    expect(within(row).getByText('2 members')).toBeInTheDocument();
  });

  it('shows an empty state with a create action', async () => {
    api.listGroups.mockResolvedValue(listOf());
    render(<GroupList />);
    expect(await screen.findByText('No groups yet')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Create group' }).length).toBeGreaterThan(0);
  });

  it('creates a group and returns focus to the button that opened the dialog', async () => {
    api.createGroup.mockResolvedValue({ ...GROUP, id: 'g2', name: 'Survey', member_count: 0 });
    const user = userEvent.setup();
    render(<GroupList />);
    await screen.findByRole('cell', { name: 'Planning' });
    const trigger = screen.getByRole('button', { name: 'Create group' });

    await user.click(trigger);
    await user.type(await screen.findByLabelText('Group name'), '  Survey ');
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(api.createGroup).toHaveBeenCalledWith('Survey'));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('keeps the dialog open and shows the refusal when the name is taken', async () => {
    api.createGroup.mockRejectedValue(new ApiError('A group named "Planning" already exists', 409));
    const user = userEvent.setup();
    render(<GroupList />);
    await user.click(await screen.findByRole('button', { name: 'Create group' }));
    await user.type(await screen.findByLabelText('Group name'), 'Planning');
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Create' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('already exists');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('renames a group from the row menu', async () => {
    api.renameGroup.mockResolvedValue({ ...GROUP, name: 'Planning team' });
    const user = userEvent.setup();
    render(<GroupList />);
    await user.click(await screen.findByRole('button', { name: 'Actions for group Planning' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Rename' }));
    const field = await screen.findByLabelText('Group name');
    expect(field).toHaveValue('Planning');

    await user.clear(field);
    await user.type(field, 'Planning team');
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(api.renameGroup).toHaveBeenCalledWith('g1', 'Planning team'));
  });

  it('asks before deleting and says members lose access', async () => {
    api.deleteGroup.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<GroupList />);
    const menu = await screen.findByRole('button', { name: 'Actions for group Planning' });
    await user.click(menu);
    await user.click(await screen.findByRole('menuitem', { name: 'Delete' }));

    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent(/lose access to datasets shared with the group/i);
    expect(api.deleteGroup).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(api.deleteGroup).not.toHaveBeenCalled();
    await waitFor(() => expect(menu).toHaveFocus());

    await user.click(menu);
    await user.click(await screen.findByRole('menuitem', { name: 'Delete' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(api.deleteGroup).toHaveBeenCalledWith('g1'));
  });

  it('keeps the delete dialog open and shows the error when the delete fails', async () => {
    api.deleteGroup.mockRejectedValue(new ApiError('Group not found', 404));
    const user = userEvent.setup();
    render(<GroupList />);
    await user.click(await screen.findByRole('button', { name: 'Actions for group Planning' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Delete' }));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Group not found');
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  });

  describe('members', () => {
    async function openMembers(user: ReturnType<typeof userEvent.setup>) {
      render(<GroupList />);
      const opener = await screen.findByRole('button', { name: 'Members of Planning' });
      await user.click(opener);
      await screen.findByRole('dialog', { name: 'Members of Planning' });
      return opener;
    }

    it('puts focus on the picker when the dialog opens', async () => {
      await openMembers(userEvent.setup());
      await waitFor(() => expect(screen.getByRole('combobox', { name: 'Add a person' })).toHaveFocus());
    });

    it('without user management permission, shows a note instead of the picker and still lists members', async () => {
      permissions.manageUsers = false;
      const user = userEvent.setup();
      await openMembers(user);

      expect(await screen.findByText(/needs user management permission/i)).toBeInTheDocument();
      expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
      expect(api.listUserNames).not.toHaveBeenCalled();
      await screen.findByText('alice');
      api.removeGroupMember.mockResolvedValue(undefined);
      await user.click(screen.getByRole('button', { name: 'Remove bob from Planning' }));
      await waitFor(() => expect(api.removeGroupMember).toHaveBeenCalledWith('g1', 'u2'));
    });

    it('without the picker, moves focus to the next member, then to Close when none is left', async () => {
      permissions.manageUsers = false;
      api.removeGroupMember.mockResolvedValue(undefined);
      api.listGroupMembers
        .mockResolvedValueOnce([
          { id: 'u1', username: 'alice' },
          { id: 'u2', username: 'bob' },
        ])
        .mockResolvedValueOnce([{ id: 'u2', username: 'bob' }])
        .mockResolvedValue([]);
      const user = userEvent.setup();
      await openMembers(user);

      await user.click(await screen.findByRole('button', { name: 'Remove alice from Planning' }));
      await waitFor(() => expect(screen.getByRole('button', { name: 'Remove bob from Planning' })).toHaveFocus());

      await user.click(screen.getByRole('button', { name: 'Remove bob from Planning' }));
      await waitFor(() =>
        expect(document.activeElement?.closest('[data-slot="dialog-footer"]')).toHaveTextContent('Close'),
      );
    });

    it('shows the error when the user names request fails', async () => {
      api.listUserNames.mockRejectedValue(new ApiError('Could not load users', 500));
      await openMembers(userEvent.setup());

      expect(await screen.findByRole('alert')).toHaveTextContent('Could not load users');
    });

    it('lists the members and announces an empty group', async () => {
      api.listGroupMembers.mockResolvedValue([]);
      await openMembers(userEvent.setup());
      expect(await screen.findByText('This group has no members yet.')).toBeInTheDocument();
    });

    it('adds a member picked with the keyboard, leaving out those already in the group', async () => {
      api.addGroupMembers.mockResolvedValue({ ...GROUP, member_count: 3 });
      const user = userEvent.setup();
      await openMembers(user);
      await screen.findByRole('list', { name: 'Members of Planning' });

      const picker = screen.getByRole('combobox', { name: 'Add a person' });
      await user.click(picker);
      await user.keyboard('{ArrowDown}');
      expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['carol']);
      await user.keyboard('{Enter}');

      await waitFor(() => expect(api.addGroupMembers).toHaveBeenCalledWith('g1', ['u3']));
    });

    it('shows why the server refused an add', async () => {
      api.addGroupMembers.mockRejectedValue(
        new ApiError("A VRT dataset would reach people who cannot see all of its source datasets.", 422),
      );
      const user = userEvent.setup();
      await openMembers(user);
      const picker = screen.getByRole('combobox', { name: 'Add a person' });
      await user.type(picker, 'carol');
      await screen.findByRole('option', { name: 'carol' });
      await user.keyboard('{Enter}');

      expect(await screen.findByRole('alert')).toHaveTextContent('would reach people who cannot see');
    });

    it('removes a member and moves focus to the picker', async () => {
      api.removeGroupMember.mockResolvedValue(undefined);
      const user = userEvent.setup();
      await openMembers(user);
      await user.click(await screen.findByRole('button', { name: 'Remove bob from Planning' }));

      await waitFor(() => expect(api.removeGroupMember).toHaveBeenCalledWith('g1', 'u2'));
      await waitFor(() => expect(screen.getByRole('combobox', { name: 'Add a person' })).toHaveFocus());
    });

    it('returns focus to the Members button on Escape', async () => {
      const user = userEvent.setup();
      const opener = await openMembers(user);
      await user.keyboard('{Escape}');
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      await waitFor(() => expect(opener).toHaveFocus());
    });
  });
});
