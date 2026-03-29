import { render, screen } from '@/test/test-utils';
import type { OGCRecordResponse } from '@/types/api';
import { SearchResultCard } from '../SearchResultCard';

function makeFeature(
  propertyOverrides: Partial<OGCRecordResponse['properties']> = {},
  featureOverrides: Partial<OGCRecordResponse> = {},
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
    ...featureOverrides,
  };
}

describe('SearchResultCard', () => {
  // Vector card tests
  describe('Vector records', () => {
    it('renders title and links to /datasets/:id', () => {
      render(<SearchResultCard feature={makeFeature()} />);

      expect(screen.getByText('World Countries')).toBeInTheDocument();
      const link = screen.getByRole('link');
      expect(link).toHaveAttribute('href', '/datasets/dataset-1');
    });

    it('renders geometry type, feature count, and CRS in metadata line', () => {
      render(<SearchResultCard feature={makeFeature()} />);

      const specs = screen.getByTestId('dataset-card-specs');
      expect(specs).toHaveTextContent('Polygon');
      expect(specs).toHaveTextContent('195');
      expect(specs).toHaveTextContent('EPSG:4326');
    });

    it('renders Vector type badge', () => {
      render(<SearchResultCard feature={makeFeature({ record_type: undefined })} />);

      expect(screen.getByText('Vector')).toBeInTheDocument();
    });

    it('renders source organization', () => {
      render(<SearchResultCard feature={makeFeature()} />);

      expect(screen.getByTestId('dataset-card-source')).toHaveTextContent('Natural Earth');
    });

    it('renders updated time in footer attribution', () => {
      render(<SearchResultCard feature={makeFeature()} />);

      const attribution = screen.getByTestId('dataset-card-updated-attribution');
      expect(attribution).toBeInTheDocument();
      expect(attribution).toHaveTextContent('Updated');
    });

    it('does not render the metadata completeness badge on search cards', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            quality_detail: {
              overall: 73,
              metadata_completeness: 80,
              geometry_validity: 90,
              attribute_completeness: 70,
              crs_defined: 100,
              computed_at: '2026-03-02T00:00:00Z',
            },
          })}
        />,
      );

      expect(screen.queryByText(/Completeness:/i)).not.toBeInTheDocument();
    });
  });

  // Raster card tests
  describe('Raster records', () => {
    it('renders Raster type badge, band count, and gsd', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'raster_dataset',
            geometry_type: null,
            band_count: 4,
            gsd: 10,
            crs: 'EPSG:6527',
          })}
        />,
      );

      expect(screen.getByText('Raster')).toBeInTheDocument();
      const specs = screen.getByTestId('dataset-card-specs');
      expect(specs).toHaveTextContent('4 bands');
      expect(specs).toHaveTextContent('10 m');
    });
  });

  // VRT card tests
  describe('VRT records', () => {
    it('renders vrt_type label, source_count, and band count', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'vrt_dataset',
            geometry_type: null,
            band_count: 3,
            vrt_type: 'mosaic',
            source_count: 12,
          })}
        />,
      );

      expect(screen.getByText('Virtual Raster')).toBeInTheDocument();
      const specs = screen.getByTestId('dataset-card-specs');
      expect(specs).toHaveTextContent('Mosaic');
      expect(specs).toHaveTextContent('12 sources');
      expect(specs).toHaveTextContent('3 bands');
    });

    it('renders band_stack as "Band Stack"', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'vrt_dataset',
            geometry_type: null,
            band_count: 6,
            vrt_type: 'band_stack',
            source_count: 3,
          })}
        />,
      );

      expect(screen.getByTestId('dataset-card-specs')).toHaveTextContent('Band Stack');
    });
  });

  // Collection card tests
  describe('Collection records', () => {
    it('renders title and links to /collections/:id', () => {
      render(
        <SearchResultCard
          feature={makeFeature(
            {
              type: 'collection',
              title: 'My Collection',
              description: 'A set of datasets',
              record_type: 'collection',
              dataset_count: 7,
              keywords: null,
              geometry_type: null,
              feature_count: null,
              crs: null,
              source_organization: null,
              quality_detail: null,
              updated_by_display: null,
              never_edited: true,
            },
            { id: 'coll-1', geometry: null },
          )}
        />,
      );

      expect(screen.getByText('My Collection')).toBeInTheDocument();
      const link = screen.getByRole('link');
      expect(link).toHaveAttribute('href', '/collections/coll-1');
    });

    it('renders dataset count badge and Collection type badge', () => {
      render(
        <SearchResultCard
          feature={makeFeature(
            {
              type: 'collection',
              title: 'My Collection',
              description: null,
              record_type: 'collection',
              dataset_count: 5,
              keywords: null,
              geometry_type: null,
              feature_count: null,
              crs: null,
              source_organization: null,
              quality_detail: null,
              updated_by_display: null,
              never_edited: true,
            },
            { id: 'coll-2', geometry: null },
          )}
        />,
      );

      expect(screen.getByText('Collection')).toBeInTheDocument();
      expect(screen.getByText('5 datasets')).toBeInTheDocument();
    });

    it('renders description for collections', () => {
      render(
        <SearchResultCard
          feature={makeFeature(
            {
              type: 'collection',
              title: 'Described Collection',
              description: 'This is a detailed description',
              record_type: 'collection',
              dataset_count: 3,
              keywords: null,
              geometry_type: null,
              feature_count: null,
              crs: null,
              source_organization: null,
              quality_detail: null,
              updated_by_display: null,
              never_edited: true,
            },
            { id: 'coll-3', geometry: null },
          )}
        />,
      );

      expect(screen.getByText('This is a detailed description')).toBeInTheDocument();
    });
  });

  // Tags tests
  describe('Tags', () => {
    it('renders max 3 tags with overflow indicator', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            keywords: ['boundaries', 'countries', 'political', 'world'],
          })}
        />,
      );

      expect(screen.getByText('boundaries')).toBeInTheDocument();
      expect(screen.getByText('countries')).toBeInTheDocument();
      expect(screen.getByText('political')).toBeInTheDocument();
      expect(screen.queryByText('world')).not.toBeInTheDocument();
      expect(screen.getByText(/\+1 more/)).toBeInTheDocument();
    });

    it('filters out synthetic and perf-seed keywords', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            keywords: ['synthetic', 'perf-seed', 'boundaries'],
          })}
        />,
      );

      expect(screen.queryByText('synthetic')).not.toBeInTheDocument();
      expect(screen.queryByText('perf-seed')).not.toBeInTheDocument();
      expect(screen.getByText('boundaries')).toBeInTheDocument();
    });

    it('filters out blank and whitespace-only keywords', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            keywords: ['', '   ', 'zoning'],
          })}
        />,
      );

      expect(screen.getByText('zoning')).toBeInTheDocument();
      expect(screen.queryByText(/\+1 more/)).not.toBeInTheDocument();
    });
  });

  // Table record tests
  describe('Table records', () => {
    it('renders Table type badge', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'table',
            geometry_type: null,
            feature_count: 500,
            crs: null,
          })}
        />,
      );

      expect(screen.getByText('Table')).toBeInTheDocument();
    });

    it('shows "X rows" not "X features" in specs', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'table',
            geometry_type: null,
            feature_count: 500,
            crs: null,
          })}
        />,
      );

      const specs = screen.getByTestId('dataset-card-specs');
      expect(specs).toHaveTextContent('500 rows');
      expect(specs).not.toHaveTextContent('500 features');
    });

    it('still shows "X features" for vector records (regression check)', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'vector_dataset',
            feature_count: 195,
          })}
        />,
      );

      const specs = screen.getByTestId('dataset-card-specs');
      expect(specs).toHaveTextContent('195 features');
      expect(specs).not.toHaveTextContent('195 rows');
    });
  });

  // Description tests
  describe('Description display', () => {
    it('renders real description when provided', () => {
      render(<SearchResultCard feature={makeFeature({ description: 'A real description' })} />);

      expect(screen.getByTestId('dataset-card-description')).toHaveTextContent('A real description');
    });

    it('renders auto-description when description is null', () => {
      render(<SearchResultCard feature={makeFeature({ description: null })} />);

      const desc = screen.getByTestId('dataset-card-description');
      expect(desc).toBeInTheDocument();
      // Auto-generated for vector: "Polygon dataset with 195 features in EPSG:4326"
      expect(desc).toHaveTextContent('Polygon');
      expect(desc).toHaveTextContent('195');
      expect(desc).toHaveTextContent('EPSG:4326');
    });

    it('renders auto-description for raster records', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            description: null,
            record_type: 'raster_dataset',
            band_count: 4,
            gsd: 10,
            crs: 'EPSG:6527',
          })}
        />,
      );

      const desc = screen.getByTestId('dataset-card-description');
      expect(desc).toBeInTheDocument();
      expect(desc).toHaveTextContent('4 bands');
      expect(desc).toHaveTextContent('10 m');
    });

    it('does not render description testid for collection records', () => {
      render(
        <SearchResultCard
          feature={makeFeature(
            {
              type: 'collection',
              title: 'My Collection',
              description: null,
              record_type: 'collection',
              dataset_count: 5,
              keywords: null,
              geometry_type: null,
              feature_count: null,
              crs: null,
              source_organization: null,
              quality_detail: null,
              updated_by_display: null,
              never_edited: true,
            },
            { id: 'coll-desc', geometry: null },
          )}
        />,
      );

      expect(screen.queryByTestId('dataset-card-description')).not.toBeInTheDocument();
    });
  });

  // Collection layout tests
  describe('Collection card layout', () => {
    it('does not render specs row for collections', () => {
      render(
        <SearchResultCard
          feature={makeFeature(
            {
              type: 'collection',
              title: 'Test Collection',
              description: 'A collection',
              record_type: 'collection',
              dataset_count: 10,
              keywords: null,
              geometry_type: null,
              feature_count: null,
              crs: null,
              source_organization: null,
              quality_detail: null,
              updated_by_display: null,
              never_edited: true,
            },
            { id: 'coll-layout', geometry: null },
          )}
        />,
      );

      expect(screen.queryByTestId('dataset-card-specs')).not.toBeInTheDocument();
    });

    it('does not render tags for collections', () => {
      render(
        <SearchResultCard
          feature={makeFeature(
            {
              type: 'collection',
              title: 'Tagged Collection',
              description: null,
              record_type: 'collection',
              dataset_count: 3,
              keywords: ['should', 'not', 'appear'],
              geometry_type: null,
              feature_count: null,
              crs: null,
              source_organization: null,
              quality_detail: null,
              updated_by_display: null,
              never_edited: true,
            },
            { id: 'coll-tags', geometry: null },
          )}
        />,
      );

      expect(screen.queryByText('should')).not.toBeInTheDocument();
      expect(screen.queryByText('not')).not.toBeInTheDocument();
      expect(screen.queryByText('appear')).not.toBeInTheDocument();
    });

    it('does not render source organization for collections', () => {
      render(
        <SearchResultCard
          feature={makeFeature(
            {
              type: 'collection',
              title: 'Org Collection',
              description: null,
              record_type: 'collection',
              dataset_count: 1,
              keywords: null,
              geometry_type: null,
              feature_count: null,
              crs: null,
              source_organization: 'Should Not Show',
              quality_detail: null,
              updated_by_display: null,
              never_edited: true,
            },
            { id: 'coll-org', geometry: null },
          )}
        />,
      );

      expect(screen.queryByTestId('dataset-card-source')).not.toBeInTheDocument();
    });
  });

  // Spec styling tests
  describe('Spec styling', () => {
    it('renders specs as icon+plain-text without pill background', () => {
      render(<SearchResultCard feature={makeFeature()} />);

      const specs = screen.getByTestId('dataset-card-specs');
      // Specs should not contain rounded-full pill elements
      const pillElements = specs.querySelectorAll('.rounded-full');
      expect(pillElements).toHaveLength(0);
    });

    it('renders spec text without bg-muted pill backgrounds', () => {
      render(<SearchResultCard feature={makeFeature()} />);

      const specs = screen.getByTestId('dataset-card-specs');
      const bgMutedElements = specs.querySelectorAll('[class*="bg-muted"]');
      expect(bgMutedElements).toHaveLength(0);
    });
  });

  // Status badge tests
  describe('Status badges', () => {
    it('renders draft badge for non-published datasets', () => {
      render(
        <SearchResultCard
          feature={makeFeature({ record_status: 'draft' })}
        />,
      );

      expect(screen.getByText('Draft')).toBeInTheDocument();
    });

    it('renders status badge in footer area', () => {
      render(
        <SearchResultCard
          feature={makeFeature({ record_status: 'internal' })}
        />,
      );
      expect(screen.getByText('Internal')).toBeInTheDocument();
    });

    it('does not render status badge for published records', () => {
      render(
        <SearchResultCard
          feature={makeFeature({ record_status: 'published' })}
        />,
      );
      expect(screen.queryByText('Draft')).not.toBeInTheDocument();
      expect(screen.queryByText('Internal')).not.toBeInTheDocument();
      expect(screen.queryByText('Ready')).not.toBeInTheDocument();
    });

    it('does not render status badges for collections', () => {
      render(
        <SearchResultCard
          feature={makeFeature(
            {
              type: 'collection',
              title: 'Collection',
              description: null,
              record_type: 'collection',
              record_status: 'draft',
              dataset_count: 1,
              keywords: null,
              geometry_type: null,
              feature_count: null,
              crs: null,
              source_organization: null,
              quality_detail: null,
              updated_by_display: null,
              never_edited: true,
            },
            { id: 'coll-4', geometry: null },
          )}
        />,
      );

      expect(screen.queryByText('Draft')).not.toBeInTheDocument();
    });
  });
});
