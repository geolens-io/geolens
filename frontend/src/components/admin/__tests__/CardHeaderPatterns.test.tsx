import { fireEvent, render, screen } from '@/test/test-utils';
import { AuditLogViewer } from '../AuditLogViewer';
import { StatsOverview } from '../StatsOverview';
import { UserList } from '../UserList';
import { useAuthStore } from '@/stores/auth-store';

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
const editionState = vi.hoisted(() => ({ isEnterprise: false }));

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
  useEdition: () => editionState,
}));

vi.mock('../ExportSplitButton', () => ({
  ExportSplitButton: ({ filters, disabled }: { filters: Record<string, unknown>; disabled?: boolean }) => (
    <output data-testid="audit-export-filters" data-disabled={String(Boolean(disabled))}>
      {JSON.stringify(filters)}
    </output>
  ),
}));

vi.mock('../FilterSelect', () => ({
  FilterSelect: ({
    label,
    value,
    onChange,
    options,
  }: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    options: { value: string; label: string }[];
  }) => (
    <label>
      {label}
      <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  ),
}));

vi.mock('../AIStatusCard', () => ({
  AIStatusCard: () => null,
}));

vi.mock('../UserCreateDialog', () => ({ UserCreateDialog: () => null }));
vi.mock('../UserEditDialog', () => ({ UserEditDialog: () => null }));
vi.mock('../UserDeleteDialog', () => ({ UserDeleteDialog: () => null }));

describe('admin card header patterns', () => {
  beforeEach(() => {
    editionState.isEnterprise = false;
    useAuthStore.setState({ user: null });
  });

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

  it('applies identity and resource filters consistently to list and export', () => {
    editionState.isEnterprise = true;
    mockUseAuditLogs.mockReturnValue({
      data: { logs: [], total: 0 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<AuditLogViewer />);

    fireEvent.change(screen.getByLabelText('User ID'), {
      target: { value: '11111111-1111-4111-8111-111111111111' },
    });
    fireEvent.change(screen.getByLabelText('Resource type'), {
      target: { value: 'dataset' },
    });
    fireEvent.change(screen.getByLabelText('Resource ID'), {
      target: { value: '22222222-2222-4222-8222-222222222222' },
    });

    const expected = {
      user_id: '11111111-1111-4111-8111-111111111111',
      resource_type: 'dataset',
      resource_id: '22222222-2222-4222-8222-222222222222',
    };
    expect(mockUseAuditLogs).toHaveBeenLastCalledWith(
      expect.objectContaining(expected),
      { enabled: true },
    );
    expect(JSON.parse(screen.getByTestId('audit-export-filters').textContent ?? '{}'))
      .toEqual(expect.objectContaining(expected));
  });

  it('blocks broad list and export requests while a UUID filter is invalid', () => {
    editionState.isEnterprise = true;
    mockUseAuditLogs.mockReturnValue({
      data: { logs: [], total: 0 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<AuditLogViewer />);
    fireEvent.change(screen.getByLabelText('User ID'), {
      target: { value: '11111111-partial' },
    });

    expect(screen.getByText('Enter a complete UUID.')).toBeInTheDocument();
    expect(mockUseAuditLogs).toHaveBeenLastCalledWith(
      expect.objectContaining({ user_id: '11111111-partial' }),
      { enabled: false },
    );
    expect(screen.getByTestId('audit-export-filters')).toHaveAttribute(
      'data-disabled',
      'true',
    );
  });

  it('offers exact action values emitted by current admin workflows', () => {
    mockUseAuditLogs.mockReturnValue({
      data: { logs: [], total: 0 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<AuditLogViewer />);

    expect(screen.getByRole('option', { name: 'job.retry' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'audit.export' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'dataset.view' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'user.deactivate' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'dataset.create' })).not.toBeInTheDocument();
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

  it('does not offer self-deactivation or self-deletion actions', async () => {
    const self = {
      id: '00000000-0000-0000-0000-000000000001',
      username: 'admin',
      email: 'admin@example.com',
      is_active: true,
      status: 'active',
      last_login_at: null,
      created_at: '2026-01-01T00:00:00Z',
      roles: ['admin'],
      quota_usage: null,
    };
    useAuthStore.setState({ user: self });
    mockUseUserList.mockReturnValue({
      data: { users: [self], total: 1 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<UserList />);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Actions for admin' }), {
      button: 0,
      ctrlKey: false,
    });

    expect(await screen.findByRole('menuitem', { name: 'Edit' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Deactivate' })).not.toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Delete' })).not.toBeInTheDocument();
  });
});
