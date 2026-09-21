import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApiError } from '@/api/client';
import { SourceSyncDialog } from '../SourceSyncDialog';
import { render } from '@/test/test-utils';

Object.defineProperty(HTMLElement.prototype, 'hasPointerCapture', { value: () => false });
Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', { value: () => undefined });
Object.defineProperty(HTMLElement.prototype, 'releasePointerCapture', { value: () => undefined });
Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { value: () => undefined });

const mocks = vi.hoisted(() => ({
  createDatasetSync: vi.fn(),
  updateDatasetSync: vi.fn(),
  createSyncCredential: vi.fn(),
  replaceSyncCredential: vi.fn(),
  listSyncCredentials: vi.fn(),
}));

vi.mock('@/api/dataset-sync', () => ({
  createDatasetSync: mocks.createDatasetSync,
  updateDatasetSync: mocks.updateDatasetSync,
  createSyncCredential: mocks.createSyncCredential,
  replaceSyncCredential: mocks.replaceSyncCredential,
  listSyncCredentials: mocks.listSyncCredentials,
}));

const source = {
  connector: 'arcgis_feature_server' as const,
  service_url: 'https://maps.example.test/arcgis/rest/services/Parks/FeatureServer',
  layer_id: 7,
};

const automation = {
  id: 'sync-1', dataset_id: 'dataset-1', revision: 4, status: 'paused' as const, pause_reason: null,
  source, credential: null, cadence: { kind: 'daily' as const, hour: 2, minute: 0 }, next_due_at: null,
  eligibility: { eligible: false, reasons: ['qualifying_run_required'], policy_version: 'arcgis_id_set_v1' },
  last_occurrence: null, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
};

describe('SourceSyncDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listSyncCredentials.mockResolvedValue([]);
  });

  it('creates a draft with a write-only credential and clears the token after saving', async () => {
    const user = userEvent.setup();
    mocks.createSyncCredential.mockResolvedValue({ id: 'credential-1' });
    mocks.createDatasetSync.mockResolvedValue({ ...automation, status: 'draft' });
    const onOpenChange = vi.fn();

    render(<SourceSyncDialog datasetId="dataset-1" source={source} automation={null} open onOpenChange={onOpenChange} onRevisionConflict={vi.fn()} />);
    await waitFor(() => expect(mocks.listSyncCredentials).toHaveBeenCalledWith('dataset-1'));
    expect(screen.getByText('Scheduled refresh replaces local data')).toBeInTheDocument();
    expect(screen.getByText('Verification checks that every source ID was fetched and that the ID set stayed the same. Source attributes may still change during the refresh.')).toBeInTheDocument();

    await user.click(screen.getByLabelText('Credential'));
    await user.click(await screen.findByRole('option', { name: 'Store a new credential' }));
    await user.type(screen.getByLabelText('Credential name'), 'Parks service');
    await user.type(screen.getByLabelText('ArcGIS token'), 'write-only-token');
    await user.click(screen.getByRole('button', { name: 'Create draft' }));

    await waitFor(() => expect(mocks.createSyncCredential).toHaveBeenCalledWith({
      connector_name: 'arcgis_feature_server',
      allowed_origin: 'https://maps.example.test',
      display_name: 'Parks service',
      token: 'write-only-token',
    }));
    expect(mocks.createDatasetSync).toHaveBeenCalledWith('dataset-1', {
      source,
      cadence: { kind: 'daily', hour: 2, minute: 0 },
      credential_id: 'credential-1',
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(String(window.localStorage.getItem('geolens-auth'))).not.toContain('write-only-token');
    expect(screen.getByLabelText('ArcGIS token')).toHaveValue('');
  });

  it('keeps the dialog open and refreshes server state after a revision conflict', async () => {
    const user = userEvent.setup();
    const conflict = new ApiError('conflict', 409, { code: 'revision_conflict' });
    mocks.updateDatasetSync.mockRejectedValue(conflict);
    const onRevisionConflict = vi.fn();

    render(<SourceSyncDialog datasetId="dataset-1" source={source} automation={automation} open onOpenChange={vi.fn()} onRevisionConflict={onRevisionConflict} />);
    await user.click(screen.getByRole('button', { name: 'Save schedule' }));

    await waitFor(() => expect(mocks.updateDatasetSync).toHaveBeenCalledWith('dataset-1', {
      revision: 4,
      cadence: { kind: 'daily', hour: 2, minute: 0 },
    }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This schedule changed on the server.');
    expect(onRevisionConflict).toHaveBeenCalledOnce();
    expect(screen.getByRole('dialog')).toBeVisible();
  });

  it('uses the explicit credential-clear flag when switching a configured source to public access', async () => {
    const user = userEvent.setup();
    mocks.updateDatasetSync.mockResolvedValue({ ...automation, credential: null });
    render(<SourceSyncDialog datasetId="dataset-1" source={source} automation={{ ...automation, credential: { id: 'credential-1', version: 2, display_name: 'Expired token', expires_at: '2026-09-01T00:00:00Z' } }} open onOpenChange={vi.fn()} onRevisionConflict={vi.fn()} />);

    await user.click(screen.getByLabelText('Credential'));
    await user.click(await screen.findByRole('option', { name: 'No credential (public source)' }));
    await user.click(screen.getByRole('button', { name: 'Save schedule' }));

    await waitFor(() => expect(mocks.updateDatasetSync).toHaveBeenCalledWith('dataset-1', {
      revision: 4,
      cadence: { kind: 'daily', hour: 2, minute: 0 },
      clear_credential: true,
    }));
  });

  it('updates the schedule source when the dataset provenance binding changed', async () => {
    const user = userEvent.setup();
    const changedSource = { ...source, service_url: 'https://maps.example.test/arcgis/rest/services/UpdatedParks/FeatureServer' };
    mocks.updateDatasetSync.mockResolvedValue({ ...automation, source: changedSource });
    render(<SourceSyncDialog datasetId="dataset-1" source={changedSource} automation={automation} open onOpenChange={vi.fn()} onRevisionConflict={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Save schedule' }));

    await waitFor(() => expect(mocks.updateDatasetSync).toHaveBeenCalledWith('dataset-1', {
      revision: 4,
      source: changedSource,
      cadence: { kind: 'daily', hour: 2, minute: 0 },
    }));
  });

  it('repairs an expired credential by replacing its write-only token before saving the schedule', async () => {
    const user = userEvent.setup();
    const expiredCredential = { id: 'credential-1', connector_name: 'arcgis_feature_server', allowed_origin: 'https://maps.example.test', display_name: 'Expired token', current_version: 2, current_expires_at: '2026-09-01T00:00:00Z', revoked_at: null, created_at: '2026-08-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z' };
    mocks.listSyncCredentials.mockResolvedValue([expiredCredential]);
    mocks.replaceSyncCredential.mockResolvedValue({ ...expiredCredential, current_version: 3, current_expires_at: null });
    mocks.updateDatasetSync.mockResolvedValue({ ...automation, credential: { id: 'credential-1', version: 3, display_name: 'Expired token', expires_at: null } });
    render(<SourceSyncDialog datasetId="dataset-1" source={source} automation={{ ...automation, credential: { id: 'credential-1', version: 2, display_name: 'Expired token', expires_at: '2026-09-01T00:00:00Z' } }} open onOpenChange={vi.fn()} onRevisionConflict={vi.fn()} />);

    await user.click(await screen.findByRole('button', { name: 'Replace stored token' }));
    await user.type(screen.getByLabelText('ArcGIS token'), 'replacement-token');
    await user.click(screen.getByRole('button', { name: 'Save schedule' }));

    await waitFor(() => expect(mocks.replaceSyncCredential).toHaveBeenCalledWith(
      'credential-1',
      { token: 'replacement-token' },
    ));
    expect(mocks.updateDatasetSync).toHaveBeenCalledWith('dataset-1', {
      revision: 4,
      cadence: { kind: 'daily', hour: 2, minute: 0 },
      credential_id: 'credential-1',
    });
  });

  it('announces when stored credentials cannot be loaded while keeping the public-source option available', async () => {
    mocks.listSyncCredentials.mockRejectedValue(new Error('credentials unavailable'));
    render(<SourceSyncDialog datasetId="dataset-1" source={source} automation={null} open onOpenChange={vi.fn()} onRevisionConflict={vi.fn()} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Stored credentials could not be loaded.');
    expect(screen.getByRole('button', { name: 'Create draft' })).toBeEnabled();
  });
});
