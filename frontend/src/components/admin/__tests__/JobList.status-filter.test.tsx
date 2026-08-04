import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { JobList } from '../JobList';

// fix(#1185): the admin sidebar's failed-jobs badge links to
// /admin/jobs?status=failed so the number the user clicked equals the number
// the list shows. That only holds if JobList reads the status filter off the
// URL, so these tests pin the read, the write-back, and the fallback for a
// value the API would reject.

const { mockUseAdminJobs } = vi.hoisted(() => ({ mockUseAdminJobs: vi.fn() }));

vi.mock('@/hooks/use-admin', () => ({
  useAdminJobs: (...args: unknown[]) => mockUseAdminJobs(...args),
  useUserNames: () => ({ data: [] }),
  useRetryAdminJob: () => ({ mutate: vi.fn(), isPending: false }),
}));

// Radix Select needs these in jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

function lastQuery() {
  return mockUseAdminJobs.mock.calls.at(-1)?.[0] as { status?: string } | undefined;
}

function statusFilter() {
  return screen.getByRole('combobox', { name: 'Status' });
}

beforeEach(() => {
  mockUseAdminJobs.mockReset();
  mockUseAdminJobs.mockReturnValue({
    data: { jobs: [], total: 0 },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
});

describe('JobList status filter from the URL (#1185)', () => {
  it('queries the failed jobs when the route carries ?status=failed', () => {
    render(<JobList />, { route: '/admin/jobs?status=failed' });

    expect(mockUseAdminJobs).toHaveBeenCalled();
    expect(lastQuery()?.status).toBe('failed');
    expect(statusFilter()).toHaveTextContent('Failed');
  });

  it('queries every job when the route carries no status', () => {
    render(<JobList />, { route: '/admin/jobs' });

    expect(mockUseAdminJobs).toHaveBeenCalled();
    expect(lastQuery()?.status).toBeUndefined();
    expect(statusFilter()).toHaveTextContent('All Statuses');
  });

  it('ignores a status the filter does not offer instead of forwarding it', () => {
    render(<JobList />, { route: '/admin/jobs?status=exploded' });

    expect(mockUseAdminJobs).toHaveBeenCalled();
    expect(lastQuery()?.status).toBeUndefined();
    expect(statusFilter()).toHaveTextContent('All Statuses');
  });

  it('writes the dropdown selection back to the URL-owned filter', async () => {
    const user = userEvent.setup();
    render(<JobList />, { route: '/admin/jobs' });

    await user.click(statusFilter());
    await user.click(await screen.findByRole('option', { name: 'Running' }));

    expect(lastQuery()?.status).toBe('running');
    expect(statusFilter()).toHaveTextContent('Running');
  });

  it('clears the status filter back to all statuses', async () => {
    const user = userEvent.setup();
    render(<JobList />, { route: '/admin/jobs?status=failed' });
    expect(lastQuery()?.status).toBe('failed');

    await user.click(screen.getByRole('button', { name: 'Clear' }));

    expect(lastQuery()?.status).toBeUndefined();
    expect(statusFilter()).toHaveTextContent('All Statuses');
  });
});
