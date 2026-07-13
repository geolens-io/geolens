import { render, screen } from '@/test/test-utils';
import { AuditLogViewer } from '../AuditLogViewer';
import { StatsOverview } from '../StatsOverview';
import { UserList } from '../UserList';

const {
  mockUseAuditLogs,
  mockUseCatalogStats,
  mockUseInfrastructure,
  mockUseUserList,
} = vi.hoisted(() => ({
  mockUseAuditLogs: vi.fn(),
  mockUseCatalogStats: vi.fn(),
  mockUseInfrastructure: vi.fn(),
  mockUseUserList: vi.fn(),
}));

vi.mock('@/hooks/use-admin', () => ({
  useAuditLogs: (...args: unknown[]) => mockUseAuditLogs(...args),
  useCatalogStats: () => mockUseCatalogStats(),
  useInfrastructure: () => mockUseInfrastructure(),
  useUserList: (...args: unknown[]) => mockUseUserList(...args),
  useApproveUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useRejectUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useDeactivateUser: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({ isEnterprise: false }),
}));

vi.mock('../AIStatusCard', () => ({
  AIStatusCard: () => null,
}));

vi.mock('../UserCreateDialog', () => ({ UserCreateDialog: () => null }));
vi.mock('../UserEditDialog', () => ({ UserEditDialog: () => null }));
vi.mock('../UserDeleteDialog', () => ({ UserDeleteDialog: () => null }));

describe('admin card header patterns', () => {
  it('exposes the audit title as an h2 and puts search in CardAction', () => {
    mockUseAuditLogs.mockReturnValue({
      data: { logs: [], total: 0 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<AuditLogViewer />);

    expect(screen.getByRole('heading', { level: 2, name: 'Audit Logs' })).toBeInTheDocument();
    expect(document.querySelector('[data-slot="card-action"] input')).toBeInTheDocument();
  });

  it('exposes admin overview card titles as h2s and puts refresh in CardAction', () => {
    mockUseCatalogStats.mockReturnValue({
      data: {
        total_datasets: 2,
        recent_additions: 1,
        total_storage_bytes: 1024,
        datasets_by_geometry_type: { Point: 2 },
        datasets_by_visibility: { public: 2 },
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    mockUseInfrastructure.mockReturnValue({
      data: {
        health: {
          database: { status: 'ok', latency_ms: 2 },
          storage: { status: 'ok', latency_ms: 3 },
          cache: { status: 'ok', latency_ms: 1 },
        },
        oidc_providers: {},
        config: {
          database_type: 'postgresql',
          storage_provider: 's3',
          cache_provider: 'valkey',
          tile_cache: 'valkey',
          tile_cache_ttl: 300,
          cdn_configured: false,
        },
      },
      isLoading: false,
      isError: false,
      isFetching: false,
      refetch: vi.fn(),
    });

    render(<StatsOverview />);

    expect(screen.getByRole('heading', { level: 2, name: 'All Systems Operational' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Datasets by Geometry Type' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Datasets by Visibility' })).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Refresh infrastructure status' })
        .closest('[data-slot="card-action"]'),
    ).toBeInTheDocument();
  });

  it('exposes the users title as an h2 and groups table controls in CardAction', () => {
    mockUseUserList.mockReturnValue({
      data: { users: [], total: 0 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<UserList />);

    expect(screen.getByRole('heading', { level: 2, name: 'Users' })).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Add User' }).closest('[data-slot="card-action"]'),
    ).toBeInTheDocument();
  });
});
