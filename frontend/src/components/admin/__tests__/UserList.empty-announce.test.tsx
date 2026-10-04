import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { UserList } from '../UserList';

const { mockUseUserList } = vi.hoisted(() => ({ mockUseUserList: vi.fn() }));

vi.mock('@/hooks/use-admin', () => ({
  useUserList: (...args: unknown[]) => mockUseUserList(...args),
  useApproveUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useRejectUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useDeactivateUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
}));

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
    <select aria-label={ariaLabel} value={value} onChange={(event) => onChange(event.target.value)}>
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

function setQuery(isFetching: boolean) {
  mockUseUserList.mockReturnValue({
    data: { users: [], total: 0 },
    isLoading: false,
    isFetching,
    error: null,
    refetch: vi.fn(),
  });
}

function statusTexts() {
  return screen.queryAllByRole('status').map((el) => el.textContent ?? '');
}

describe('UserList empty-state announcement', () => {
  beforeEach(() => {
    mockUseUserList.mockReset();
    setQuery(false);
  });

  it('announces a second empty filter once it settles and reads nothing stale while fetching', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<UserList />, { route: '/admin/users' });

    const [statusSelect] = screen.getAllByRole('combobox');
    const options = Array.from((statusSelect as HTMLSelectElement).options).map((o) => o.value);
    const first = options.find((v) => v !== '') as string;
    const second = options.find((v) => v !== '' && v !== first) as string;

    await user.selectOptions(statusSelect, first);
    await waitFor(() => expect(statusTexts().some((text) => text.includes('No users'))).toBe(true));

    // keepPreviousData: the old empty page stays mounted while the next query loads.
    setQuery(true);
    await user.selectOptions(statusSelect, second);
    expect(statusTexts().some((text) => text.includes('No users'))).toBe(false);

    setQuery(false);
    rerender(<UserList />);
    await waitFor(() => expect(statusTexts().some((text) => text.includes('No users'))).toBe(true));
  });
});
