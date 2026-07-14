import { render, screen } from '@/test/test-utils';
import { SettingsAITab } from '../SettingsAITab';
import type { SettingItem } from '@/api/settings';

// #347 (ADM-05) regression: the Embedding Coverage box has two buttons ("Generate
// Missing" + "Regenerate All") backed by one backfill mutation. Each spinner
// must key off backfill.variables (false = missing, true = regenerate) so only
// the clicked button spins — previously both keyed off backfill.isPending and
// both spun at once.

const hoisted = vi.hoisted(() => ({
  backfill: { mutate: vi.fn(), isPending: false, variables: undefined as unknown },
  canManageUsers: true,
  useEmbeddingStats: vi.fn((_options?: { enabled?: boolean }) => ({
    data: { total_records: 100, embedded_records: 50, missing_records: 50, coverage_percent: 50 },
  })),
}));

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    can: (capability: string) => capability === 'manage_users' && hoisted.canManageUsers,
  }),
}));

vi.mock('@/hooks/use-admin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-admin')>();
  return {
    ...actual,
    useEmbeddingStats: (options?: { enabled?: boolean }) => hoisted.useEmbeddingStats(options),
    useBackfillEmbeddings: () => hoisted.backfill,
    useUpdateSemanticSearch: () => ({ mutate: vi.fn(), isPending: false }),
  };
});

vi.mock('@/hooks/use-settings', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-settings')>();
  return {
    ...actual,
    useApiKeyStatus: () => ({ data: { configured: true } }),
  };
});

function renderTab(settings: SettingItem[] = []) {
  return render(
    <SettingsAITab
      settings={settings}
      envOnly={false}
      onSave={vi.fn()}
      onReset={vi.fn()}
      isSaving={false}
    />,
  );
}

describe('SettingsAITab — embedding coverage single spinner (#347 (ADM-05))', () => {
  beforeEach(() => {
    hoisted.canManageUsers = true;
    hoisted.useEmbeddingStats.mockClear();
  });

  it('shows exactly one spinner — only Regenerate All — while regenerating', () => {
    hoisted.backfill = { mutate: vi.fn(), isPending: true, variables: true };
    const { container } = renderTab();
    expect(container.querySelectorAll('.animate-spin')).toHaveLength(1);
  });

  it('shows exactly one spinner — only Generate Missing — while generating missing', () => {
    hoisted.backfill = { mutate: vi.fn(), isPending: true, variables: false };
    const { container } = renderTab();
    expect(container.querySelectorAll('.animate-spin')).toHaveLength(1);
  });

  it('shows no spinner when idle', () => {
    hoisted.backfill = { mutate: vi.fn(), isPending: false, variables: undefined };
    const { container } = renderTab();
    expect(container.querySelectorAll('.animate-spin')).toHaveLength(0);
  });

  it('uses settings for the semantic toggle and suppresses user-management probes', () => {
    hoisted.canManageUsers = false;
    renderTab([
      {
        key: 'semantic_search_enabled',
        value: true,
        source: 'overridden',
        label: 'Semantic search',
      },
    ]);

    expect(hoisted.useEmbeddingStats).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByRole('switch', { name: 'Semantic Search' })).toBeChecked();
    expect(screen.queryByText('Embedding Coverage')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Generate Missing' })).not.toBeInTheDocument();
  });
});
