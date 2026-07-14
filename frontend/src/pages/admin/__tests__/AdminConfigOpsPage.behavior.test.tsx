import userEvent from '@testing-library/user-event';
import { render, screen, waitFor, within } from '@/test/test-utils';
import { AdminConfigOpsPage } from '../AdminConfigOpsPage';
import type { DryRunResult } from '@/api/config-ops';

const mocks = vi.hoisted(() => ({
  dryRunMutate: vi.fn(),
  dryRunReset: vi.fn(),
  importMutate: vi.fn(),
  importReset: vi.fn(),
}));

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn(() => false);
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

vi.mock('@/hooks/use-config-ops', () => ({
  useExportConfig: () => ({ mutate: vi.fn(), isPending: false }),
  useValidateConnectivity: () => ({
    mutate: vi.fn(),
    isPending: false,
    data: undefined,
  }),
  useDryRunImport: () => ({
    mutate: mocks.dryRunMutate,
    reset: mocks.dryRunReset,
    isPending: false,
  }),
  useImportConfig: () => ({
    mutate: mocks.importMutate,
    reset: mocks.importReset,
    isPending: false,
    isSuccess: false,
    data: undefined,
  }),
}));

const updatePreview: DryRunResult = {
  settings: {
    changes: [
      {
        key: 'log_level',
        current: 'INFO',
        imported: 'DEBUG',
        action: 'update',
      },
    ],
  },
  oauth_providers: { changes: [], dependent_accounts_deleted: 0 },
  preview_token: null,
};

async function uploadConfig(
  user: ReturnType<typeof userEvent.setup>,
  settings: Record<string, unknown> = { log_level: 'DEBUG' },
  fileName = 'config.json',
) {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  expect(input).not.toBeNull();
  await user.upload(
    input!,
    new File(
      [JSON.stringify({ settings })],
      fileName,
      { type: 'application/json' },
    ),
  );
  await screen.findByText(fileName);
}

async function selectOverwrite(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('combobox', { name: 'Import mode' }));
  await user.click(
    await screen.findByRole('option', { name: 'Overwrite - replace all' }),
  );
}

describe('AdminConfigOpsPage import confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.dryRunMutate.mockImplementation((_variables, options) => {
      options?.onSuccess?.(updatePreview);
    });
  });

  it('clears a preview when the import mode changes', async () => {
    const user = userEvent.setup();
    render(<AdminConfigOpsPage />);
    await uploadConfig(user);

    await user.click(screen.getByRole('button', { name: 'Preview Changes' }));
    expect(await screen.findByText('Settings Changes')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply Import' })).toBeEnabled();

    mocks.dryRunReset.mockClear();
    mocks.importReset.mockClear();
    await selectOverwrite(user);

    expect(screen.queryByText('Settings Changes')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply Import' })).toBeDisabled();
    expect(mocks.dryRunReset).toHaveBeenCalledOnce();
    expect(mocks.importReset).toHaveBeenCalledOnce();
  });

  it('sends the bound preview token when confirming overwrite', async () => {
    mocks.dryRunMutate.mockImplementation((_variables, options) => {
      options?.onSuccess?.({ ...updatePreview, preview_token: 'signed-preview' });
    });
    const user = userEvent.setup();
    render(<AdminConfigOpsPage />);
    await selectOverwrite(user);
    await uploadConfig(user);

    await user.click(screen.getByRole('button', { name: 'Preview Changes' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Apply Import' })).toBeEnabled(),
    );
    await user.click(screen.getByRole('button', { name: 'Apply Import' }));

    const dialog = await screen.findByRole('alertdialog');
    await user.type(
      within(dialog).getByRole('textbox', {
        name: 'Overwrite the entire configuration?',
      }),
      'OVERWRITE',
    );
    await user.click(within(dialog).getByRole('button', { name: 'Apply Import' }));

    expect(mocks.importMutate).toHaveBeenCalledWith(
      {
        data: { settings: { log_level: 'DEBUG' }, oauth_providers: null },
        mode: 'overwrite',
        previewToken: 'signed-preview',
      },
      expect.any(Object),
    );
  });

  it('shows an error and blocks overwrite when a preview has no bound token', async () => {
    const user = userEvent.setup();
    render(<AdminConfigOpsPage />);
    await selectOverwrite(user);
    await uploadConfig(user);

    await user.click(screen.getByRole('button', { name: 'Preview Changes' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Run a new overwrite preview',
    );
    expect(screen.getByRole('button', { name: 'Apply Import' })).toBeDisabled();
  });

  it('shows linked-account cascade counts in an overwrite preview', async () => {
    mocks.dryRunMutate.mockImplementation((_variables, options) => {
      options?.onSuccess?.({
        settings: { changes: [] },
        oauth_providers: {
          dependent_accounts_deleted: 3,
          changes: [
            {
              slug: 'corporate-sso',
              action: 'delete',
              changed_fields: null,
              dependent_accounts_deleted: 3,
            },
          ],
        },
        preview_token: 'signed-preview',
      });
    });
    const user = userEvent.setup();
    render(<AdminConfigOpsPage />);
    await selectOverwrite(user);
    await uploadConfig(user);

    await user.click(screen.getByRole('button', { name: 'Preview Changes' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Linked OAuth account deletions: 3',
    );
    const providerRow = screen.getByText('corporate-sso').closest('tr');
    expect(providerRow).not.toBeNull();
    expect(within(providerRow!).getByText('3')).toBeInTheDocument();
  });

  it('ignores an in-flight preview after a different file is selected', async () => {
    let resolveOldPreview: ((result: DryRunResult) => void) | undefined;
    mocks.dryRunMutate.mockImplementation((_variables, options) => {
      resolveOldPreview = options?.onSuccess;
    });
    const user = userEvent.setup();
    render(<AdminConfigOpsPage />);
    await uploadConfig(user);

    await user.click(screen.getByRole('button', { name: 'Preview Changes' }));
    await uploadConfig(user, { log_level: 'WARNING' }, 'replacement.json');
    resolveOldPreview?.(updatePreview);

    expect(mocks.dryRunReset).toHaveBeenCalled();
    expect(screen.queryByText('Settings Changes')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply Import' })).toBeDisabled();
  });
});
