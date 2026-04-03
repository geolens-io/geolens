import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SidebarProvider } from '@/components/ui/sidebar';
import { AdminSidebar } from '../AdminSidebar';

vi.mock('@/hooks/use-admin', () => ({
  usePendingCount: () => ({ data: 0 }),
  useFailedJobCount: () => ({ data: 0 }),
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({ isEnterprise: false, edition: 'community', isLoading: false }),
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
    expect(link).toHaveAttribute('href', '/search');
  });
});
