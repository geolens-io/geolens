import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import type { SettingItem } from '@/api/settings';
import { SettingsAITab } from '../SettingsAITab';

// fix(#1542): the backfill is queued, so by the time the mutation resolves the
// run has not started, let alone finished. The panel used to read counts off
// the response ("Generated N embeddings") — under the queued contract those
// fields do not exist, and reporting a result nobody has yet would be a
// fabricated one. It acknowledges the queueing instead; the coverage figure
// above the buttons is what reflects the finished run.

const hoisted = vi.hoisted(() => ({
  mutate: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: (capability: string) => capability === 'manage_users' }),
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({
    edition: 'community',
    features: [],
    isEnterprise: false,
    isMultiTenant: false,
    isLoading: false,
  }),
}));

vi.mock('@/hooks/use-admin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-admin')>();
  return {
    ...actual,
    useEmbeddingStats: () => ({
      data: {
        total_records: 100,
        embedded_records: 50,
        missing_records: 50,
        stale_records: 0,
        coverage_percent: 50,
      },
    }),
    useBackfillEmbeddings: () => ({
      mutate: hoisted.mutate,
      isPending: false,
      variables: undefined,
    }),
    useUpdateSemanticSearch: () => ({ mutate: vi.fn(), isPending: false }),
  };
});

vi.mock('@/hooks/use-settings', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-settings')>();
  return { ...actual, useApiKeyStatus: () => ({ data: { configured: true } }) };
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

describe('SettingsAITab — queued backfill (#1542)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('acknowledges the queued run rather than reporting counts it does not have', async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(screen.getByRole('button', { name: /Regenerate All/ }));

    expect(hoisted.mutate).toHaveBeenCalledTimes(1);
    const [force, options] = hoisted.mutate.mock.calls[0];
    expect(force).toBe(true);

    options.onSuccess({ job_id: '5f1e5b2a-0000-4000-8000-000000000001', status: 'pending' });

    expect(toast.info).toHaveBeenCalledWith(
      'Embedding backfill queued — this page updates when it finishes',
    );
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});
