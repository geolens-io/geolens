import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SidebarProvider } from '@/components/ui/sidebar';
import { AdminSidebar } from '../AdminSidebar';

vi.mock('@/hooks/use-admin', () => ({
  usePendingCount: () => ({ data: 0 }),
  useFailedJobCount: () => ({ data: 0 }),
}));

// Default: community edition. Individual tests can override per-call via
// `mockReturnValueOnce` to simulate enterprise. Stored on the mock so the
// SAML-gating suite below can flip it without re-mocking the whole module.
const useEditionMock = vi.fn(() => ({
  isEnterprise: false,
  edition: 'community',
  isLoading: false,
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => useEditionMock(),
}));

// i18n returns the key by default in tests, so we match on i18n keys' last segment
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      // Return human-readable labels from keys
      const labels: Record<string, string> = {
        'adminNav.admin': 'Admin',
        'adminNav.overview': 'Overview',
        'adminNav.operations': 'Operations',
        'adminNav.users': 'Users',
        'adminNav.jobs': 'Jobs',
        'adminNav.auditLog': 'Audit Log',
        'adminNav.sharedMaps': 'Shared Maps',
        'adminNav.saml': 'SAML SSO',
        'adminNav.settings': 'Settings',
        'adminNav.configOps': 'Config Ops',
        'adminNav.backToApp': 'Back to App',
        'admin:settings.tabs.general': 'General',
        'admin:settings.tabs.auth': 'Auth',
        'admin:settings.tabs.ai': 'AI',
        'admin:settings.tabs.network': 'Network',
        'admin:settings.tabs.storage': 'Storage',
        'admin:settings.tabs.map': 'Map',
        'admin:settings.tabs.permissions': 'Permissions',
      };
      return labels[key] ?? key;
    },
  }),
}));

// SidebarProvider uses useIsMobile which calls window.matchMedia
beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function renderSidebar(path = '/admin/overview') {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <SidebarProvider>
          <AdminSidebar />
        </SidebarProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AdminSidebar', () => {
  it('renders overview, operations, and settings nav items', () => {
    renderSidebar();
    // Overview
    expect(screen.getByText('Overview')).toBeInTheDocument();
    // Operations
    expect(screen.getByText('Users')).toBeInTheDocument();
    expect(screen.getByText('Jobs')).toBeInTheDocument();
    expect(screen.getByText('Audit Log')).toBeInTheDocument();
    expect(screen.getByText('Shared Maps')).toBeInTheDocument();
    // Settings
    expect(screen.getByText('General')).toBeInTheDocument();
    expect(screen.getByText('Auth')).toBeInTheDocument();
    expect(screen.getByText('AI')).toBeInTheDocument();
    expect(screen.getByText('Network')).toBeInTheDocument();
    expect(screen.getByText('Storage')).toBeInTheDocument();
    expect(screen.getByText('Map')).toBeInTheDocument();
    expect(screen.getByText('Permissions')).toBeInTheDocument();
    expect(screen.getByText('Config Ops')).toBeInTheDocument();
  });

  it('renders section group labels for Operations and Settings', () => {
    renderSidebar();
    expect(screen.getByText('Operations')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('routes General to /admin/settings/general', () => {
    renderSidebar();
    const link = screen.getByText('General').closest('a');
    expect(link).toHaveAttribute('href', '/admin/settings/general');
  });

  it('routes Auth to /admin/settings/auth', () => {
    renderSidebar();
    const link = screen.getByText('Auth').closest('a');
    expect(link).toHaveAttribute('href', '/admin/settings/auth');
  });

  it('routes Users to /admin/users', () => {
    renderSidebar();
    const link = screen.getByText('Users').closest('a');
    expect(link).toHaveAttribute('href', '/admin/users');
  });

  it('renders Back to App footer link', () => {
    renderSidebar();
    const link = screen.getByText('Back to App').closest('a');
    expect(link).toHaveAttribute('href', '/');
  });
});

// ---------------------------------------------------------------------------
// Phase 217 Plan 04 Task 02 — SAML nav gating (217-04-02 / SAML-10)
//
// Verifies the three-layer defense for SAML enterprise gating
// (T-217-04-EDITION): the sidebar nav item is HIDDEN in community mode
// (`isEnterprise=false`) and VISIBLE in enterprise mode (`isEnterprise=true`).
// The companion checks live in:
//   - AdminSamlPage.tsx (page-level <Navigate to="/admin"> redirect)
//   - backend/tests/test_saml_overlay.py::test_saml_endpoint_404_in_community
// ---------------------------------------------------------------------------

describe('AdminSidebar SAML gating (Phase 217 SAML-10)', () => {
  it('hides SAML nav item in community edition', () => {
    useEditionMock.mockReturnValueOnce({
      isEnterprise: false,
      edition: 'community',
      isLoading: false,
    });
    renderSidebar();
    // The "SAML SSO" label must NOT render and no <a> should target /admin/saml.
    expect(screen.queryByText('SAML SSO')).toBeNull();
    expect(document.querySelector('a[href="/admin/saml"]')).toBeNull();
  });

  it('shows SAML nav item in enterprise edition', () => {
    useEditionMock.mockReturnValueOnce({
      isEnterprise: true,
      edition: 'enterprise',
      isLoading: false,
    });
    renderSidebar();
    // Both the human-readable label and the link href must be present.
    expect(screen.getByText('SAML SSO')).toBeInTheDocument();
    const link = document.querySelector('a[href="/admin/saml"]');
    expect(link).not.toBeNull();
  });
});
