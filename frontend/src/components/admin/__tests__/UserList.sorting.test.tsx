import { render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router';
import { UserList } from '../UserList';

const { mockUseUserList } = vi.hoisted(() => ({ mockUseUserList: vi.fn() }));

vi.mock('@/hooks/use-admin', () => ({
  useUserList: (...args: unknown[]) => mockUseUserList(...args),
  useApproveUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useRejectUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useDeactivateUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
}));

// Radix Select needs pointer-capture APIs jsdom does not implement; the
// sibling CardHeaderPatterns suite swaps in a native select for the same
// reason. The filter's own behaviour is covered there, not here.
vi.mock('../FilterSelect', () => ({
  FilterSelect: ({
    ariaLabel,
    value,
    onChange,
    options,
  }: {
    ariaLabel?: string;
    value: string;
    onChange: (value: string) => void;
    options: { value: string; label: string }[];
  }) => (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

vi.mock('../UserCreateDialog', () => ({ UserCreateDialog: () => null }));
vi.mock('../UserEditDialog', () => ({ UserEditDialog: () => null }));
vi.mock('../UserDeleteDialog', () => ({ UserDeleteDialog: () => null }));

/** Surfaces the live URL so state->URL can be asserted, not just URL->state. */
function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

function lastCall() {
  return mockUseUserList.mock.calls.at(-1)?.[0] as Record<string, unknown>;
}

function renderList(route = '/admin/users') {
  return render(
    <>
      <UserList />
      <LocationProbe />
    </>,
    { route },
  );
}

beforeEach(() => {
  mockUseUserList.mockReset();
  mockUseUserList.mockReturnValue({
    data: { users: [], total: 0 },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
});

describe('UserList sorting', () => {
  it('requests the historical created_at ascending order by default', () => {
    renderList();

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'asc' });
  });

  it('names the sortable header with its visible label plus the next action', () => {
    renderList();

    // The accessible name must CONTAIN the visible label (WCAG 2.5.3) — an
    // aria-label would have replaced it.
    expect(
      screen.getByRole('button', { name: 'Username, sort ascending' }),
    ).toBeInTheDocument();
  });

  it('marks sort state with aria-sort on the th, not on the button', () => {
    renderList('/admin/users?sort=username&order=desc');

    expect(screen.getByRole('columnheader', { name: /Username/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
    expect(screen.getByRole('columnheader', { name: /Email/ })).toHaveAttribute(
      'aria-sort',
      'none',
    );
    // The active header now offers the opposite direction.
    expect(
      screen.getByRole('button', { name: 'Username, sort ascending' }),
    ).toBeInTheDocument();
  });

  it('sorts ascending on first activation and flips on the second', async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole('button', { name: /^Username/ }));
    expect(lastCall()).toMatchObject({ sort: 'username', order: 'asc' });

    await user.click(screen.getByRole('button', { name: /^Username/ }));
    expect(lastCall()).toMatchObject({ sort: 'username', order: 'desc' });
  });

  it('flips the default column to descending on first activation', async () => {
    const user = userEvent.setup();
    renderList();

    // Created is already the active ascending sort, so activating it must
    // reverse rather than re-assert ascending.
    await user.click(screen.getByRole('button', { name: /^Created/ }));

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'desc' });
  });

  it('is operable from the keyboard', async () => {
    const user = userEvent.setup();
    renderList();

    const header = screen.getByRole('button', { name: /^Email/ });
    header.focus();
    await user.keyboard('{Enter}');

    expect(lastCall()).toMatchObject({ sort: 'email', order: 'asc' });
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
    renderList('/admin/users?sort=last_login_at&order=desc');

    expect(lastCall()).toMatchObject({ sort: 'last_login_at', order: 'desc' });
  });

  it('falls back to the default for a sort field the API would refuse', () => {
    renderList('/admin/users?sort=password_hash&order=sideways');

    expect(lastCall()).toMatchObject({ sort: 'created_at', order: 'asc' });
  });

  it('returns to the first page when the ordering changes', async () => {
    const user = userEvent.setup();
    mockUseUserList.mockReturnValue({
      data: { users: [], total: 100 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderList();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(lastCall()).toMatchObject({ skip: 20 });

    await user.click(screen.getByRole('button', { name: /^Username/ }));
    // Page 3 of the old ordering names different rows under the new one.
    expect(lastCall()).toMatchObject({ skip: 0, sort: 'username' });
  });

  it('composes sort with the status filter instead of replacing it', async () => {
    const user = userEvent.setup();
    renderList();

    await user.selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'pending');
    await user.click(screen.getByRole('button', { name: /^Username/ }));

    expect(lastCall()).toMatchObject({
      status: 'pending',
      sort: 'username',
      order: 'asc',
    });
  });

  it('offers no sort control for columns the API cannot order', () => {
    renderList();

    for (const label of ['Roles', 'File storage', 'Actions']) {
      const header = screen.getByRole('columnheader', { name: label });
      expect(within(header).queryByRole('button')).toBeNull();
      expect(header).not.toHaveAttribute('aria-sort');
    }
  });
});
