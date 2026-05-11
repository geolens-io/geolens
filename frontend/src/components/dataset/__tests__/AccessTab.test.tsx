import { render, screen } from '@/test/test-utils';
import { useDistributions } from '@/components/dataset/hooks/use-records';
import { useTileConfig } from '@/hooks/use-settings';
import { AccessTab } from '../tabs/AccessTab';
import type { DatasetResponse } from '@/types/api';

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
    geometry_type: null,
    feature_count: 3,
    extent_bbox: null,
    column_info: null,
    license: null,
    source_organization: null,
    data_vintage_start: null,
    data_vintage_end: null,
    source_format: 'csv',
    source_filename: 'parks.csv',
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
    record_type: 'table',
    raster: null,
    ...overrides,
    tile_columns: overrides.tile_columns ?? null,
  };
}

describe('AccessTab', () => {
  beforeEach(() => {
    mockUseDistributions.mockReturnValue({
      data: {
        distributions: [
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
            is_primary: true,
            auto_generated: true,
          },
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
            is_primary: false,
            auto_generated: true,
          },
        ],
        total: 2,
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

  it('renders a distribution-backed OGC snippet and csv-only export for table datasets', () => {
    render(<AccessTab dataset={makeDataset()} />);

    expect(screen.getByText('Access via API')).toBeInTheDocument();

    const codeBlock = document.querySelector('pre');
    expect(codeBlock).not.toBeNull();
    expect(codeBlock).toHaveTextContent('https://catalog.example.com/api/collections/ds-1/items?limit=10');
    expect(codeBlock).not.toHaveTextContent('/api/v1/collections/public_parks');
    expect(codeBlock).not.toHaveTextContent('public_parks');

    const select = screen.getByRole('combobox', { name: 'Export format' });
    const options = Array.from(select.querySelectorAll('option'));
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveValue('csv');
  });

  it('hides the API snippet for raster datasets that do not expose OGC features', () => {
    render(
      <AccessTab
        dataset={makeDataset({
          record_type: 'raster_dataset',
          raster: {
            tile_url: 'https://tiles.example.com/{z}/{x}/{y}.png',
            connect: {
              download_url: '/datasets/ds-1/download/cog',
              tile_url: 'https://tiles.example.com/{z}/{x}/{y}.png',
              s3_uri: null,
            },
          } as DatasetResponse['raster'],
        })}
      />,
    );

    expect(screen.queryByText('Access via API')).not.toBeInTheDocument();
  });
});
