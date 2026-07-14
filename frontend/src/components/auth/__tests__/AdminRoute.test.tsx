import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import {
  AdminCapabilityRoute,
  AdminIndexRoute,
  AdminRoute,
} from '../AdminRoute';

const permissionState = vi.hoisted(() => ({
  manageUsers: false,
  manageSettings: false,
  isLoading: false,
}));

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: (capability: string) =>
      capability === 'manage_users'
        ? permissionState.manageUsers
        : capability === 'manage_settings' && permissionState.manageSettings,
    isLoading: permissionState.isLoading,
    permissions: {},
  }),
}));

function renderAdminRoute(initialRoute = '/admin') {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <Routes>
        <Route path="/" element={<div>App Home</div>} />
        <Route path="/admin" element={<AdminRoute />}>
          <Route index element={<div>Admin Content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('AdminRoute', () => {
  beforeEach(() => {
    permissionState.manageUsers = false;
    permissionState.manageSettings = false;
    permissionState.isLoading = false;
  });

  it('redirects a user with no admin capability to the application', () => {
    renderAdminRoute();

    expect(screen.getByText('App Home')).toBeInTheDocument();
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument();
  });

  it('renders admin content for manage_users', () => {
    permissionState.manageUsers = true;
    renderAdminRoute();

    expect(screen.getByText('Admin Content')).toBeInTheDocument();
  });

  it('renders admin content for manage_settings', () => {
    permissionState.manageSettings = true;
    renderAdminRoute();

    expect(screen.getByText('Admin Content')).toBeInTheDocument();
  });
});

describe('AdminCapabilityRoute', () => {
  function renderCapabilityRoute(capability: 'manage_users' | 'manage_settings') {
    return render(
      <MemoryRouter initialEntries={['/admin/target']}>
        <Routes>
          <Route path="/admin" element={<div>Admin Index</div>} />
          <Route element={<AdminCapabilityRoute capability={capability} />}>
            <Route path="/admin/target" element={<div>Capability Content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
  }

  beforeEach(() => {
    permissionState.manageUsers = false;
    permissionState.manageSettings = false;
    permissionState.isLoading = false;
  });

  it('renders the route when its specific capability is granted', () => {
    permissionState.manageSettings = true;
    renderCapabilityRoute('manage_settings');

    expect(screen.getByText('Capability Content')).toBeInTheDocument();
  });

  it('redirects to the admin index when the specific capability is denied', () => {
    permissionState.manageUsers = true;
    renderCapabilityRoute('manage_settings');

    expect(screen.getByText('Admin Index')).toBeInTheDocument();
  });
});

describe('AdminIndexRoute', () => {
  function renderIndex() {
    return render(
      <MemoryRouter initialEntries={['/admin']}>
        <Routes>
          <Route path="/admin" element={<AdminIndexRoute />} />
          <Route path="/admin/overview" element={<div>User Admin</div>} />
          <Route path="/admin/audit" element={<div>Settings Admin</div>} />
          <Route path="/" element={<div>App Home</div>} />
        </Routes>
      </MemoryRouter>,
    );
  }

  beforeEach(() => {
    permissionState.manageUsers = false;
    permissionState.manageSettings = false;
    permissionState.isLoading = false;
  });

  it('prefers the user-management overview when available', () => {
    permissionState.manageUsers = true;
    permissionState.manageSettings = true;
    renderIndex();
    expect(screen.getByText('User Admin')).toBeInTheDocument();
  });

  it('lands settings-only administrators on the audit page', () => {
    permissionState.manageSettings = true;
    renderIndex();
    expect(screen.getByText('Settings Admin')).toBeInTheDocument();
  });
});
