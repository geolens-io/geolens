import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { Navbar } from '../Navbar';

const permissions = vi.hoisted(() => ({ edit: false }));
vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { username: 'Catalog reader' }, logout: vi.fn() }),
}));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: (capability: string) => capability === 'edit_metadata' && permissions.edit }),
}));
vi.mock('@/hooks/use-settings-admin', () => ({ useSettingsAdmin: () => false }));
vi.mock('@/hooks/use-settings', () => ({ useFeatureFlags: () => ({ data: {} }) }));
vi.mock('@/components/create/CreateDatasetDialog', () => ({ CreateDatasetDialog: () => null }));
vi.mock('@/components/collections/CollectionCreateDialog', () => ({ CollectionCreateDialog: () => null }));
vi.mock('@/components/maps/MapCreateDialog', () => ({ MapCreateDialog: ({ open }: { open: boolean }) => open ? <div>Map creation form</div> : null }));
vi.mock('@/components/import/VrtCreateDialog', () => ({ VrtCreateDialog: () => null }));

afterEach(() => { permissions.edit = false; });

it('does not offer map creation without the effective capability on either navigation', async () => {
  const user = userEvent.setup();
  render(<Navbar />);
  expect(screen.queryByRole('button', { name: 'Create' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Menu' }));
  expect(screen.queryByRole('button', { name: 'Map', exact: true })).not.toBeInTheDocument();
});

it.each(['desktop', 'mobile'])('opens map creation with the capability on %s', async (surface) => {
  permissions.edit = true;
  const user = userEvent.setup();
  render(<Navbar />);
  if (surface === 'desktop') {
    await user.click(screen.getByRole('button', { name: 'Create' }));
    await user.click(screen.getByRole('menuitem', { name: 'Map', exact: true }));
  } else {
    await user.click(screen.getByRole('button', { name: 'Menu' }));
    await user.click(screen.getByRole('button', { name: 'Map', exact: true }));
  }
  expect(screen.getByText('Map creation form')).toBeInTheDocument();
});
