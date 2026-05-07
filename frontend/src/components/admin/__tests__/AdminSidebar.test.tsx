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

// Phase 279 ADMIN-03 (M-03): server-driven enterprise-tab list. Defaults to
// the canonical post-279 set so existing tests (which expect appearance to be
// hidden in community) keep passing without changes. Per-test overrides via
// `mockReturnValueOnce` exercise the loading / drift / extension scenarios.
const useEnterpriseOnlyTabsMock = vi.fn<() => { data: { tabs: string[] } | undefined }>(() => ({
  data: { tabs: ['branding', 'appearance'] },
}));

vi.mock('@/hooks/use-settings', () => ({
  useEnterpriseOnlyTabs: () => useEnterpriseOnlyTabsMock(),
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
        'admin:settings.tabs.appearance': 'Appearance',
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

// ---------------------------------------------------------------------------
// Phase 279 Plan 02 — Server-driven enterprise-tab list (ADMIN-03 / M-03)
//
// Verifies the AdminSidebar reads the canonical enterprise-only Settings tab
// keys from the server-driven `useEnterpriseOnlyTabs` hook and falls back to
// the local FALLBACK_ENTERPRISE_ONLY_TABS constant when the API is loading
// or has errored. This eliminates the prior drift between backend
// `_ENTERPRISE_ONLY_TABS` and frontend hardcoded enterpriseOnly flags.
// ---------------------------------------------------------------------------

describe('AdminSidebar server-driven enterpriseOnly tabs (Phase 279 ADMIN-03)', () => {
  it('hides server-marked enterprise tabs in community edition', () => {
    // Default mock: community + canonical {branding, appearance}.
    renderSidebar();
    // The "Appearance" tab is enterpriseOnly per the server set — must NOT
    // render in community.
    expect(screen.queryByText('Appearance')).toBeNull();
    expect(document.querySelector('a[href="/admin/settings/appearance"]')).toBeNull();
    // Non-enterprise tabs must still render.
    expect(screen.getByText('General')).toBeInTheDocument();
    expect(screen.getByText('Auth')).toBeInTheDocument();
  });

  it('shows server-marked enterprise tabs in enterprise edition', () => {
    useEditionMock.mockReturnValueOnce({
      isEnterprise: true,
      edition: 'enterprise',
      isLoading: false,
    });
    renderSidebar();
    // "Appearance" is enterpriseOnly but enterprise edition sees ALL tabs.
    expect(screen.getByText('Appearance')).toBeInTheDocument();
    expect(document.querySelector('a[href="/admin/settings/appearance"]')).not.toBeNull();
  });

  it('falls back to local defaults when the API hook is loading (data undefined)', () => {
    // Simulate: hook is still loading, data is undefined. Sidebar must still
    // hide enterprise tabs in community edition by consulting
    // FALLBACK_ENTERPRISE_ONLY_TABS = ['branding', 'appearance'].
    useEnterpriseOnlyTabsMock.mockReturnValueOnce({ data: undefined });
    renderSidebar();
    // No flash of forbidden UI — Appearance still hidden via fallback.
    expect(screen.queryByText('Appearance')).toBeNull();
    expect(document.querySelector('a[href="/admin/settings/appearance"]')).toBeNull();
  });

  it('respects newly-added server-marked enterprise tabs (server-driven extensibility)', () => {
    // Simulate the server adding a hypothetical "permissions" tab to the
    // enterprise-only set without a frontend redeploy. The sidebar must
    // hide it without code changes.
    useEnterpriseOnlyTabsMock.mockReturnValueOnce({
      data: { tabs: ['branding', 'appearance', 'permissions'] },
    });
    renderSidebar();
    // Newly-marked enterprise tab disappears in community edition.
    expect(screen.queryByText('Permissions')).toBeNull();
    expect(document.querySelector('a[href="/admin/settings/permissions"]')).toBeNull();
    // Other community tabs still render.
    expect(screen.getByText('General')).toBeInTheDocument();
  });
});
