import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { MapsPage } from '../MapsPage';

vi.mock('@/hooks/use-permissions', () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock('@/stores/auth-store', () => ({
  useAuthStore: (selector: (value: { user: { id: string; roles: string[] }; token: string }) => unknown) =>
    selector({ user: { id: 'owner-id', roles: ['editor'] }, token: 'token' }),
}));
const useMaps = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-maps', () => ({
  useMaps,
  useDeleteMap: () => ({ mutate: vi.fn(), isPending: false }),
  useMapStories: () => ({ data: undefined }),
}));
vi.mock('@/components/maps/MapCreateDialog', () => ({ MapCreateDialog: () => null }));
vi.mock('@/hooks/use-document-title', () => ({ useDocumentTitle: vi.fn() }));
vi.mock('@/components/stories/StoryCreateDialog', () => ({
  StoryCreateDialog: ({ open }: { open: boolean }) => (open ? <div role="dialog">new story dialog</div> : null),
}));
vi.mock('@/components/stories/StoriesList', () => ({
  StoriesList: () => <div data-testid="stories-list">stories</div>,
}));

beforeEach(() => {
  useMaps.mockReset();
  useMaps.mockReturnValue({ data: { total: 0, maps: [] }, isLoading: false });
});

function SearchProbe() {
  return <span data-testid="search">{useLocation().search}</span>;
}

it('switches to the stories list and keeps the mode in the URL', async () => {
  const user = userEvent.setup();
  render(
    <>
      <MapsPage />
      <SearchProbe />
    </>,
    { route: '/maps' },
  );
  expect(screen.queryByTestId('stories-list')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Create your first map' })).toBeInTheDocument();

  await user.click(screen.getByRole('tab', { name: 'Stories' }));
  expect(screen.getByTestId('stories-list')).toBeInTheDocument();
  expect(screen.getByTestId('search')).toHaveTextContent('?type=stories');
  expect(screen.queryByRole('button', { name: /Create/ })).not.toBeInTheDocument();
  expect(useMaps).toHaveBeenLastCalledWith(expect.anything(), { enabled: false });
});

it('opens on the stories list from a link', () => {
  render(<MapsPage />, { route: '/maps?type=stories' });
  expect(screen.getByRole('tab', { name: 'Stories' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByTestId('stories-list')).toBeInTheDocument();
  expect(useMaps).not.toHaveBeenCalledWith(expect.anything(), { enabled: true });
});

it('offers New story on the stories tab', async () => {
  const user = userEvent.setup();
  render(<MapsPage />, { route: '/maps?type=stories' });
  await user.click(screen.getByRole('button', { name: 'New story' }));
  expect(screen.getByRole('dialog')).toHaveTextContent('new story dialog');
});
