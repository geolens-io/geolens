import { render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router';
import { AdminSharedMapsPage } from '../AdminSharedMapsPage';

// fix(#1204): the Published Maps list is server-paginated, so ordering had to
// go through the API — sorting only the current page would leave page 1 sorted
// and page 2 unrelated, which looks correct in the UI and is not. These tests
// pin the URL-owned sort state, the accessibility contract, and the link-status
// column that deliberately has no sort control.

const { mockUseShareTokens } = vi.hoisted(() => ({ mockUseShareTokens: vi.fn() }));

vi.mock('@/hooks/use-admin', () => ({
  useShareTokens: (...args: unknown[]) => mockUseShareTokens(...args),
  useAdminRevokeShareToken: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAdminEmbedTokens: () => ({ data: undefined, isLoading: false }),
  useBulkRevokeEmbedTokens: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/hooks/use-document-title', () => ({ useDocumentTitle: vi.fn() }));

/** Surfaces the live URL so state->URL can be asserted, not just URL->state. */
function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

function lastCall() {
  return mockUseShareTokens.mock.calls.at(-1)?.[0] as Record<string, unknown>;
}

const TOKEN = {
  id: '44444444-4444-4444-8444-444444444444',
  map_id: '55555555-5555-4555-8555-555555555555',
  map_name: 'Parcels',
  token: 'abcd1234',
  is_active: true,
  expires_at: null,
  created_at: '2026-01-01T00:00:00Z',
  created_by: 'alice',
  embed_token_count: 0,
};

function renderPage(route = '/admin/shared-maps', total = 1) {
  mockUseShareTokens.mockReturnValue({
    data: { tokens: [TOKEN], total },
    isLoading: false,
    isError: false,
  });
  return render(
    <>
      <AdminSharedMapsPage />
      <LocationProbe />
    </>,
    { route },
  );
}

beforeEach(() => {
  mockUseShareTokens.mockReset();
});

describe('AdminSharedMapsPage sorting', () => {
  it('requests the historical created_at descending order by default', () => {
    renderPage();

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'desc' });
  });

  it('names the sortable header with its visible label plus the next action', () => {
    renderPage();

    // The accessible name must CONTAIN the visible label (WCAG 2.5.3) — an
    // aria-label would have replaced it.
    expect(
      screen.getByRole('button', { name: 'Map, sort ascending' }),
    ).toBeInTheDocument();
  });

  it('marks sort state with aria-sort on the th, not on the button', () => {
    renderPage('/admin/shared-maps?sort=map_name&order=desc');

    expect(screen.getByRole('columnheader', { name: /Map/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
    expect(screen.getByRole('columnheader', { name: /Creator/ })).toHaveAttribute(
      'aria-sort',
      'none',
    );
    // The active header now offers the opposite direction.
    expect(
      screen.getByRole('button', { name: 'Map, sort ascending' }),
    ).toBeInTheDocument();
  });

  it('sorts ascending on first activation and flips on the second', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /^Map,/ }));
    expect(lastCall()).toMatchObject({ sort: 'map_name', order: 'asc' });

    await user.click(screen.getByRole('button', { name: /^Map,/ }));
    expect(lastCall()).toMatchObject({ sort: 'map_name', order: 'desc' });
  });

  it('flips the default column to ascending on first activation', async () => {
    const user = userEvent.setup();
    renderPage();

    // Created is already the active DESCENDING sort, so activating it must
    // reverse rather than re-assert descending.
    await user.click(screen.getByRole('button', { name: /^Created/ }));

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'asc' });
  });

  it('sorts by the embed count, which the API orders as 0 not NULL', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /^Embeds/ }));

    expect(lastCall()).toMatchObject({ sort: 'embed_token_count', order: 'asc' });
  });

  it('is operable from the keyboard', async () => {
    const user = userEvent.setup();
    renderPage();

    const header = screen.getByRole('button', { name: /^Expires/ });
    header.focus();
    await user.keyboard('{Enter}');

    expect(lastCall()).toMatchObject({ sort: 'expires_at', order: 'asc' });
  });

  it('owns sort state in the URL', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /^Creator/ }));

    const search = screen.getByTestId('location').textContent ?? '';
    expect(new URLSearchParams(search).get('sort')).toBe('creator');
    expect(new URLSearchParams(search).get('order')).toBe('asc');
  });

  it('reads sort state back out of the URL', () => {
    renderPage('/admin/shared-maps?sort=expires_at&order=asc');

    expect(lastCall()).toMatchObject({ sort: 'expires_at', order: 'asc' });
  });

  it('falls back to the default for a sort field the API would refuse', () => {
    // link_status is the trap: it IS a visible column, but it is derived in
    // Python from is_active plus expires_at, so the API refuses it.
    renderPage('/admin/shared-maps?sort=link_status&order=sideways');

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'desc' });
  });

  it('composes sort with the status filter instead of replacing it', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Active' }));
    await user.click(screen.getByRole('button', { name: /^Map,/ }));

    expect(lastCall()).toMatchObject({ status: 'active', sort: 'map_name' });
  });

  it('returns to the first page when the ordering changes', async () => {
    const user = userEvent.setup();
    renderPage('/admin/shared-maps', 200);

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(lastCall()).toMatchObject({ skip: 50 });

    await user.click(screen.getByRole('button', { name: /^Map,/ }));
    // Page 3 of the old ordering names different rows under the new one.
    expect(lastCall()).toMatchObject({ skip: 0, sort: 'map_name' });
  });

  it('offers no sort control for the link-status column', () => {
    renderPage();

    // "Status" here is the derived link status, not a database column.
    const header = screen.getByRole('columnheader', { name: 'Status' });
    expect(within(header).queryByRole('button')).toBeNull();
    expect(header).not.toHaveAttribute('aria-sort');
  });
});
