import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { NavLink } from 'react-router';
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
  useCancelAdminJob: () => ({ mutate: vi.fn(), isPending: false }),
}));

// Radix Select needs these in jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

function lastQuery() {
  return mockUseAdminJobs.mock.calls.at(-1)?.[0] as
    | { status?: string; user_id?: string; search?: string; skip?: number }
    | undefined;
}

// DataTableSearch renders a bare Input with a placeholder and no label, so
// there is exactly one textbox in this card to address.
function searchBox() {
  return screen.getByRole('textbox');
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

// fix(#1185 review): the sidebar badge advertises a count of ALL failed jobs.
// React Router keeps this instance mounted when the alert link only changes a
// query param on the same route, so a search/user filter set earlier would
// survive and narrow the list below the advertised number — the badge-vs-list
// mismatch #1185 exists to remove, arriving through a second door.
//
// Both directions are pinned deliberately. A refusal test alone would let the
// false-positive half regress silently: nothing in "external nav clears the
// search" notices that the dropdown ALSO started clearing it, which would be a
// real regression, since combining status with an existing filter is the whole
// point of the dropdown.
describe('JobList filter reset on external navigation (#1185 review)', () => {
  it('clears a stale search filter when the alert link is followed', async () => {
    const user = userEvent.setup();
    render(
      <>
        <NavLink to="/admin/jobs?status=failed">go to failed</NavLink>
        <JobList />
      </>,
      { route: '/admin/jobs' },
    );

    await user.type(searchBox(), 'tiles');
    expect(lastQuery()?.search).toBe('tiles');

    await user.click(screen.getByRole('link', { name: 'go to failed' }));

    expect(lastQuery()?.status).toBe('failed');
    expect(lastQuery()?.search).toBeUndefined();
    expect(lastQuery()?.skip).toBe(0);
  });

  // The first fix keyed this off the status VALUE, which is silent for the
  // most likely repeat interaction: an admin already sitting on the filtered
  // view clicks the badge again. Same URL, no value change, no reset. Keying
  // off location.key is what makes this case fire.
  it('clears filters when the alert is re-clicked from the same URL', async () => {
    const user = userEvent.setup();
    render(
      <>
        <NavLink to="/admin/jobs?status=failed">go to failed</NavLink>
        <JobList />
      </>,
      { route: '/admin/jobs?status=failed' },
    );
    expect(lastQuery()?.status).toBe('failed');

    await user.type(searchBox(), 'tiles');
    expect(lastQuery()?.search).toBe('tiles');

    // identical destination — the URL does not change at all
    await user.click(screen.getByRole('link', { name: 'go to failed' }));

    expect(lastQuery()?.status).toBe('failed');
    expect(lastQuery()?.search).toBeUndefined();
    expect(lastQuery()?.skip).toBe(0);
  });

  it('leaves an existing search filter alone when the dropdown changes status', async () => {
    const user = userEvent.setup();
    render(<JobList />, { route: '/admin/jobs' });

    await user.type(searchBox(), 'tiles');
    expect(lastQuery()?.search).toBe('tiles');

    await user.click(statusFilter());
    await user.click(await screen.findByRole('option', { name: 'Failed' }));

    expect(lastQuery()?.status).toBe('failed');
    expect(lastQuery()?.search).toBe('tiles');
  });
});
