import { render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { MapsPage } from '../MapsPage';

const state = vi.hoisted(() => ({ canEdit: false, isEditor: false, id: 'owner-id', username: 'owner', roles: ['viewer'], mutate: vi.fn() }));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: (capability: string) => capability === 'edit_metadata' && state.canEdit }),
}));
vi.mock('@/stores/auth-store', () => ({
  useAuthStore: (selector: (value: { isEditor: () => boolean; user: { id: string; username: string; roles: string[] } }) => unknown) => selector({
    isEditor: () => state.isEditor,
    user: { id: state.id, username: state.username, roles: state.roles },
  }),
}));
vi.mock('@/hooks/use-maps', () => ({
  useMaps: () => ({
    data: { total: 1, maps: [{ id: 'owned-map', name: 'My map', visibility: 'private', layer_count: 0, created_by: 'owner-id', created_by_username: 'owner', created_at: '2026-01-01', updated_at: '2026-01-01' }] },
    isLoading: false,
  }),
  useDeleteMap: () => ({ mutate: state.mutate, isPending: false }),
}));
vi.mock('@/components/maps/hooks/use-map-thumbnail', () => ({ useMapThumbnail: () => null }));
vi.mock('@/components/maps/MapCreateDialog', () => ({ MapCreateDialog: () => null }));
vi.mock('@/hooks/use-document-title', () => ({ useDocumentTitle: vi.fn() }));

beforeEach(() => {
  state.canEdit = false;
  state.isEditor = false;
  state.username = 'owner';
  state.id = 'owner-id';
  state.roles = ['viewer'];
  state.mutate.mockReset();
  localStorage.clear();
});

it.each(['list', 'grid'])('hides deletion of another owner’s map even with the same username in %s view', async (view) => {
  state.canEdit = true;
  state.id = 'another-user-id';
  const user = userEvent.setup();
  render(<MapsPage />);
  if (view === 'grid') await user.click(screen.getByRole('radio', { name: 'Grid view' }));
  expect(screen.queryByRole('button', { name: 'Delete map' })).not.toBeInTheDocument();
});

it.each(['list', 'grid'])('allows an authorized admin to delete another owner’s map in %s view', async (view) => {
  state.canEdit = true;
  state.username = 'administrator';
  state.id = 'admin-id';
  state.roles = ['admin'];
  state.isEditor = true;
  const user = userEvent.setup();
  render(<MapsPage />);
  if (view === 'grid') await user.click(screen.getByRole('radio', { name: 'Grid view' }));
  await user.click(screen.getByRole('button', { name: 'Delete map' }));
  expect(screen.getByRole('alertdialog')).toBeInTheDocument();
});

it('keeps deletion available to an owner whose username changed', async () => {
  state.canEdit = true;
  state.username = 'renamed-owner';
  render(<MapsPage />);
  expect(screen.getByRole('button', { name: 'Delete map' })).toBeInTheDocument();
});

it.each(['list', 'grid'])('allows a custom permission holder to confirm deletion in %s view', async (view) => {
  state.canEdit = true;
  const user = userEvent.setup();
  render(<MapsPage />);
  if (view === 'grid') await user.click(screen.getByRole('radio', { name: 'Grid view' }));
  expect(screen.getByRole('button', { name: 'Create Map' })).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: 'Visibility' })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Delete map' }));
  const dialog = screen.getByRole('alertdialog');
  expect(within(dialog).getByText('My map')).toBeInTheDocument();
  await user.click(within(dialog).getByRole('button', { name: 'Delete' }));
  expect(state.mutate).toHaveBeenCalledWith('owned-map', expect.objectContaining({ onSuccess: expect.any(Function) }));
});

it.each(['list', 'grid'])('hides mutations when an editor lacks the capability in %s view', async (view) => {
  state.isEditor = true;
  state.roles = ['editor'];
  const user = userEvent.setup();
  render(<MapsPage />);
  if (view === 'grid') await user.click(screen.getByRole('radio', { name: 'Grid view' }));
  expect(screen.queryByRole('button', { name: 'Create Map' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Delete map' })).not.toBeInTheDocument();
});
