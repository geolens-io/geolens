import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { Navbar } from '../Navbar';

const permissions = vi.hoisted(() => ({ edit: false, datasetEditing: false }));
vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { username: 'Catalog reader' }, logout: vi.fn() }),
}));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: (capability: string) => capability === 'edit_metadata' && permissions.edit }),
}));
vi.mock('@/hooks/use-settings-admin', () => ({ useSettingsAdmin: () => false }));
vi.mock('@/hooks/use-settings', () => ({ useFeatureFlags: () => ({ data: { enable_dataset_editing: permissions.datasetEditing } }) }));
vi.mock('@/components/create/CreateDatasetDialog', () => ({ CreateDatasetDialog: () => null }));
vi.mock('@/components/collections/CollectionCreateDialog', () => ({ CollectionCreateDialog: () => null }));
vi.mock('@/components/maps/MapCreateDialog', () => ({ MapCreateDialog: ({ open }: { open: boolean }) => open ? <div>Map creation form</div> : null }));
vi.mock('@/components/import/VrtCreateDialog', () => ({ VrtCreateDialog: () => null }));

afterEach(() => { permissions.edit = false; permissions.datasetEditing = false; });

it('does not offer map creation without the effective capability on either navigation', async () => {
  const user = userEvent.setup();
  render(<Navbar />);
  expect(screen.queryByRole('button', { name: 'Create' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Menu' }));
  expect(screen.queryByRole('button', { name: 'Map' })).not.toBeInTheDocument();
});

it.each(['desktop', 'mobile'])('opens map creation with the capability on %s', async (surface) => {
  permissions.edit = true;
  const user = userEvent.setup();
  render(<Navbar />);
  if (surface === 'desktop') {
    await user.click(screen.getByRole('button', { name: 'Create' }));
    await user.click(screen.getByRole('menuitem', { name: 'Map' }));
  } else {
    await user.click(screen.getByRole('button', { name: 'Menu' }));
    await user.click(screen.getByRole('button', { name: 'Map' }));
  }
  expect(screen.getByText('Map creation form')).toBeInTheDocument();
});

it('does not offer dataset creation to a viewer even when dataset editing is enabled', async () => {
  permissions.datasetEditing = true;
  const user = userEvent.setup();
  render(<Navbar />);
  expect(screen.queryByRole('button', { name: 'Create' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Menu' }));
  expect(screen.queryByRole('button', { name: 'Dataset' })).not.toBeInTheDocument();
});

it('offers dataset creation with the capability and dataset editing enabled', async () => {
  permissions.edit = true;
  permissions.datasetEditing = true;
  const user = userEvent.setup();
  render(<Navbar />);
  await user.click(screen.getByRole('button', { name: 'Create' }));
  expect(screen.getByRole('menuitem', { name: 'Dataset' })).toBeInTheDocument();
});
