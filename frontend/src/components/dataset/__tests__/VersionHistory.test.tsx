import { render, screen } from '@/test/test-utils';
import { useDatasetVersions } from '@/components/dataset/hooks/use-dataset';
import { VersionHistory } from '@/components/dataset/VersionHistory';
import type { DatasetResponse, DatasetVersionResponse } from '@/types/api';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetVersions: vi.fn(),
}));

const mockUseDatasetVersions = vi.mocked(useDatasetVersions);

const dataset = {
  id: 'ds-1',
  current_version: 2,
  source_filename: 'roads-2026.geojson',
  source_format: 'geojson',
  feature_count: 900,
  srid: 4326,
  geometry_type: 'LineString',
  created_by: 'user-1',
  created_at: '2026-01-01T00:00:00Z',
} as DatasetResponse;

function version(
  number: number,
  overrides: Partial<DatasetVersionResponse> = {},
) {
  return {
    id: `v${number}`,
    dataset_id: 'ds-1',
    version_number: number,
    source_filename: `roads-v${number}.geojson`,
    source_format: 'geojson',
    feature_count: 100 * number,
    srid: 4326,
    geometry_type: 'LineString',
    file_hash: null,
    uploaded_by: 'user-1',
    uploaded_at: '2026-02-01T00:00:00Z',
    ...overrides,
  } as DatasetVersionResponse;
}

function withVersions(
  versions: DatasetVersionResponse[],
  total = versions.length,
) {
  mockUseDatasetVersions.mockReturnValue({
    data: { versions, total },
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof useDatasetVersions>);
}

describe('VersionHistory', () => {
  it('shows the unrecorded first version of a replaced dataset as unknown', () => {
    withVersions([
      version(2, { source_filename: 'roads-2026.geojson', feature_count: 900 }),
    ]);

    render(<VersionHistory datasetId='ds-1' dataset={dataset} />);

    expect(screen.getByText('Version 1')).toBeInTheDocument();
    expect(screen.getAllByText(/roads-2026\.geojson/)).toHaveLength(1);
    expect(screen.getAllByText(/900 features/)).toHaveLength(1);
    expect(screen.getByText(/Unknown file/)).toBeInTheDocument();
    expect(
      screen.getByText('Details of this version were not recorded.'),
    ).toBeInTheDocument();
  });

  it('shows the facts of a never-replaced dataset as its first version', () => {
    withVersions([]);

    render(
      <VersionHistory
        datasetId='ds-1'
        dataset={{ ...dataset, current_version: 1 } as DatasetResponse}
      />,
    );

    expect(screen.getByText(/roads-2026\.geojson/)).toBeInTheDocument();
    expect(screen.getByText(/900 features/)).toBeInTheDocument();
    expect(
      screen.queryByText('Details of this version were not recorded.'),
    ).toBeNull();
  });

  it('keeps a recorded first version as recorded', () => {
    withVersions([version(2), version(1)]);

    render(<VersionHistory datasetId='ds-1' dataset={dataset} />);

    expect(screen.getByText(/roads-v1\.geojson/)).toBeInTheDocument();
    expect(screen.queryByText(/Unknown file/)).toBeNull();
    expect(
      screen.queryByText('Details of this version were not recorded.'),
    ).toBeNull();
  });

  it('invents no first version when the history is longer than the page', () => {
    withVersions([version(3), version(2)], 3);

    render(
      <VersionHistory
        datasetId='ds-1'
        dataset={{ ...dataset, current_version: 3 } as DatasetResponse}
      />,
    );

    expect(screen.queryByText('Version 1')).toBeNull();
  });
});
