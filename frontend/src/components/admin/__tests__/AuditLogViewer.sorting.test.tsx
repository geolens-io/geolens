import { render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router';
import { AuditLogViewer } from '../AuditLogViewer';

// fix(#1204): the audit log is server-paginated, so ordering had to go through
// the API — sorting only the current page would leave page 1 sorted and page 2
// unrelated, which looks correct in the UI and is not. These tests pin the
// URL-owned sort state, the accessibility contract, and the two columns that
// deliberately have no sort control.

const { mockUseAuditLogs } = vi.hoisted(() => ({ mockUseAuditLogs: vi.fn() }));

vi.mock('@/hooks/use-admin', () => ({
  useAuditLogs: (...args: unknown[]) => mockUseAuditLogs(...args),
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
  return mockUseAuditLogs.mock.calls.at(-1)?.[0] as Record<string, unknown>;
}

// The headers only render when the list has rows, so every test needs one.
const LOG = {
  id: '22222222-2222-4222-8222-222222222222',
  user_id: null,
  username: 'alice',
  action: 'metadata.edit',
  resource_type: 'dataset',
  resource_id: '33333333-3333-4333-8333-333333333333',
  resource_name: 'Parcels',
  details: null,
  ip_address: '203.0.113.7',
  created_at: '2026-01-01T00:00:00Z',
};

function renderViewer(route = '/admin/audit', total = 1) {
  mockUseAuditLogs.mockReturnValue({
    data: { logs: [LOG], total },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
  return render(
    <>
      <AuditLogViewer />
      <LocationProbe />
    </>,
    { route },
  );
}

beforeEach(() => {
  mockUseAuditLogs.mockReset();
});

describe('AuditLogViewer sorting', () => {
  it('requests the historical created_at descending order by default', () => {
    renderViewer();

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'desc' });
  });

  it('names the sortable header with its visible label plus the next action', () => {
    renderViewer();

    // The accessible name must CONTAIN the visible label (WCAG 2.5.3) — an
    // aria-label would have replaced it.
    expect(
      screen.getByRole('button', { name: 'Action, sort ascending' }),
    ).toBeInTheDocument();
  });

  it('marks sort state with aria-sort on the th, not on the button', () => {
    renderViewer('/admin/audit?sort=action&order=desc');

    expect(screen.getByRole('columnheader', { name: /Action/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
    expect(screen.getByRole('columnheader', { name: /IP Address/ })).toHaveAttribute(
      'aria-sort',
      'none',
    );
    // The active header now offers the opposite direction.
    expect(
      screen.getByRole('button', { name: 'Action, sort ascending' }),
    ).toBeInTheDocument();
  });

  it('sorts ascending on first activation and flips on the second', async () => {
    const user = userEvent.setup();
    renderViewer();

    await user.click(screen.getByRole('button', { name: /^Action/ }));
    expect(lastCall()).toMatchObject({ sort: 'action', order: 'asc' });

    await user.click(screen.getByRole('button', { name: /^Action/ }));
    expect(lastCall()).toMatchObject({ sort: 'action', order: 'desc' });
  });

  it('flips the default column to ascending on first activation', async () => {
    const user = userEvent.setup();
    renderViewer();

    // Timestamp is already the active DESCENDING sort, so activating it must
    // reverse rather than re-assert descending.
    await user.click(screen.getByRole('button', { name: /^Timestamp/ }));

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'asc' });
  });

  it('is operable from the keyboard', async () => {
    const user = userEvent.setup();
    renderViewer();

    const header = screen.getByRole('button', { name: /^IP Address/ });
    header.focus();
    await user.keyboard('{Enter}');

    expect(lastCall()).toMatchObject({ sort: 'ip_address', order: 'asc' });
  });

  it('owns sort state in the URL', async () => {
    const user = userEvent.setup();
    renderViewer();

    await user.click(screen.getByRole('button', { name: /^User/ }));

    const search = screen.getByTestId('location').textContent ?? '';
    expect(new URLSearchParams(search).get('sort')).toBe('username');
    expect(new URLSearchParams(search).get('order')).toBe('asc');
  });

  it('reads sort state back out of the URL', () => {
    renderViewer('/admin/audit?sort=resource_type&order=asc');

    expect(lastCall()).toMatchObject({ sort: 'resource_type', order: 'asc' });
  });

  it('falls back to the default for a sort field the API would refuse', () => {
    // resource_name is the trap: it IS a visible column, but it is resolved
    // per page after the query, so the API refuses it.
    renderViewer('/admin/audit?sort=resource_name&order=sideways');

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'desc' });
  });

  it('composes sort with the resource-type filter instead of replacing it', async () => {
    const user = userEvent.setup();
    renderViewer();

    await user.type(screen.getByLabelText('Resource type'), 'dataset');
    await vi.waitFor(() =>
      expect(lastCall()).toMatchObject({ resource_type: 'dataset' }),
    );

    await user.click(screen.getByRole('button', { name: /^Action/ }));

    expect(lastCall()).toMatchObject({ resource_type: 'dataset', sort: 'action' });
  });

  it('returns to the first page when the ordering changes', async () => {
    const user = userEvent.setup();
    renderViewer('/admin/audit', 100);

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(lastCall()).toMatchObject({ skip: 25 });

    await user.click(screen.getByRole('button', { name: /^Action/ }));
    // Page 3 of the old ordering names different rows under the new one.
    expect(lastCall()).toMatchObject({ skip: 0, sort: 'action' });
  });

  it('offers no sort control for columns the API cannot order', () => {
    renderViewer();

    // Name is resolved after the query; Resource ID is an opaque uuid; the
    // disclosure column has no data at all.
    for (const label of ['Name', 'Resource ID', 'Details']) {
      const header = screen.getByRole('columnheader', { name: label });
      expect(within(header).queryByRole('button')).toBeNull();
      expect(header).not.toHaveAttribute('aria-sort');
    }
  });
});
