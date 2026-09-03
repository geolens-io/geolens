import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SidebarProvider } from '@/components/ui/sidebar';
import { AdminSidebar } from '../AdminSidebar';
import enCommon from '@/i18n/locales/en/common.json';
import esCommon from '@/i18n/locales/es/common.json';
import frCommon from '@/i18n/locales/fr/common.json';
import deCommon from '@/i18n/locales/de/common.json';

const counts = vi.hoisted(() => ({ users: 0, failed: 0, audit: 0, published: 0 }));
const permissionState = vi.hoisted(() => ({ manageUsers: true, manageSettings: true }));
const countHookEnabled = vi.hoisted(() => ({
  users: true,
  failed: true,
  audit: true,
  published: true,
}));

vi.mock('@/hooks/use-admin', () => ({
  useUserCount: (enabled: boolean) => {
    countHookEnabled.users = enabled;
    return { data: counts.users };
  },
  useFailedJobCount: (enabled: boolean) => {
    countHookEnabled.failed = enabled;
    return { data: counts.failed };
  },
  useAuditLogCount: (enabled: boolean) => {
    countHookEnabled.audit = enabled;
    return { data: counts.audit };
  },
  usePublishedMapCount: (enabled: boolean) => {
    countHookEnabled.published = enabled;
    return { data: counts.published };
  },
}));

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: (capability: string) =>
      capability === 'manage_users'
        ? permissionState.manageUsers
        : capability === 'manage_settings' && permissionState.manageSettings,
    isLoading: false,
    permissions: {},
  }),
}));

// Default: community edition. Individual tests can override per-call via
// `mockReturnValueOnce` to simulate enterprise. Stored on the mock so the
// SAML-gating suite below can flip it without re-mocking the whole module.
const useEditionMock = vi.fn(() => ({
  isEnterprise: false,
  edition: 'community',
  isMultiTenant: false,
  isLoading: false,
  isResolved: true,
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => useEditionMock(),
}));

// Phase 279 ADMIN-03 (M-03): server-driven enterprise-tab list. Defaults to
// the canonical post-279 set so existing tests (which expect appearance to be
// hidden in community) keep passing without changes. Per-test overrides via
// `mockReturnValueOnce` exercise the loading / drift / extension scenarios.
const useEnterpriseOnlyTabsMock = vi.fn<(_options?: { enabled?: boolean }) => { data: { tabs: string[] } | undefined }>(() => ({
  data: { tabs: ['branding', 'appearance'] },
}));

vi.mock('@/hooks/use-settings', () => ({
  useEnterpriseOnlyTabs: (options?: { enabled?: boolean }) => useEnterpriseOnlyTabsMock(options),
}));

// i18n returns the key by default in tests, so we match on i18n keys' last segment
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: number }) => {
      // fix(#1185): the failed-jobs label is the sidebar's only plural key.
      // Resolve it the way i18next would so the assertions below read the
      // rendered copy rather than a bare key. `EN_ADMIN_NAV` below pins these
      // strings against the real bundle.
      if (key === 'adminNav.failedJobs') {
        const count = options?.count ?? 0;
        return count === 1 ? `${count} failed job` : `${count} failed jobs`;
      }
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

beforeEach(() => {
  counts.users = 0;
  counts.failed = 0;
  counts.audit = 0;
  counts.published = 0;
  permissionState.manageUsers = true;
  permissionState.manageSettings = true;
  useEnterpriseOnlyTabsMock.mockClear();
});

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

  it('shows only user-management routes and disables settings queries for a user manager', () => {
    permissionState.manageSettings = false;
    renderSidebar();

    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('Users')).toBeInTheDocument();
    expect(screen.getByText('Jobs')).toBeInTheDocument();
    expect(screen.getByText('Shared Maps')).toBeInTheDocument();
    expect(screen.queryByText('Audit Log')).not.toBeInTheDocument();
    expect(screen.queryByText('General')).not.toBeInTheDocument();
    expect(countHookEnabled.audit).toBe(false);
    expect(countHookEnabled.users).toBe(true);
    expect(useEnterpriseOnlyTabsMock).toHaveBeenCalledWith({ enabled: false });
  });

  it('shows only settings routes and disables user-management queries for a settings manager', () => {
    permissionState.manageUsers = false;
    renderSidebar();

    expect(screen.queryByText('Overview')).not.toBeInTheDocument();
    expect(screen.queryByText('Users')).not.toBeInTheDocument();
    expect(screen.queryByText('Jobs')).not.toBeInTheDocument();
    expect(screen.queryByText('Shared Maps')).not.toBeInTheDocument();
    expect(screen.getByText('Audit Log')).toBeInTheDocument();
    expect(screen.getByText('General')).toBeInTheDocument();
    expect(countHookEnabled.audit).toBe(true);
    expect(countHookEnabled.users).toBe(false);
    expect(countHookEnabled.failed).toBe(false);
    expect(countHookEnabled.published).toBe(false);
    expect(useEnterpriseOnlyTabsMock).toHaveBeenCalledWith({ enabled: true });
  });

  // fix(#817): the settings/config-ops APIs require manage_tenants in
  // multi-tenant mode — a manage_settings-only per-tenant admin must not see
  // the Settings group (every request behind those links 403s). Audit Log
  // stays manage_settings in BOTH modes.
  //
  // fix(#1778): SAML calls the same mode-aware /settings/oauth-providers/
  // API, so it must follow the Settings group here too, not Audit Log — a
  // manage_settings-only per-tenant admin saw the SAML nav item and the
  // route admitted them, but every SAML request 403'd (the exact drift #817
  // fixed for the Settings tabs).
  it('multi-tenant: hides the Settings group AND SAML for a manage_settings-only admin', () => {
    const multiTenant = {
      isEnterprise: true,
      edition: 'enterprise',
      isMultiTenant: true,
      isLoading: false,
      isResolved: true,
    };
    // Two queued values: AdminSidebar's own useEdition call, then the
    // useSettingsAdmin hook's internal call (canAdminSettings is computed
    // once and reused for both the Settings group and the SAML item).
    useEditionMock
      .mockReturnValueOnce(multiTenant as never)
      .mockReturnValueOnce(multiTenant as never);
    renderSidebar();

    expect(screen.queryByText('General')).toBeNull();
    expect(screen.queryByText('Config Ops')).toBeNull();
    expect(screen.queryByText('SAML SSO')).toBeNull();
    expect(document.querySelector('a[href="/admin/saml"]')).toBeNull();
    expect(useEnterpriseOnlyTabsMock).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByText('Audit Log')).toBeInTheDocument();
  });

  it('shows total count badges and caps large counts at 999+ (#347 (ADM-02))', () => {
    counts.users = 62;
    counts.audit = 1500;
    counts.published = 10;
    counts.failed = 0; // hidden when 0
    renderSidebar();
    expect(screen.getByText('62')).toBeInTheDocument();
    expect(screen.getByText('999+')).toBeInTheDocument();
    expect(screen.getByText('10')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// fix(#1185): the Jobs badge counts FAILED jobs while every sibling badge
// counts the total behind its list, so a bare number read as a broken total
// (badge 3, list 200). It must render as an alert: destructive colors, a
// spoken "N failed jobs" label instead of a naked digit, and a click target
// pre-filtered to status=failed so the number clicked equals the list landed
// on. At zero there is no badge and the row links to the unfiltered list.
// ---------------------------------------------------------------------------

function badges() {
  return Array.from(document.querySelectorAll('[data-slot="sidebar-menu-badge"]'));
}

// Located by POSITION (the badge in the Jobs row), not by its copy — otherwise
// the styling assertions below would silently depend on the spoken label.
function failedBadge() {
  const row = screen.getByText('Jobs').closest('[data-slot="sidebar-menu-item"]');
  return row?.querySelector('[data-slot="sidebar-menu-badge"]') ?? undefined;
}

describe('AdminSidebar failed-jobs alert badge (#1185)', () => {
  it('renders the failed count in destructive colors, unlike the total badges', () => {
    counts.failed = 3;
    counts.users = 62;
    renderSidebar();

    const failed = failedBadge();
    expect(failed).toBeDefined();
    expect(failed?.className).toContain('text-destructive');
    expect(failed?.className).toContain('bg-destructive/10');
    // The hover and active variants have to be overridden too, or the badge
    // reverts to the sidebar accent color on the active route. `cn()` must
    // drop the base colors rather than leave both in the attribute — equal
    // specificity would otherwise make the winner a stylesheet-order accident.
    expect(failed?.className).toContain('peer-data-[active=true]/menu-button:text-destructive');
    expect(failed?.className).toContain('peer-hover/menu-button:text-destructive');
    expect(failed?.className).not.toContain('text-sidebar-foreground');
    expect(failed?.className).not.toContain('text-sidebar-accent-foreground');

    const users = badges().find((el) => el.textContent === '62');
    expect(users).toBeDefined();
    expect(users?.className).not.toContain('destructive');
  });

  it('speaks the badge as "N failed jobs" and hides the bare digits', () => {
    counts.failed = 3;
    renderSidebar();

    const spoken = screen.getByText('3 failed jobs');
    expect(spoken).toHaveClass('sr-only');
    // The visible digits must not be announced twice.
    expect(screen.getByText('3')).toHaveAttribute('aria-hidden', 'true');
  });

  it('uses the singular form for a single failed job', () => {
    counts.failed = 1;
    renderSidebar();
    expect(screen.getByText('1 failed job')).toBeInTheDocument();
  });

  it('keeps the capped visible count while speaking the true count', () => {
    counts.failed = 1500;
    renderSidebar();
    expect(screen.getByText('999+')).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByText('1500 failed jobs')).toBeInTheDocument();
  });

  it('points Jobs at the failed-filtered list while the badge is showing', () => {
    counts.failed = 3;
    renderSidebar();
    expect(screen.getByText('Jobs').closest('a')).toHaveAttribute(
      'href',
      '/admin/jobs?status=failed',
    );
  });

  it('points Jobs at the unfiltered list and renders no badge at zero', () => {
    counts.failed = 0;
    renderSidebar();
    expect(screen.getByText('Jobs').closest('a')).toHaveAttribute('href', '/admin/jobs');
    expect(failedBadge()).toBeUndefined();
  });

  // A `title` is a hover affordance; it must not become the link's name. A
  // link takes its accessible name from its contents, so this asserts the
  // computed name rather than the JSX.
  it('leaves the Jobs link accessible name as its label, not the tooltip', () => {
    counts.failed = 3;
    renderSidebar();

    const link = screen.getByRole('link', { name: 'Jobs' });
    expect(link).toHaveAttribute('title', '3 failed jobs');
    expect(screen.queryByRole('link', { name: '3 failed jobs' })).toBeNull();
  });

  it('keeps the Jobs row highlighted on the pre-filtered route', () => {
    counts.failed = 3;
    renderSidebar('/admin/jobs');
    expect(screen.getByText('Jobs').closest('a')).toHaveAttribute('data-active', 'true');
  });
});

// The source-key guard skips keys that are not string literals inside a t()
// call, and this one lives in the `operationsItems` table — so pin the bundle
// contents directly. All four locales carry the pair, and every `_one` value
// interpolates {{count}} (French resolves count 0 to `_one`, so a hardcoded
// "1" there would render "1 failed job" for zero).
describe('adminNav.failedJobs bundle coverage (#1185)', () => {
  const bundles = { en: enCommon, es: esCommon, fr: frCommon, de: deCommon };

  it.each(Object.entries(bundles))('%s carries both plural forms with {{count}}', (_locale, bundle) => {
    const adminNav = (bundle as { adminNav: Record<string, string> }).adminNav;
    expect(adminNav.failedJobs_one).toContain('{{count}}');
    expect(adminNav.failedJobs_other).toContain('{{count}}');
  });

  it('matches the English copy the mocked translator renders', () => {
    expect(enCommon.adminNav.failedJobs_one).toBe('{{count}} failed job');
    expect(enCommon.adminNav.failedJobs_other).toBe('{{count}} failed jobs');
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
      isMultiTenant: false,
      isLoading: false,
      isResolved: true,
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
      isMultiTenant: false,
      isLoading: false,
      isResolved: true,
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
      isMultiTenant: false,
      isLoading: false,
      isResolved: true,
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
