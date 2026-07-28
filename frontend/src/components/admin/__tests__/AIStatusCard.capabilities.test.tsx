import { render, screen } from '@/test/test-utils';
import { AIStatusCard } from '@/components/admin/AIStatusCard';

const mocks = vi.hoisted(() => ({
  capabilities: new Set<string>(),
  isMultiTenant: false,
  useAIStatus: vi.fn(),
  useEmbeddingStats: vi.fn(),
}));

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: (capability: string) => mocks.capabilities.has(capability),
  }),
}));

// fix(#653): the card gate goes through useAIStatusReader, which composes
// usePermissions with useEdition — mock the edition side too.
vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({
    edition: 'community',
    features: [],
    isEnterprise: false,
    isMultiTenant: mocks.isMultiTenant,
    isLoading: false,
  }),
}));

vi.mock('@/hooks/use-admin', () => ({
  useAIStatus: (options: { enabled?: boolean }) => mocks.useAIStatus(options),
  useEmbeddingStats: (options: { enabled?: boolean }) =>
    mocks.useEmbeddingStats(options),
}));

describe('AIStatusCard capability gates', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.capabilities = new Set(['manage_users']);
    mocks.isMultiTenant = false;
    mocks.useAIStatus.mockReturnValue({
      data: {
        configured: true,
        enabled: true,
        provider: 'openai',
        semantic_search_enabled: true,
      },
      isLoading: false,
    });
    mocks.useEmbeddingStats.mockReturnValue({ data: undefined });
  });

  it('loads operational status without showing a denied settings link', () => {
    render(<AIStatusCard />);

    expect(mocks.useAIStatus).toHaveBeenCalledWith({ enabled: true });
    expect(mocks.useEmbeddingStats).toHaveBeenCalledWith({ enabled: true });
    expect(screen.getByText('AI Status')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Manage AI settings' })).not.toBeInTheDocument();
  });

  it('suppresses manage-users probes and content without the capability', () => {
    mocks.capabilities = new Set(['manage_settings']);

    render(<AIStatusCard />);

    expect(mocks.useAIStatus).toHaveBeenCalledWith({ enabled: false });
    expect(mocks.useEmbeddingStats).toHaveBeenCalledWith({ enabled: false });
    expect(screen.queryByText('AI Status')).not.toBeInTheDocument();
  });

  // fix(#653): /admin/ai-status is gated by require_ai_status_reader — the
  // capability flips from manage_users to manage_tenants in multi-tenant mode.
  it('multi-tenant: manage_users alone hides the card and fires no queries', () => {
    mocks.isMultiTenant = true;
    mocks.capabilities = new Set(['manage_users']);

    render(<AIStatusCard />);

    expect(mocks.useAIStatus).toHaveBeenCalledWith({ enabled: false });
    expect(mocks.useEmbeddingStats).toHaveBeenCalledWith({ enabled: false });
    expect(screen.queryByText('AI Status')).not.toBeInTheDocument();
  });

  it('multi-tenant: manage_tenants without manage_users shows the card', () => {
    mocks.isMultiTenant = true;
    mocks.capabilities = new Set(['manage_tenants']);

    render(<AIStatusCard />);

    expect(mocks.useAIStatus).toHaveBeenCalledWith({ enabled: true });
    // fix(#653): /admin/embedding-stats stays manage_users in both modes —
    // a manage_tenants-only operator would 403, so the query stays disabled.
    expect(mocks.useEmbeddingStats).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByText('AI Status')).toBeInTheDocument();
  });

  it('multi-tenant: manage_tenants plus manage_users also loads coverage', () => {
    mocks.isMultiTenant = true;
    mocks.capabilities = new Set(['manage_tenants', 'manage_users']);

    render(<AIStatusCard />);

    expect(mocks.useAIStatus).toHaveBeenCalledWith({ enabled: true });
    expect(mocks.useEmbeddingStats).toHaveBeenCalledWith({ enabled: true });
    expect(screen.getByText('AI Status')).toBeInTheDocument();
  });
});
