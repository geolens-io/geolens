import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { useDistributions } from '@/components/dataset/hooks/use-records';
import { useTileConfig } from '@/hooks/use-settings';
import { ConnectDropdown } from '../ConnectDropdown';
import type { DatasetResponse } from '@/types/api';

vi.mock('@/stores/auth-store', () => ({
  useAuthStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ user: { roles: ['admin'] }, token: 'test' }),
}));

vi.mock('@/components/dataset/hooks/use-records', () => ({
  useDistributions: vi.fn(),
}));

vi.mock('@/hooks/use-settings', () => ({
  useTileConfig: vi.fn(),
}));

const mockUseDistributions = vi.mocked(useDistributions);
const mockUseTileConfig = vi.mocked(useTileConfig);

function makeDataset(overrides: Partial<DatasetResponse> = {}): DatasetResponse {
  return {
    id: 'ds-1',
    record_id: 'rec-1',
    table_name: 'public_parks',
    title: 'Parks',
    summary: null,
    srid: 4326,
    geometry_type: 'Polygon',
    feature_count: 100,
    extent_bbox: null,
    column_info: null,
    license: null,
    source_organization: null,
    data_vintage_start: null,
    data_vintage_end: null,
    source_format: null,
    source_filename: null,
    original_srid: null,
    visibility: 'public',
    created_by: null,
    created_by_display: 'admin',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    last_edited_by_display: null,
    last_edited_at: null,
    record_status: 'published',
    lineage_summary: null,
    update_frequency: null,
    usage_constraints: null,
    access_constraints: null,
    sensitivity_classification: null,
    theme_category: null,
    owner_org: null,
    published_at: null,
    updated_by: null,
    current_version: 1,
    source_url: null,
    quality_statement: null,
    collections: null,
    record_type: 'vector_dataset',
    raster: null,
    ...overrides,
    tile_columns: overrides.tile_columns ?? null,
  };
}

describe('ConnectDropdown', () => {
  beforeEach(() => {
    mockUseDistributions.mockReturnValue({
      data: {
        distributions: [
          {
            id: 'dist-ogc',
            record_id: 'rec-1',
            distribution_type: 'ogc_features',
            format: 'geojson',
            url: '/collections/ds-1/items',
            title: 'OGC API Features',
            description: null,
            protocol: 'OGC:OAFeat',
            media_type: 'application/geo+json',
            is_primary: true,
            auto_generated: true,
          },
          {
            id: 'dist-csv',
            record_id: 'rec-1',
            distribution_type: 'download',
            format: 'csv',
            url: '/datasets/ds-1/export?format=csv',
            title: 'CSV Download',
            description: null,
            protocol: 'HTTP',
            media_type: 'text/csv',
            is_primary: false,
            auto_generated: true,
          },
          {
            id: 'dist-tiles',
            record_id: 'rec-1',
            distribution_type: 'vector_tiles',
            format: 'pbf',
            url: '/tiles/data.public_parks/{z}/{x}/{y}.pbf',
            title: 'Vector Tiles',
            description: null,
            protocol: 'OGC:WMTS',
            media_type: 'application/vnd.mapbox-vector-tile',
            is_primary: false,
            auto_generated: true,
          },
        ],
        total: 3,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useDistributions>);
    mockUseTileConfig.mockReturnValue({
      data: {
        public_api_url: 'https://catalog.example.com/api',
        public_base_url: 'https://catalog.example.com',
      },
    } as ReturnType<typeof useTileConfig>);
  });

  it('renders OGC features and vector tiles actions for spatial datasets', async () => {
    const user = userEvent.setup();
    render(<ConnectDropdown dataset={makeDataset()} />);

    await user.click(screen.getByRole('button', { name: /connect/i }));

    expect(screen.getByText('Copy OGC Features URL')).toBeInTheDocument();
    expect(screen.getByText('Copy Vector Tiles URL')).toBeInTheDocument();
    expect(screen.queryByText('Copy CSV Export URL')).not.toBeInTheDocument();
  });

  it('renders OGC features and CSV actions for table datasets', async () => {
    const user = userEvent.setup();
    render(<ConnectDropdown dataset={makeDataset({ record_type: 'table' })} />);

    await user.click(screen.getByRole('button', { name: /connect/i }));

    expect(screen.getByText('Copy OGC Features URL')).toBeInTheDocument();
    expect(screen.getByText('Copy CSV Export URL')).toBeInTheDocument();
    expect(screen.queryByText('Copy Vector Tiles URL')).not.toBeInTheDocument();
  });

  it('renders raster-specific items for raster datasets', async () => {
    const user = userEvent.setup();
    render(
      <ConnectDropdown
        dataset={makeDataset({
          record_type: 'raster_dataset',
          raster: {
            tile_url: 'http://tiles/xyz',
            connect: {
              download_url: '/api/datasets/ds-1/download/cog',
              tile_url: 'http://tiles/{z}/{x}/{y}.png',
              s3_uri: 's3://bucket/key.tif',
            },
          } as DatasetResponse['raster'],
        })}
      />,
    );

    await user.click(screen.getByRole('button', { name: /connect/i }));

    expect(screen.getByText('Copy COG URL')).toBeInTheDocument();
    expect(screen.getByText('Copy XYZ Tile URL')).toBeInTheDocument();
    expect(screen.getByText('Copy S3 URI')).toBeInTheDocument();
    expect(screen.queryByText('Copy OGC Features URL')).not.toBeInTheDocument();
    expect(screen.queryByText('Copy Vector Tiles URL')).not.toBeInTheDocument();
  });
});
