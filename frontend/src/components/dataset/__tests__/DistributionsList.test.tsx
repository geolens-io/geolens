import { render, screen } from '@/test/test-utils';
import { useDistributions } from '@/components/dataset/hooks/use-records';
import { useTileConfig } from '@/hooks/use-settings';
import { resolveDistributionUrl } from '@/lib/dataset-access';
import {
  DistributionsList,
  getDistributionGroup,
} from '@/components/dataset/DistributionsList';

vi.mock('@/components/dataset/hooks/use-records', () => ({
  useDistributions: vi.fn(),
}));

vi.mock('@/hooks/use-settings', () => ({
  useTileConfig: vi.fn(),
}));

const mockUseDistributions = vi.mocked(useDistributions);
const mockUseTileConfig = vi.mocked(useTileConfig);

describe('DistributionsList', () => {
  beforeEach(() => {
    mockUseDistributions.mockReturnValue({
      data: {
        distributions: [],
        total: 0,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useDistributions>);
    mockUseTileConfig.mockReturnValue({
      data: {
        cdn_base_url: null,
        public_app_url: 'https://catalog.example.com',
        public_api_url: 'https://catalog.example.com/api',
        public_base_url: 'https://catalog.example.com',
      },
    } as ReturnType<typeof useTileConfig>);
  });

  it('maps backend distribution types into stable UI groups', () => {
    expect(getDistributionGroup('download')).toBe('download');
    expect(getDistributionGroup('ogc_features')).toBe('api');
    expect(getDistributionGroup('ogcService')).toBe('api');
    expect(getDistributionGroup('vector_tiles')).toBe('tiles');
    expect(getDistributionGroup('webApp')).toBe('other');
    expect(getDistributionGroup('unexpected_type')).toBe('other');
  });

  it('prefixes relative distribution URLs with the configured public base URL', () => {
    expect(resolveDistributionUrl('/datasets/1/export?format=gpkg', 'https://catalog.example.com/api')).toBe(
      'https://catalog.example.com/api/datasets/1/export?format=gpkg',
    );
    expect(resolveDistributionUrl('collections/1/items', 'https://catalog.example.com/api/')).toBe(
      'https://catalog.example.com/api/collections/1/items',
    );
    expect(resolveDistributionUrl('/tiles/data.example/{z}/{x}/{y}.pbf', 'https://catalog.example.com/api')).toBe(
      'https://catalog.example.com/api/tiles/data.example/{z}/{x}/{y}.pbf',
    );
    expect(resolveDistributionUrl('https://example.com/app', 'https://catalog.example.com/api')).toBe(
      'https://example.com/app',
    );
  });

  it('renders api, tile, and fallback sections from normalized backend types', () => {
    mockUseDistributions.mockReturnValue({
      data: {
        distributions: [
          {
            id: 'download-1',
            record_id: 'record-1',
            distribution_type: 'download',
            format: 'gpkg',
            url: '/datasets/1/export?format=gpkg',
            title: 'GeoPackage Download',
            description: null,
            protocol: 'HTTP',
            media_type: 'application/geopackage+sqlite3',
            is_primary: true,
            auto_generated: true,
          },
          {
            id: 'ogc-1',
            record_id: 'record-1',
            distribution_type: 'ogc_features',
            format: 'geojson',
            url: '/collections/1/items',
            title: 'OGC API Features',
            description: null,
            protocol: 'OGC:OAFeat',
            media_type: 'application/geo+json',
            is_primary: false,
            auto_generated: true,
          },
          {
            id: 'tiles-1',
            record_id: 'record-1',
            distribution_type: 'vector_tiles',
            format: 'pbf',
            url: '/tiles/data.example/{z}/{x}/{y}.pbf',
            title: 'Vector Tiles',
            description: null,
            protocol: 'OGC:WMTS',
            media_type: 'application/vnd.mapbox-vector-tile',
            is_primary: false,
            auto_generated: true,
          },
          {
            id: 'app-1',
            record_id: 'record-1',
            distribution_type: 'webApp',
            format: 'html',
            url: 'https://example.com/app',
            title: 'Viewer App',
            description: null,
            protocol: 'HTTPS',
            media_type: 'text/html',
            is_primary: false,
            auto_generated: false,
          },
        ],
        total: 4,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useDistributions>);

    render(<DistributionsList recordId="record-1" />);

    expect(screen.getByText('Downloads')).toBeInTheDocument();
    expect(screen.getByText('API Endpoints')).toBeInTheDocument();
    expect(screen.getByText('Tile Services')).toBeInTheDocument();
    expect(screen.getByText('Additional Access')).toBeInTheDocument();

    expect(screen.getByText('OGC API Features')).toBeInTheDocument();
    expect(screen.getByText('Vector Tiles')).toBeInTheDocument();
    expect(screen.getByText('Viewer App')).toBeInTheDocument();
    expect(screen.getByText('https://catalog.example.com/api/datasets/1/export?format=gpkg')).toBeInTheDocument();
    expect(screen.getByText('https://catalog.example.com/api/collections/1/items')).toBeInTheDocument();
    expect(screen.getByText('https://catalog.example.com/api/tiles/data.example/{z}/{x}/{y}.pbf')).toBeInTheDocument();
    expect(screen.getByText('https://example.com/app')).toBeInTheDocument();
  });
});
