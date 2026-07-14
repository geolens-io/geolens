import { render, screen } from '@/test/test-utils';
import { AIStatusCard } from '@/components/admin/AIStatusCard';

const mocks = vi.hoisted(() => ({
  capabilities: new Set<string>(),
  useAIStatus: vi.fn(),
  useEmbeddingStats: vi.fn(),
}));

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: (capability: string) => mocks.capabilities.has(capability),
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
});
