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

  it('hides the created placeholder below sm while loading, as the column header does', () => {
    api.listGroups.mockReturnValue(new Promise(() => {}));
    render(<GroupList />);
    const cells = screen.getAllByRole('row')[1].querySelectorAll('td');
    expect(cells).toHaveLength(4);
    expect(cells[2]).toHaveClass('hidden', 'sm:table-cell');
    expect(cells[1]).not.toHaveClass('hidden');
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

    await user.type(screen.getByLabelText('Group name'), 'x');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Group name')).not.toHaveAttribute('aria-invalid');
  });

  it('steps back one page, not to the start, after deleting the only group on a later page', async () => {
    const many = (n: number, offset: number) =>
      Array.from({ length: n }, (_, i) => ({ ...GROUP, id: `g${offset + i}`, name: `Group ${offset + i}` }));
    let deleted = false;
    api.listGroups.mockImplementation(async ({ skip = 0 } = {}) => {
      // 41 groups, then 40 after the delete of the only one on page 3.
      const total = deleted ? 40 : 41;
      const page = skip / 20;
      const n = Math.max(Math.min(20, total - skip), 0);
      await new Promise((r) => setTimeout(r, 20));
      return { groups: many(n, page * 20), total };
    });
    api.deleteGroup.mockImplementation(async () => {
      deleted = true;
    });
    const user = userEvent.setup();
    render(<GroupList />);
    await screen.findByRole('cell', { name: 'Group 0' });
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByRole('cell', { name: 'Group 20' });
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(await screen.findByRole('button', { name: 'Actions for group Group 40' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Delete' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }));

    expect(await screen.findByRole('cell', { name: 'Group 20' })).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 100));
    expect(screen.getByRole('cell', { name: 'Group 20' })).toBeInTheDocument();
    expect(screen.queryByRole('cell', { name: 'Group 0' })).not.toBeInTheDocument();
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
    expect(dialog).toHaveTextContent(/lose access to datasets, maps and stories shared with the group/i);
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

    it('offers no candidates, and shows the error, while the member list has not loaded', async () => {
      api.listGroupMembers.mockRejectedValue(new ApiError('Could not load members', 500));
      const user = userEvent.setup();
      await openMembers(user);
      expect(await screen.findByText(/Could not load members/)).toBeInTheDocument();

      await user.click(screen.getByRole('combobox', { name: 'Add a person' }));
      await user.keyboard('{ArrowDown}');
      expect(screen.queryByRole('option')).not.toBeInTheDocument();
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

    it('ignores a second pick while an add is pending, then accepts it once the add settles', async () => {
      api.listUserNames.mockResolvedValue([
        { id: 'u3', username: 'carol' },
        { id: 'u4', username: 'dave' },
      ]);
      let settleFirst!: (group: typeof GROUP) => void;
      api.addGroupMembers
        .mockReturnValueOnce(new Promise((resolve) => (settleFirst = resolve)))
        .mockResolvedValue({ ...GROUP, member_count: 4 });
      const user = userEvent.setup();
      await openMembers(user);
      await screen.findByRole('list', { name: 'Members of Planning' });
      const picker = screen.getByRole('combobox', { name: 'Add a person' });

      await user.type(picker, 'carol');
      await user.click(screen.getByRole('option', { name: 'carol' }));
      await waitFor(() => expect(api.addGroupMembers).toHaveBeenCalledWith('g1', ['u3']));

      await user.type(picker, 'dave');
      await user.click(screen.getByRole('option', { name: 'dave' }));
      expect(api.addGroupMembers).toHaveBeenCalledTimes(1);
      expect(picker).toHaveValue('dave');
      expect(picker).toHaveAttribute('aria-expanded', 'true');

      settleFirst({ ...GROUP, member_count: 3 });
      await waitFor(() => expect(picker).not.toHaveAttribute('aria-busy'));
      await user.click(screen.getByRole('option', { name: 'dave' }));
      await waitFor(() => expect(api.addGroupMembers).toHaveBeenLastCalledWith('g1', ['u4']));
      expect(api.addGroupMembers).toHaveBeenCalledTimes(2);
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

    it('closes the picker list on the first Escape and the dialog on the second', async () => {
      const user = userEvent.setup();
      const opener = await openMembers(user);
      const picker = screen.getByRole('combobox', { name: 'Add a person' });
      await waitFor(() => expect(picker).toHaveFocus());
      await user.keyboard('{ArrowDown}');
      expect(picker).toHaveAttribute('aria-expanded', 'true');

      await user.keyboard('{Escape}');
      expect(picker).toHaveAttribute('aria-expanded', 'false');
      expect(screen.getByRole('dialog')).toBeInTheDocument();

      await user.keyboard('{Escape}');
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      await waitFor(() => expect(opener).toHaveFocus());
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
