import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
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

function renderTab(items: SettingItem[] = settings, onSave = vi.fn()) {
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
    hoisted.backfillMutate.mockReset();
    hoisted.embedded = 50;
    hoisted.stale = 0;
    hoisted.statsAvailable = true;
  });

  it('asks before saving a width change and sends nothing on cancel', async () => {
    const user = userEvent.setup();
    const onSave = renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByText(/deletes all stored embeddings/)).toBeInTheDocument();
    expect(screen.getByRole('alertdialog')).not.toHaveTextContent('50');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onSave).not.toHaveBeenCalled();
    expect(hoisted.backfillMutate).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Embedding Dimensions')).toHaveValue(768);
  });

  it('saves on confirm and then queues the backfill', async () => {
    const user = userEvent.setup();
    const onSave = renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByRole('checkbox', { name: 'Regenerate embeddings after saving' })).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith({ embedding_dims: '768' });
    await waitFor(() => expect(hoisted.backfillMutate).toHaveBeenCalledWith({ force: false, allTenants: true }, expect.anything()));
  });

  it('warns when another tenant could not start regenerating', async () => {
    hoisted.backfillMutate.mockImplementation((_variables, opts) =>
      opts.onSuccess({
        job_id: '5f1e5b2a-0000-4000-8000-000000000001',
        status: 'pending',
        other_tenants: [
          { tenant_id: 'a', job_id: 'b', status: 'pending' },
          { tenant_id: 'c', job_id: null, status: 'not_queued' },
        ],
      }),
    );
    const user = userEvent.setup();
    renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

    await waitFor(() =>
      expect(toast.warning).toHaveBeenCalledWith('Regeneration could not be queued for 1 other tenant'),
    );
  });

  it('keeps the pending warning visible when the stats are unavailable', async () => {
    hoisted.statsAvailable = false;
    hoisted.backfillMutate.mockImplementation((_variables, opts) => opts.onError(new Error('no provider')));
    const user = userEvent.setup();
    renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

    expect(await screen.findByText(/could not be regenerated automatically/)).toBeInTheDocument();
  });

  it('describes automatic regeneration while the option is checked, and the manual step once cleared', async () => {
    const user = userEvent.setup();
    renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByText(/regenerates them automatically after saving/)).toBeInTheDocument();
    expect(screen.getByRole('alertdialog')).not.toHaveTextContent('Generate Missing Embeddings');

    await user.click(screen.getByRole('checkbox', { name: 'Regenerate embeddings after saving' }));
    expect(screen.getByRole('alertdialog')).toHaveTextContent('regenerate them with Generate Missing Embeddings');
  });

  it('queues nothing and says AI must be enabled when AI was already off', async () => {
    const user = userEvent.setup();
    const onSave = renderTab(
      settings.map((item) => (item.key === 'ai_enabled' ? { ...item, value: false } : item)),
    );

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.queryByRole('checkbox', { name: 'Regenerate embeddings after saving' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(hoisted.backfillMutate).not.toHaveBeenCalled();
    expect(await screen.findByText(/AI features are disabled/)).toBeInTheDocument();
  });

  it('queues nothing when the same save turns AI off', async () => {
    const user = userEvent.setup();
    const onSave = renderTab();

    await user.click(screen.getByRole('switch', { name: 'AI Chat Enabled' }));
    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toMatchObject({ ai_enabled: false, embedding_dims: '768' });
    expect(hoisted.backfillMutate).not.toHaveBeenCalled();
    expect(await screen.findByText(/AI features are disabled/)).toBeInTheDocument();
  });

  it('queues nothing when the regenerate option is cleared', async () => {
    const user = userEvent.setup();
    const onSave = renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await user.click(screen.getByRole('checkbox', { name: 'Regenerate embeddings after saving' }));
    await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(hoisted.backfillMutate).not.toHaveBeenCalled();
  });

  it('queues nothing when the save fails', async () => {
    const user = userEvent.setup();
    const onSave = renderTab(settings, vi.fn().mockResolvedValue(false));

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(hoisted.backfillMutate).not.toHaveBeenCalled();
  });

  it('says regeneration is pending when the backfill cannot be queued', async () => {
    hoisted.backfillMutate.mockImplementation((_variables, opts) => opts.onError(new Error('no provider')));
    const user = userEvent.setup();
    renderTab();

    await changeWidth(user, '768');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

    expect(await screen.findByText(/could not be regenerated automatically/)).toBeInTheDocument();
  });

  it('names all stored embeddings, never a tenant-scoped count, even when stats are unavailable', async () => {
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
    await user.click(screen.getByRole('button', { name: 'Change model' }));
    expect(onSave).toHaveBeenCalledWith({ embedding_model: 'other-model' });
  });

  it('confirms when the stats report zero embeddings', async () => {
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

    it('softens the dialog when the override equals the default width, and still regenerates', async () => {
      const user = userEvent.setup();
      renderTab(
        overridden.map((item) =>
          item.key === 'embedding_dims' ? { ...item, default_value: 1536 } : item,
        ),
      );

      await user.click(screen.getByRole('button', { name: /Reset/ }));

      expect(screen.getByText('Reset embedding width?')).toBeInTheDocument();
      expect(screen.getByText(/Resetting should keep stored embeddings/)).toBeInTheDocument();
      expect(screen.queryByText(/deletes all stored embeddings/)).not.toBeInTheDocument();
      expect(onReset).not.toHaveBeenCalled();
      await user.click(screen.getByRole('button', { name: 'Reset width' }));

      expect(onReset).toHaveBeenCalledWith('embedding_dims');
      await waitFor(() => expect(hoisted.backfillMutate).toHaveBeenCalledWith({ force: false, allTenants: true }, expect.anything()));
    });

    it('queues the backfill only after the reset resolves', async () => {
      let finish: (ok: boolean) => void = () => {};
      onReset.mockReturnValueOnce(new Promise<boolean>((resolve) => { finish = resolve; }));
      const user = userEvent.setup();
      renderTab(overridden);

      await user.click(screen.getByRole('button', { name: /Reset/ }));
      await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));
      expect(hoisted.backfillMutate).not.toHaveBeenCalled();

      finish(true);
      await waitFor(() => expect(hoisted.backfillMutate).toHaveBeenCalledWith({ force: false, allTenants: true }, expect.anything()));
    });

    it('queues nothing when the reset fails', async () => {
      onReset.mockResolvedValueOnce(false);
      const user = userEvent.setup();
      renderTab(overridden);

      await user.click(screen.getByRole('button', { name: /Reset/ }));
      await user.click(screen.getByRole('button', { name: 'Delete embeddings' }));

      await waitFor(() => expect(onReset).toHaveBeenCalledTimes(1));
      await new Promise((r) => setTimeout(r, 20));
      expect(hoisted.backfillMutate).not.toHaveBeenCalled();
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

    it('does not warn of deletion when resetting only the model', async () => {
      const user = userEvent.setup();
      renderTab(
        settings.map((item) =>
          item.key === 'embedding_model' ? { ...item, source: 'overridden' as const } : { ...item, source: 'default' as const },
        ),
      );

      await user.click(screen.getByRole('button', { name: /Reset/ }));
      expect(screen.getByText(/Stored embeddings are kept/)).toBeInTheDocument();
      expect(screen.queryByText(/deleted/)).not.toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Change model' }));

      expect(onReset).toHaveBeenCalledWith('embedding_model');
    });
  });
});
