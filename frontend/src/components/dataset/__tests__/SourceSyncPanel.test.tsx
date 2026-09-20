import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApiError } from '@/api/client';
import { SourceSyncPanel } from '../SourceSyncPanel';
import { render } from '@/test/test-utils';
import type { DatasetResponse } from '@/types/api';

const mocks = vi.hoisted(() => ({
  getDatasetSync: vi.fn(), runDatasetSync: vi.fn(), pauseDatasetSync: vi.fn(), resumeDatasetSync: vi.fn(), deleteDatasetSync: vi.fn(),
  listSyncCredentials: vi.fn(), createDatasetSync: vi.fn(), updateDatasetSync: vi.fn(), createSyncCredential: vi.fn(), replaceSyncCredential: vi.fn(), deleteSyncCredential: vi.fn(),
  useEdition: vi.fn(),
}));

vi.mock('@/api/dataset-sync', () => ({
  getDatasetSync: mocks.getDatasetSync, runDatasetSync: mocks.runDatasetSync, pauseDatasetSync: mocks.pauseDatasetSync,
  resumeDatasetSync: mocks.resumeDatasetSync, deleteDatasetSync: mocks.deleteDatasetSync, listSyncCredentials: mocks.listSyncCredentials,
  createDatasetSync: mocks.createDatasetSync, updateDatasetSync: mocks.updateDatasetSync, createSyncCredential: mocks.createSyncCredential,
  replaceSyncCredential: mocks.replaceSyncCredential, deleteSyncCredential: mocks.deleteSyncCredential,
}));
vi.mock('@/hooks/use-edition', () => ({ useEdition: mocks.useEdition }));
vi.mock('@/components/dataset/hooks/use-dataset', () => ({ useDatasetRefreshRuns: vi.fn() }));

function dataset(overrides: Partial<DatasetResponse> = {}): DatasetResponse {
  return {
    id: 'dataset-1', record_id: 'record-1', table_name: 'parks', title: 'Parks', summary: null, srid: 4326, geometry_type: 'Polygon', feature_count: 1, extent_bbox: null, column_info: null, license: null, attribution: null, source_organization: null, data_vintage_start: null, data_vintage_end: null, source_format: 'arcgis_featureserver', source_filename: null, tile_columns: null, original_srid: 4326, visibility: 'private', created_by: 'user-1', created_by_display: 'Owner', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', last_edited_by_display: null, last_edited_at: null, record_status: 'published', lineage_summary: null, update_frequency: 'daily', usage_constraints: null, access_constraints: null, sensitivity_classification: null, theme_category: null, owner_org: null, published_at: null, updated_by: null, current_version: 1, source_url: null, origin: 'service', origin_uri: 'https://maps.example.test/arcgis/rest/services/Parks/FeatureServer', origin_ref: { kind: 'service', service_type: 'arcgis_featureserver', url: 'https://maps.example.test/arcgis/rest/services/Parks/FeatureServer', layer_id: '0' }, last_refreshed_at: null, last_checked_at: null, source_health: 'healthy', schema_drift_status: 'none', source_freshness: 'fresh', quality_statement: null, collections: null, record_type: 'vector_dataset', raster: null,
    ...overrides,
  };
}

const configured = {
  id: 'sync-1', dataset_id: 'dataset-1', revision: 2, status: 'enabled' as const, pause_reason: null,
  source: { connector: 'arcgis_feature_server' as const, service_url: 'https://maps.example.test/arcgis/rest/services/Parks/FeatureServer', layer_id: 0 }, credential: null,
  cadence: { kind: 'hourly' as const, minute: 5 }, next_due_at: '2026-10-01T00:05:00Z', eligibility: { eligible: true, reasons: [], policy_version: 'arcgis_id_set_v1' }, last_occurrence: null, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
};

describe('SourceSyncPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.useEdition.mockReturnValue({ features: ['scheduled_sync'], isLoading: false, isResolved: true });
    mocks.getDatasetSync.mockResolvedValue(null);
    mocks.listSyncCredentials.mockResolvedValue([]);
  });

  it('shows a labelled loading state while the capability is unresolved', () => {
    mocks.useEdition.mockReturnValue({ features: [], isLoading: true, isResolved: false });
    render(<SourceSyncPanel dataset={dataset()} canEdit onRunDispatched={vi.fn()} />);
    expect(screen.getByLabelText('Loading scheduled sync')).toBeInTheDocument();
  });

  it('keeps community and unresolved sources passive', () => {
    mocks.useEdition.mockReturnValue({ features: [], isLoading: false, isResolved: true });
    const { rerender } = render(<SourceSyncPanel dataset={dataset()} canEdit onRunDispatched={vi.fn()} />);
    expect(screen.getByText(/Enterprise scheduling capability/)).toBeInTheDocument();
    mocks.useEdition.mockReturnValue({ features: ['scheduled_sync'], isLoading: false, isResolved: true });
    rerender(<SourceSyncPanel dataset={dataset({ origin_ref: null })} canEdit onRunDispatched={vi.fn()} />);
    expect(screen.getByText(/cannot be scheduled/)).toBeInTheDocument();
  });

  it('shows a schedule load error when no configuration can be displayed', async () => {
    mocks.getDatasetSync.mockRejectedValue(new Error('request failed'));
    render(<SourceSyncPanel dataset={dataset()} canEdit onRunDispatched={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Scheduled sync could not be loaded.');
  });

  it('does not expose paid mutations to readers', async () => {
    render(<SourceSyncPanel dataset={dataset()} canEdit={false} onRunDispatched={vi.fn()} />);
    expect(await screen.findByText(/owner or administrator can configure/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Set up schedule' })).not.toBeInTheDocument();
  });

  it('runs and detaches a configured schedule with its current revision', async () => {
    const user = userEvent.setup();
    mocks.getDatasetSync.mockResolvedValue(configured);
    mocks.runDatasetSync.mockResolvedValue({ occurrence_id: 'occ-1', run_id: 'run-1', job_id: 'job-1', state: 'planned' });
    mocks.deleteDatasetSync.mockResolvedValue(undefined);
    const onRunDispatched = vi.fn();
    render(<SourceSyncPanel dataset={dataset()} canEdit onRunDispatched={onRunDispatched} />);
    await screen.findByText('Enabled');

    await user.click(screen.getByRole('button', { name: 'Run verification' }));
    await waitFor(() => expect(mocks.runDatasetSync).toHaveBeenCalledWith('dataset-1', 2));
    expect(onRunDispatched).toHaveBeenCalledWith('run-1');

    await user.click(screen.getByRole('button', { name: 'Detach' }));
    await user.click(screen.getAllByRole('button', { name: 'Detach' }).at(-1)!);
    await waitFor(() => expect(mocks.deleteDatasetSync).toHaveBeenCalledWith('dataset-1', 2));
  });

  it('shows a revision-conflict message instead of server detail when verification dispatch is stale', async () => {
    const user = userEvent.setup();
    mocks.getDatasetSync.mockResolvedValue(configured);
    mocks.runDatasetSync.mockRejectedValue(new ApiError('stale revision', 409, { code: 'revision_conflict' }));
    render(<SourceSyncPanel dataset={dataset()} canEdit onRunDispatched={vi.fn()} />);
    await screen.findByText('Enabled');

    await user.click(screen.getByRole('button', { name: 'Run verification' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This schedule changed on the server.');
    expect(screen.queryByText('stale revision')).not.toBeInTheDocument();
  });

  it('shows a failed occurrence state with its safe actionable reason', async () => {
    mocks.getDatasetSync.mockResolvedValue({
      ...configured,
      last_occurrence: {
        id: 'occurrence-1', state: 'failed', scheduled_for: '2026-10-01T00:05:00Z', error_code: 'credential_expired',
      },
    });
    render(<SourceSyncPanel dataset={dataset()} canEdit onRunDispatched={vi.fn()} />);

    expect(await screen.findByText(/Failed/)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('The stored credential expired. Update it and run verification again.');
  });

  it('uses generic guidance instead of rendering an unknown failed-occurrence code', async () => {
    mocks.getDatasetSync.mockResolvedValue({
      ...configured,
      last_occurrence: {
        id: 'occurrence-2', state: 'failed', scheduled_for: '2026-10-01T00:05:00Z', error_code: 'internal_transport_failure',
      },
    });
    render(<SourceSyncPanel dataset={dataset()} canEdit onRunDispatched={vi.fn()} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('This scheduled run did not complete. Review the schedule and try again.');
    expect(screen.queryByText('internal_transport_failure')).not.toBeInTheDocument();
  });

  it('requires confirmation before enabling a schedule that replaces local data', async () => {
    const user = userEvent.setup();
    mocks.getDatasetSync.mockResolvedValue({ ...configured, status: 'paused' });
    mocks.resumeDatasetSync.mockResolvedValue({ ...configured, status: 'enabled' });
    render(<SourceSyncPanel dataset={dataset()} canEdit onRunDispatched={vi.fn()} />);
    await screen.findByText('Paused');

    await user.click(screen.getByRole('button', { name: 'Enable schedule' }));
    const confirmation = await screen.findByRole('alertdialog', { name: 'Enable scheduled sync?' });
    expect(confirmation).toHaveTextContent('Local changes may be overwritten.');
    expect(mocks.resumeDatasetSync).not.toHaveBeenCalled();
    await user.click(screen.getAllByRole('button', { name: 'Enable schedule' }).at(-1)!);
    await waitFor(() => expect(mocks.resumeDatasetSync).toHaveBeenCalledWith('dataset-1', 2));
  });
});
