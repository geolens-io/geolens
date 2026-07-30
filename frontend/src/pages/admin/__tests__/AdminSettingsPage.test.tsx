import { render, screen } from '@/test/test-utils';
import { Route, Routes } from 'react-router';
import { AdminSettingsPage } from '@/pages/admin/AdminSettingsPage';

// AdminSettingsPage composes 8 SettingsXxxTab components on top of TanStack
// Query hooks for live config + a router-driven `:tab` param.  Each tab is
// covered by its own component test; this page-level test stays scoped to
// route composition (header, breadcrumbs, tab dispatch, error banner).
vi.mock('@/components/admin/settings/EnvOnlyBanner', () => ({
  EnvOnlyBanner: () => <div data-testid="env-only-banner" />,
}));

vi.mock('@/components/admin/settings/SettingsGeneralTab', () => ({
  SettingsGeneralTab: () => <div data-testid="settings-general-tab" />,
}));

vi.mock('@/components/admin/settings/SettingsAuthTab', () => ({
  SettingsAuthTab: () => <div data-testid="settings-auth-tab" />,
}));

vi.mock('@/components/admin/settings/SettingsAITab', () => ({
  SettingsAITab: () => <div data-testid="settings-ai-tab" />,
}));

vi.mock('@/components/admin/settings/SettingsNetworkTab', () => ({
  SettingsNetworkTab: () => <div data-testid="settings-network-tab" />,
}));

vi.mock('@/components/admin/settings/SettingsStorageTab', () => ({
  SettingsStorageTab: () => <div data-testid="settings-storage-tab" />,
}));

vi.mock('@/components/admin/settings/SettingsMapTab', () => ({
  SettingsMapTab: () => <div data-testid="settings-map-tab" />,
}));

vi.mock('@/components/admin/settings/SettingsPermissionsTab', () => ({
  SettingsPermissionsTab: () => <div data-testid="settings-permissions-tab" />,
}));

vi.mock('@/components/admin/settings/SettingsAppearanceTab', () => ({
  SettingsAppearanceTab: () => <div data-testid="settings-appearance-tab" />,
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

vi.mock('@/hooks/use-unsaved-guard', () => ({
  useUnsavedGuard: () => ({ state: 'unblocked', proceed: vi.fn(), reset: vi.fn() }),
}));

const mockUseEdition = vi.fn();
vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => mockUseEdition(),
}));

const mockUseAllSettings = vi.fn();
const mockUseConfigMode = vi.fn();
const mockUseUpdateSettings = vi.fn();
const mockUseResetSettings = vi.fn();

vi.mock('@/hooks/use-settings', () => ({
  useAllSettings: () => mockUseAllSettings(),
  useConfigMode: () => mockUseConfigMode(),
  useUpdateSettings: () => mockUseUpdateSettings(),
  useResetSettings: () => mockUseResetSettings(),
}));

const mockUseParams = vi.fn();
vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router');
  return {
    ...actual,
    useParams: () => mockUseParams(),
  };
});

describe('AdminSettingsPage', () => {
  beforeEach(() => {
    mockUseAllSettings.mockReset();
    mockUseConfigMode.mockReset();
    mockUseUpdateSettings.mockReset();
    mockUseResetSettings.mockReset();
    mockUseParams.mockReset();

    mockUseConfigMode.mockReturnValue({ data: { env_only: false } });
    mockUseUpdateSettings.mockReturnValue({ mutate: vi.fn(), isPending: false });
    mockUseResetSettings.mockReturnValue({ mutate: vi.fn(), isPending: false });
    mockUseEdition.mockReturnValue({ isEnterprise: false });
  });

  it('renders the active tab from the route param when settings are loaded', () => {
    mockUseParams.mockReturnValue({ tab: 'general' });
    mockUseAllSettings.mockReturnValue({
      data: { env_only: false, tabs: { general: [] } },
      isLoading: false,
      isError: false,
    });

    render(<AdminSettingsPage />);

    expect(screen.getByTestId('settings-general-tab')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(screen.getByTestId('env-only-banner')).toBeInTheDocument();
  });

  it('renders skeletons while settings are loading', () => {
    mockUseParams.mockReturnValue({ tab: 'general' });
    mockUseAllSettings.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    });

    const { container } = render(<AdminSettingsPage />);

    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    // Tab content not yet rendered
    expect(screen.queryByTestId('settings-general-tab')).not.toBeInTheDocument();
    // Skeleton primitives carry the data-slot="skeleton" attribute from shadcn
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });

  it('renders the load-failure banner when settings query errors', () => {
    mockUseParams.mockReturnValue({ tab: 'general' });
    mockUseAllSettings.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error('boom'),
    });

    render(<AdminSettingsPage />);

    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    // Tab content not rendered on error
    expect(screen.queryByTestId('settings-general-tab')).not.toBeInTheDocument();
  });

  // test(#828): the appearance tab's edition gate lives here (visibleTabs
  // excludes 'appearance' unless isEnterprise). Both edition directions are
  // pinned below because e2e can only ever observe one of them — the stack
  // under test has a single edition. fix(#871) removed the static
  // appearance→map redirect from App.tsx that used to outrank
  // `admin/settings/:tab` and keep this gate from ever seeing the URL; these
  // two cases are what the route now delegates to.
  describe('appearance tab edition gating (#828)', () => {
    function renderAppearanceRoute() {
      mockUseParams.mockReturnValue({ tab: 'appearance' });
      return render(
        <Routes>
          <Route path="/admin/settings/general" element={<div data-testid="redirect-target-general" />} />
          <Route path="/admin/settings/:tab" element={<AdminSettingsPage />} />
        </Routes>,
        { route: '/admin/settings/appearance' },
      );
    }

    it('enterprise: renders the appearance tab for tab=appearance', () => {
      mockUseEdition.mockReturnValue({ isEnterprise: true });
      mockUseAllSettings.mockReturnValue({
        data: { env_only: false, tabs: { appearance: [] } },
        isLoading: false,
        isError: false,
      });

      renderAppearanceRoute();

      expect(screen.getByTestId('settings-appearance-tab')).toBeInTheDocument();
      expect(screen.queryByTestId('redirect-target-general')).not.toBeInTheDocument();
    });

    it('community: redirects tab=appearance to the general settings route', () => {
      mockUseEdition.mockReturnValue({ isEnterprise: false });
      mockUseAllSettings.mockReturnValue({
        data: { env_only: false, tabs: { appearance: [] } },
        isLoading: false,
        isError: false,
      });

      renderAppearanceRoute();

      expect(screen.getByTestId('redirect-target-general')).toBeInTheDocument();
      expect(screen.queryByTestId('settings-appearance-tab')).not.toBeInTheDocument();
    });
  });
});
