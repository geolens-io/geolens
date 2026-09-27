import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { AuditLogViewer } from '../AuditLogViewer';

const mocks = vi.hoisted(() => ({ useAuditLogs: vi.fn() }));
const userId = '11111111-1111-4111-8111-111111111111';

vi.mock('@/hooks/use-admin', () => ({
  useAuditLogs: (...args: unknown[]) => mocks.useAuditLogs(...args),
  useUserNames: () => ({ data: [{ id: userId, username: 'alice' }, { id: '22222222-2222-4222-8222-222222222222', username: 'bob' }] }),
}));

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
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
