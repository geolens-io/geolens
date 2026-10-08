import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { VersionHistory } from '@/components/dataset/VersionHistory';
import { getDatasetVersions, restorePreviousVersion } from '@/api/datasets';
import type { DatasetResponse, DatasetVersionResponse } from '@/types/api';

vi.mock('@/api/datasets', () => ({
  getDatasetVersions: vi.fn(),
  restorePreviousVersion: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const dataset = {
  id: 'ds-1',
  title: 'Roads',
  current_version: 3,
  previous_version: { version_number: 2 },
  created_by: 'user-1',
  created_at: '2026-01-01T00:00:00Z',
} as DatasetResponse;

function version(number: number) {
  return {
    id: `v${number}`,
    dataset_id: 'ds-1',
    version_number: number,
    source_filename: `roads-v${number}.geojson`,
    source_format: 'geojson',
    feature_count: 10,
    srid: 4326,
    geometry_type: 'LineString',
    file_hash: null,
    uploaded_by: 'user-1',
    uploaded_at: '2026-02-01T00:00:00Z',
  } as DatasetVersionResponse;
}

beforeEach(() => {
  vi.mocked(getDatasetVersions).mockResolvedValue({
    versions: [version(3), version(2), version(1)],
    total: 3,
  });
  vi.mocked(restorePreviousVersion).mockReset();
});

describe('restore previous version', () => {
  it('offers the action only on the kept version, and only with write access', async () => {
    const { unmount } = render(<VersionHistory datasetId='ds-1' dataset={dataset} canEdit />);
    await screen.findByText('Version 2');
    expect(screen.getAllByRole('button', { name: 'Restore' })).toHaveLength(1);
    unmount();

    render(<VersionHistory datasetId='ds-1' dataset={dataset} />);
    await screen.findByText('Version 2');
    expect(screen.queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument();
  });

  it('hides the action when no previous version is kept', async () => {
    render(
      <VersionHistory
        datasetId='ds-1'
        dataset={{ ...dataset, previous_version: null }}
        canEdit
      />,
    );
    await screen.findByText('Version 2');
    expect(screen.queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument();
  });

  it('requires the dataset name, then restores and refetches history', async () => {
    const user = userEvent.setup();
    vi.mocked(restorePreviousVersion).mockResolvedValue({ job_id: 'j', run_id: 'r' });
    render(<VersionHistory datasetId='ds-1' dataset={dataset} canEdit />);

    await user.click(await screen.findByRole('button', { name: 'Restore' }));
    const confirm = screen.getByRole('button', { name: 'Restore version' });
    expect(confirm).toBeDisabled();
    expect(screen.getByText(/Feature edits made since version 2/)).toBeInTheDocument();
    expect(screen.getByText(/Mosaics that use this dataset/)).toBeInTheDocument();

    await user.type(screen.getByRole('textbox'), 'Roads');
    expect(confirm).toBeEnabled();
    const fetchesBefore = vi.mocked(getDatasetVersions).mock.calls.length;
    await user.click(confirm);

    await waitFor(() => expect(restorePreviousVersion).toHaveBeenCalledWith('ds-1', 2));
    await waitFor(() =>
      expect(vi.mocked(getDatasetVersions).mock.calls.length).toBeGreaterThan(fetchesBefore),
    );
  });

  it('keeps the dialog open and shows the refusal', async () => {
    const user = userEvent.setup();
    vi.mocked(restorePreviousVersion).mockRejectedValue(new Error('Another run is active'));
    render(<VersionHistory datasetId='ds-1' dataset={dataset} canEdit />);

    await user.click(await screen.findByRole('button', { name: 'Restore' }));
    await user.type(screen.getByRole('textbox'), 'Roads');
    await user.click(screen.getByRole('button', { name: 'Restore version' }));

    expect(await screen.findByText('Another run is active')).toBeInTheDocument();
  });
});
