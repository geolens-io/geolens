import { render, screen } from '@/test/test-utils';
import type { OGCRecordResponse } from '@/types/api';
import { DatasetCard } from '../DatasetCard';

function makeFeature(
  propertyOverrides: Partial<OGCRecordResponse['properties']> = {},
): OGCRecordResponse {
  return {
    type: 'Feature',
    id: 'dataset-1',
    geometry: {
      type: 'Polygon',
      coordinates: [[
        [-124.8, 24.4],
        [-66.9, 24.4],
        [-66.9, 49.3],
        [-124.8, 49.3],
        [-124.8, 24.4],
      ]],
    },
    properties: {
      type: 'dataset',
      title: 'World Countries',
      description: 'Boundary polygons for countries.',
      keywords: ['boundaries', 'countries'],
      created: '2026-03-01T00:00:00Z',
      updated: '2026-03-02T00:00:00Z',
      updated_by_display: 'editor-user',
      never_edited: false,
      crs: 'EPSG:4326',
      geometry_type: 'Polygon',
      feature_count: 195,
      contact: null,
      license: null,
      source_organization: 'Natural Earth',
      quality_detail: null,
      ...propertyOverrides,
    },
    links: [
      {
        rel: 'self',
        href: 'http://localhost:8000/collections/datasets/items/dataset-1',
        type: 'application/geo+json',
      },
    ],
  };
}

describe('DatasetCard', () => {
  it('wraps the entire card in a link to the dataset detail page', () => {
    render(<DatasetCard feature={makeFeature()} />);

    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/datasets/dataset-1');
  });

  it('renders compact updated-by attribution line on cards', () => {
    render(<DatasetCard feature={makeFeature()} />);

    const attribution = screen.getByTestId('dataset-card-updated-attribution');
    expect(attribution).toHaveTextContent('Updated by');
    expect(attribution).toHaveTextContent('editor-user');
    expect(attribution).toHaveTextContent(/ago|yesterday|today|last|now/i);
  });

  it('keeps full identity in title attribute for long editor names', () => {
    const longIdentity = 'very-long-editor-name-that-should-remain-readable-in-tooltip';

    render(
      <DatasetCard
        feature={makeFeature({
          updated_by_display: longIdentity,
        })}
      />,
    );

    expect(screen.getByText(longIdentity)).toHaveAttribute('title', longIdentity);
  });

  it('renders "Created X ago" fallback when never_edited but created date exists', () => {
    render(
      <DatasetCard
        feature={makeFeature({
          updated_by_display: null,
          never_edited: true,
          created: '2026-03-01T00:00:00Z',
        })}
      />,
    );

    expect(screen.getByTestId('dataset-card-updated-attribution')).toHaveTextContent(/Updated/i);
  });

  it('renders "No update metadata" when never_edited and created is null', () => {
    render(
      <DatasetCard
        feature={makeFeature({
          updated_by_display: null,
          never_edited: true,
          created: null,
        })}
      />,
    );

    expect(screen.getByTestId('dataset-card-updated-attribution')).toHaveTextContent('No update metadata');
  });

  it('renders restricted user attribution correctly', () => {
    render(
      <DatasetCard
        feature={makeFeature({
          updated_by_display: 'Restricted user',
          never_edited: false,
        })}
      />,
    );
    expect(screen.getByTestId('dataset-card-updated-attribution')).toHaveTextContent('Restricted user');
  });

  it('shows source_organization in the metadata line', () => {
    render(<DatasetCard feature={makeFeature()} />);

    expect(screen.getByText(/Natural Earth/)).toBeInTheDocument();
  });

  it('renders Vector type badge for vector datasets', () => {
    render(<DatasetCard feature={makeFeature({ record_type: undefined, geometry_type: 'Polygon' })} />);

    expect(screen.getByText('Vector')).toBeInTheDocument();
  });

  it('renders Raster type badge for raster datasets', () => {
    render(<DatasetCard feature={makeFeature({ record_type: 'raster_dataset', geometry_type: null, band_count: 3 })} />);

    expect(screen.getByText('Raster')).toBeInTheDocument();
  });

  it('renders Virtual Raster type badge for VRT datasets', () => {
    render(<DatasetCard feature={makeFeature({ record_type: 'vrt_dataset', geometry_type: null, band_count: 1 })} />);

    expect(screen.getByText('Virtual Raster')).toBeInTheDocument();
  });
});
