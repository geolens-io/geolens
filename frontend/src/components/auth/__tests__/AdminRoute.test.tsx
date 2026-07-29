import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import {
  AdminCapabilityRoute,
  AdminIndexRoute,
  AdminRoute,
  AdminSettingsRoute,
} from '../AdminRoute';

const permissionState = vi.hoisted(() => ({
  manageUsers: false,
  manageSettings: false,
  manageTenants: false,
  isLoading: false,
}));

const editionState = vi.hoisted(() => ({
  isMultiTenant: false,
  isLoading: false,
}));

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: (capability: string) =>
      capability === 'manage_users'
        ? permissionState.manageUsers
        : capability === 'manage_settings'
          ? permissionState.manageSettings
          : capability === 'manage_tenants' && permissionState.manageTenants,
    isLoading: permissionState.isLoading,
    permissions: {},
  }),
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({
    edition: 'community',
    features: [],
    isEnterprise: false,
    isMultiTenant: editionState.isMultiTenant,
    isLoading: editionState.isLoading,
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

// fix(#817): the settings/config-ops APIs require manage_settings in
// single-tenant but manage_tenants in multi-tenant — the route gate must
// switch the same way so per-tenant admins don't land on tabs whose every
// request 403s.
describe('AdminSettingsRoute', () => {
  function renderSettingsRoute() {
    return render(
      <MemoryRouter initialEntries={['/admin/settings/ai']}>
        <Routes>
          <Route path="/admin" element={<div>Admin Index</div>} />
          <Route element={<AdminSettingsRoute />}>
            <Route path="/admin/settings/ai" element={<div>Settings Content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
  }

  beforeEach(() => {
    permissionState.manageUsers = false;
    permissionState.manageSettings = false;
    permissionState.manageTenants = false;
    permissionState.isLoading = false;
    editionState.isMultiTenant = false;
    editionState.isLoading = false;
  });

  it('single-tenant: admits manage_settings', () => {
    permissionState.manageSettings = true;
    renderSettingsRoute();

    expect(screen.getByText('Settings Content')).toBeInTheDocument();
  });

  it('multi-tenant: redirects a manage_settings-only per-tenant admin to the admin index', () => {
    editionState.isMultiTenant = true;
    permissionState.manageSettings = true;
    renderSettingsRoute();

    expect(screen.getByText('Admin Index')).toBeInTheDocument();
    expect(screen.queryByText('Settings Content')).not.toBeInTheDocument();
  });

  it('multi-tenant: admits manage_tenants', () => {
    editionState.isMultiTenant = true;
    permissionState.manageTenants = true;
    renderSettingsRoute();

    expect(screen.getByText('Settings Content')).toBeInTheDocument();
  });

  it('waits for the edition to load before deciding', () => {
    editionState.isLoading = true;
    permissionState.manageSettings = true;
    renderSettingsRoute();

    expect(screen.queryByText('Settings Content')).not.toBeInTheDocument();
    expect(screen.queryByText('Admin Index')).not.toBeInTheDocument();
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
