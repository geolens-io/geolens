import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { AuditLogViewer } from '../AuditLogViewer';

const mocks = vi.hoisted(() => ({ useAuditLogs: vi.fn(), useUserNames: vi.fn(), canManageUsers: true }));
const userId = '11111111-1111-4111-8111-111111111111';

vi.mock('@/hooks/use-admin', () => ({
  useAuditLogs: (...args: unknown[]) => mocks.useAuditLogs(...args),
  useUserNames: (...args: unknown[]) => mocks.useUserNames(...args),
}));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: (capability: string) => capability === 'manage_users' && mocks.canManageUsers }),
}));

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  mocks.canManageUsers = true;
  mocks.useUserNames.mockReturnValue({ data: [{ id: userId, username: 'alice' }, { id: '22222222-2222-4222-8222-222222222222', username: 'bob' }] });
});

it('filters the audit log by a searched username while keeping UUID entry', async () => {
  const user = userEvent.setup();
  mocks.useAuditLogs.mockReturnValue({ data: { logs: [], total: 0 }, isLoading: false, error: null, refetch: vi.fn() });
  render(<AuditLogViewer />);

  await user.type(screen.getByRole('searchbox', { name: 'Search users' }), 'ali');
  await user.click(screen.getByRole('combobox', { name: 'User' }));
  expect(screen.getByRole('option', { name: 'alice' })).toBeInTheDocument();
  expect(screen.queryByRole('option', { name: 'bob' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('option', { name: 'alice' }));

  expect(mocks.useAuditLogs.mock.calls.at(-1)?.[0]).toMatchObject({ user_id: userId });
  expect(screen.getByRole('textbox', { name: 'User ID' })).toBeInTheDocument();
});

it('keeps UUID filtering available without requesting the manage-users list', async () => {
  const user = userEvent.setup();
  mocks.canManageUsers = false;
  mocks.useAuditLogs.mockReturnValue({ data: { logs: [], total: 0 }, isLoading: false, error: null, refetch: vi.fn() });
  render(<AuditLogViewer />);

  expect(mocks.useUserNames).toHaveBeenCalledWith({ enabled: false });
  expect(screen.queryByRole('searchbox', { name: 'Search users' })).not.toBeInTheDocument();
  expect(screen.queryByRole('combobox', { name: 'User' })).not.toBeInTheDocument();

  await user.type(screen.getByRole('textbox', { name: 'User ID' }), userId);
  expect(mocks.useAuditLogs.mock.calls.at(-1)?.[0]).toMatchObject({ user_id: userId });
});

it('can select a user beyond the first names page', async () => {
  const user = userEvent.setup();
  const laterUser = { id: '33333333-3333-4333-8333-333333333333', username: 'later-user' };
  mocks.useUserNames.mockReturnValue({
    data: [
      ...Array.from({ length: 500 }, (_, index) => ({ id: `id-${index}`, username: `user-${index}` })),
      laterUser,
    ],
  });
  mocks.useAuditLogs.mockReturnValue({ data: { logs: [], total: 0 }, isLoading: false, error: null, refetch: vi.fn() });
  render(<AuditLogViewer />);

  await user.type(screen.getByRole('searchbox', { name: 'Search users' }), 'later-user');
  await user.click(screen.getByRole('combobox', { name: 'User' }));
  await user.click(screen.getByRole('option', { name: 'later-user' }));

  expect(mocks.useAuditLogs.mock.calls.at(-1)?.[0]).toMatchObject({ user_id: laterUser.id });
});
