import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import type { SettingItem } from '@/api/settings';
import { SettingsAITab } from '../SettingsAITab';

const hoisted = vi.hoisted(() => ({
  backfillMutate: vi.fn(),
  embedded: 50,
  stale: 0,
  statsAvailable: true,
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), info: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: (capability: string) => capability === 'manage_users' }),
}));

vi.mock('@/hooks/use-admin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-admin')>();
  return {
    ...actual,
    useEmbeddingStats: () => ({
      data: !hoisted.statsAvailable ? undefined : {
        total_records: 100,
        embedded_records: hoisted.embedded,
        missing_records: 100 - hoisted.embedded,
        stale_records: hoisted.stale,
        coverage_percent: hoisted.embedded,
        current_run: null,
        recent_runs: [],
        estimate: null,
      },
    }),
    useBackfillEmbeddings: () => ({
      mutate: hoisted.backfillMutate,
      isPending: false,
      variables: undefined,
    }),
  };
});

vi.mock('@/hooks/use-settings', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-settings')>();
  return { ...actual, useApiKeyStatus: () => ({ data: { configured: true } }) };
});

const settings: SettingItem[] = [
  { key: 'ai_enabled', value: true, source: 'default', label: 'AI enabled' },
  { key: 'embedding_model', value: 'text-embedding-3-small', source: 'default', label: 'Embedding model' },
  { key: 'embedding_dims', value: 1536, source: 'overridden', label: 'Embedding Dimensions' },
];

const onReset = vi.fn();

function renderTab(items: SettingItem[] = settings) {
  const onSave = vi.fn();
  render(
    <SettingsAITab settings={items} envOnly={false} onSave={onSave} onReset={onReset} isSaving={false} />,
  );
  return onSave;
}

async function changeWidth(user: ReturnType<typeof userEvent.setup>, to: string) {
  const input = screen.getByLabelText('Embedding Dimensions');
  await user.clear(input);
  await user.type(input, to);
}

describe('SettingsAITab embedding width confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.embedded = 50;
    hoisted.stale = 0;
    hoisted.statsAvailable = true;
  });

  it('asks before saving a width change and sends nothing on cancel', async () => {
    const user = userEvent.setup();
    const onSave = renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByText(/deletes 50 stored embeddings/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onSave).not.toHaveBeenCalled();
    expect(hoisted.backfillMutate).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Embedding Dimensions')).toHaveValue(768);
  });

  it('saves on confirm and queues nothing from the client', async () => {
    const user = userEvent.setup();
    const onSave = renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith({ embedding_dims: '768' });
    expect(hoisted.backfillMutate).not.toHaveBeenCalled();
  });

  it('counts stale embeddings with the usable ones', async () => {
    hoisted.stale = 7;
    const user = userEvent.setup();
    renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByText(/deletes 57 stored embeddings/)).toBeInTheDocument();
  });

  it('still confirms a width change when the stats are unavailable', async () => {
    hoisted.statsAvailable = false;
    const user = userEvent.setup();
    const onSave = renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByText(/deletes all stored embeddings/)).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('confirms a model-only change', async () => {
    const user = userEvent.setup();
    const onSave = renderTab();

    const model = screen.getByLabelText('Embedding Model');
    await user.clear(model);
    await user.type(model, 'other-model');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByText('Change embedding model?')).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));
    expect(onSave).toHaveBeenCalledWith({ embedding_model: 'other-model' });
  });

  it('confirms with the generic wording when the stats report zero embeddings', async () => {
    hoisted.embedded = 0;
    const user = userEvent.setup();
    const onSave = renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByText(/deletes all stored embeddings/)).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('saves directly when the width is unchanged', async () => {
    const user = userEvent.setup();
    const onSave = renderTab();

    await user.click(screen.getByRole('switch', { name: 'AI Chat Enabled' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/stored embeddings/)).not.toBeInTheDocument();
  });

  describe('resetting an overridden embedding setting', () => {
    const overridden = settings.map((item) =>
      item.key === 'embedding_dims' ? { ...item, source: 'overridden' as const } : item,
    );

    it('sends no reset on cancel', async () => {
      const user = userEvent.setup();
      renderTab(overridden);

      await user.click(screen.getByRole('button', { name: /Reset/ }));
      expect(screen.getByText('Change embedding width?')).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Cancel' }));

      expect(onReset).not.toHaveBeenCalled();
    });

    it('sends exactly one reset on confirm', async () => {
      const user = userEvent.setup();
      renderTab(overridden);

      await user.click(screen.getByRole('button', { name: /Reset/ }));
      await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

      expect(onReset).toHaveBeenCalledTimes(1);
      expect(onReset).toHaveBeenCalledWith('embedding_dims');
    });

    it('still confirms a reset when the stats report zero embeddings', async () => {
      hoisted.embedded = 0;
      const user = userEvent.setup();
      renderTab(overridden);

      await user.click(screen.getByRole('button', { name: /Reset/ }));
      expect(onReset).not.toHaveBeenCalled();
      await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

      expect(onReset).toHaveBeenCalledWith('embedding_dims');
    });
  });
});
