import { render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router';
import { JobList } from '../JobList';

// fix(#1204): the Jobs list is server-paginated, so ordering had to go through
// the API — sorting only the current page would leave page 1 sorted and page 2
// unrelated, which looks correct in the UI and is not. These tests pin the
// URL-owned sort state, the accessibility contract, and the columns that
// deliberately have no sort control.

const { mockUseAdminJobs } = vi.hoisted(() => ({ mockUseAdminJobs: vi.fn() }));

vi.mock('@/hooks/use-admin', () => ({
  useAdminJobs: (...args: unknown[]) => mockUseAdminJobs(...args),
  useUserNames: () => ({ data: [] }),
  useRetryAdminJob: () => ({ mutate: vi.fn(), isPending: false }),
  useCancelAdminJob: () => ({ mutate: vi.fn(), isPending: false }),
}));

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

/** Surfaces the live URL so state->URL can be asserted, not just URL->state. */
function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

function lastCall() {
  return mockUseAdminJobs.mock.calls.at(-1)?.[0] as Record<string, unknown>;
}

// The headers only render when the list has rows, so every test needs one.
const JOB = {
  id: '11111111-1111-4111-8111-111111111111',
  status: 'complete',
  source_filename: 'parcels.geojson',
  dataset_id: null,
  error_message: null,
  can_retry: false,
  retry_reason: null,
  user_metadata: null,
  created_by: null,
  username: 'alice',
  started_at: '2026-01-01T00:00:00Z',
  completed_at: '2026-01-01T00:01:00Z',
  created_at: '2026-01-01T00:00:00Z',
};

function renderList(route = '/admin/jobs') {
  return render(
    <>
      <JobList />
      <LocationProbe />
    </>,
    { route },
  );
}

beforeEach(() => {
  mockUseAdminJobs.mockReset();
  mockUseAdminJobs.mockReturnValue({
    data: { jobs: [JOB], total: 1 },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
});

describe('JobList sorting', () => {
  it('requests the historical created_at descending order by default', () => {
    renderList();

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'desc' });
  });

  it('names the sortable header with its visible label plus the next action', () => {
    renderList();

    // The accessible name must CONTAIN the visible label (WCAG 2.5.3) — an
    // aria-label would have replaced it.
    expect(
      screen.getByRole('button', { name: 'Filename, sort ascending' }),
    ).toBeInTheDocument();
  });

  it('marks sort state with aria-sort on the th, not on the button', () => {
    renderList('/admin/jobs?sort=status&order=desc');

    expect(screen.getByRole('columnheader', { name: /Status/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
    expect(screen.getByRole('columnheader', { name: /Duration/ })).toHaveAttribute(
      'aria-sort',
      'none',
    );
    // The active header now offers the opposite direction.
    expect(
      screen.getByRole('button', { name: 'Status, sort ascending' }),
    ).toBeInTheDocument();
  });

  it('sorts ascending on first activation and flips on the second', async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole('button', { name: /^Filename/ }));
    expect(lastCall()).toMatchObject({ sort: 'source_filename', order: 'asc' });

    await user.click(screen.getByRole('button', { name: /^Filename/ }));
    expect(lastCall()).toMatchObject({ sort: 'source_filename', order: 'desc' });
  });

  it('flips the default column to ascending on first activation', async () => {
    const user = userEvent.setup();
    renderList();

    // Created At is already the active DESCENDING sort, so activating it must
    // reverse rather than re-assert descending.
    await user.click(screen.getByRole('button', { name: /^Created At/ }));

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'asc' });
  });

  it('offers Duration as a sort key, ordered by the elapsed interval', async () => {
    const user = userEvent.setup();
    renderList();

    // Duration is rendered from started_at/completed_at but IS orderable: the
    // API sorts by the completed_at - started_at interval.
    await user.click(screen.getByRole('button', { name: /^Duration/ }));

    expect(lastCall()).toMatchObject({ sort: 'duration', order: 'asc' });
  });

  it('is operable from the keyboard', async () => {
    const user = userEvent.setup();
    renderList();

    const header = screen.getByRole('button', { name: /^User/ });
    header.focus();
    await user.keyboard('{Enter}');

    expect(lastCall()).toMatchObject({ sort: 'username', order: 'asc' });
  });

  it('owns sort state in the URL', async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole('button', { name: /^Status/ }));

    const search = screen.getByTestId('location').textContent ?? '';
    expect(new URLSearchParams(search).get('sort')).toBe('status');
    expect(new URLSearchParams(search).get('order')).toBe('asc');
  });

  it('reads sort state back out of the URL', () => {
    renderList('/admin/jobs?sort=duration&order=asc');

    expect(lastCall()).toMatchObject({ sort: 'duration', order: 'asc' });
  });

  it('falls back to the default for a sort field the API would refuse', () => {
    renderList('/admin/jobs?sort=file_path&order=sideways');

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'desc' });
  });

  it('keeps the status filter that arrived in the URL', async () => {
    const user = userEvent.setup();
    renderList('/admin/jobs?status=failed');

    await user.click(screen.getByRole('button', { name: /^Filename/ }));

    expect(lastCall()).toMatchObject({ status: 'failed', sort: 'source_filename' });
  });

  it('does not clear the search filter when a header is activated', async () => {
    // fix(#1204): JobList resets its filters on any navigation it did not make
    // itself (#1185), keyed on location.key. A sort write produces a new key,
    // so without the self-write exemption every header click would silently
    // wipe the user's search — the list would reorder AND widen at once.
    const user = userEvent.setup();
    renderList();

    await user.type(screen.getByRole('textbox'), 'parcels');
    await vi.waitFor(() => expect(lastCall()).toMatchObject({ search: 'parcels' }));

    await user.click(screen.getByRole('button', { name: /^Filename/ }));

    expect(lastCall()).toMatchObject({ search: 'parcels', sort: 'source_filename' });
  });

  it('returns to the first page when the ordering changes', async () => {
    const user = userEvent.setup();
    mockUseAdminJobs.mockReturnValue({
      data: { jobs: [JOB], total: 100 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderList();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(lastCall()).toMatchObject({ skip: 25 });

    await user.click(screen.getByRole('button', { name: /^Filename/ }));
    // Page 3 of the old ordering names different rows under the new one.
    expect(lastCall()).toMatchObject({ skip: 0, sort: 'source_filename' });
  });

  it('offers no sort control for the disclosure column', () => {
    renderList();

    const header = screen.getByRole('columnheader', { name: 'Details' });
    expect(within(header).queryByRole('button')).toBeNull();
    expect(header).not.toHaveAttribute('aria-sort');
  });
});
