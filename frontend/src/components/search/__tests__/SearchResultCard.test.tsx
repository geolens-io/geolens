import { fireEvent, render, screen, waitFor, within } from '@/test/test-utils';
import { getDataset } from '@/api/datasets';
import type { OGCRecordResponse } from '@/types/api';
import { useQuicklook } from '@/components/maps/hooks/use-quicklook';
import { SearchResultCard } from '../SearchResultCard';

vi.mock('@/api/datasets', () => ({ getDataset: vi.fn(() => Promise.resolve({})) }));

vi.mock('@/components/maps/hooks/use-quicklook', () => ({
  useQuicklook: vi.fn(() => ({ url: null, status: 'idle' })),
}));

function makeFeature(
  propertyOverrides: Partial<OGCRecordResponse['properties']> = {},
  featureOverrides: Partial<OGCRecordResponse> = {},
): OGCRecordResponse {
  return {
    type: 'Feature',
    id: 'dataset-1',
    time: {},
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
      record_type: 'vector_dataset',
      themes: [],
      time: {},
      source_freshness: 'unknown',
      source_health: 'unknown',
      has_quicklook: false,
      crs: 'EPSG:4326',
      geometry_type: 'Polygon',
      feature_count: 195,
      contacts: [],
      license: 'proprietary',
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
    it('exposes the title as a heading inside the card link', () => {
      render(<SearchResultCard feature={makeFeature()} />, { route: '/' });
      const link = screen.getByRole('link');
      expect(within(link).getByRole('heading', { level: 3, name: 'World Countries' })).toBeInTheDocument();
      expect(link.className).toContain('focus-visible:ring-2');
    });

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

  describe('Source state', () => {
    it('wires freshness and optional health summary fields into visible chips', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            source_format: 'stac',
            source_freshness: 'overdue',
            source_health: 'inaccessible',
          })}
        />,
      );

      expect(screen.getByTestId('origin-badge')).toHaveAttribute('data-origin', 'stac');
      expect(screen.getByTestId('source-freshness-chip')).toHaveAttribute('data-state', 'overdue');
      expect(screen.getByText('Source refresh overdue')).toBeVisible();
      expect(screen.getByTestId('source-health-chip')).toHaveAttribute('data-state', 'inaccessible');
      expect(screen.getByText('Source inaccessible')).toBeVisible();
    });

    it('stays silent when source state is unknown or omitted', () => {
      render(
        <SearchResultCard
          feature={makeFeature({ source_freshness: 'unknown' })}
        />,
      );

      expect(screen.queryByTestId('source-freshness-chip')).not.toBeInTheDocument();
      expect(screen.queryByTestId('source-health-chip')).not.toBeInTheDocument();
    });

    it('does not show dataset source state on collection cards', () => {
      render(
        <SearchResultCard
          feature={makeFeature(
            {
              type: 'collection',
              title: 'Collection',
              description: '',
              record_type: 'collection',
              dataset_count: 1,
              keywords: [],
              geometry_type: null,
              feature_count: null,
              crs: null,
              source_organization: null,
              quality_detail: null,
              updated_by_display: null,
              never_edited: true,
              source_freshness: 'overdue',
              source_health: 'missing',
            },
            { id: 'coll-source-state', geometry: null },
          )}
        />,
      );

      expect(screen.queryByTestId('source-freshness-chip')).not.toBeInTheDocument();
      expect(screen.queryByTestId('source-health-chip')).not.toBeInTheDocument();
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

    it('dims quicklook imagery in dark mode to prevent bright thumbnail glare', () => {
      vi.mocked(useQuicklook).mockReturnValueOnce({
        url: 'blob:quicklook-preview',
        status: 'ready',
      });

      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'raster_dataset',
            geometry_type: null,
            has_quicklook: true,
          })}
        />,
      );

      const quicklook = screen.getByRole('img', { name: 'Preview of World Countries' });
      expect(quicklook).toHaveAttribute('src', 'blob:quicklook-preview');
      expect(quicklook).toHaveClass('dark:brightness-75');
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

    it.each([5, 1])('shows a source count of %i', (count) => {
      render(
        <SearchResultCard
          feature={makeFeature({ record_type: 'vrt_dataset', description: '', geometry_type: null, vrt_type: 'mosaic', source_count: count })}
        />,
      );

      expect(screen.getByTestId('dataset-card-specs')).toHaveTextContent(count === 1 ? '1 source' : `${count} sources`);
      expect(screen.getByText(new RegExp(`with ${count} source`))).toBeInTheDocument();
    });

    it.each([0, null])('leaves the count out when source_count is %s', (count) => {
      render(
        <SearchResultCard
          feature={makeFeature({ record_type: 'vrt_dataset', description: '', geometry_type: null, vrt_type: 'mosaic', source_count: count })}
        />,
      );

      expect(screen.getByTestId('dataset-card-specs')).toHaveTextContent('Mosaic');
      expect(screen.queryByText(/\bsources?\b/i)).not.toBeInTheDocument();
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
              keywords: [],
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
              description: '',
              record_type: 'collection',
              dataset_count: 5,
              keywords: [],
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
              keywords: [],
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

    it('renders Table2 icon in thumbnail tile instead of ImageOff', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'table',
            geometry_type: null,
            feature_count: 29,
            crs: null,
          })}
        />,
      );

      // Table2 icon present via data-testid
      expect(screen.getByTestId('table-thumbnail-icon')).toBeInTheDocument();
    });

    it('renders row count in thumbnail tile', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'table',
            geometry_type: null,
            feature_count: 29,
            crs: null,
          })}
        />,
      );

      // Multiple elements may contain "29 rows" (specs + tile); verify the tile span specifically
      const allRowCountEls = screen.getAllByText(/29 rows/i);
      expect(allRowCountEls.length).toBeGreaterThanOrEqual(1);
      // The thumbnail tile span has class "tabular-nums"
      const tileLabel = allRowCountEls.find((el) => el.className.includes('tabular-nums'));
      expect(tileLabel).toBeInTheDocument();
    });

    it('renders column count separator when column_count > 0', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'table',
            geometry_type: null,
            feature_count: 29,
            column_count: 5,
            crs: null,
          })}
        />,
      );

      expect(screen.getByText(/5 cols/i)).toBeInTheDocument();
    });

    it('hides column count when column_count is null', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'table',
            geometry_type: null,
            feature_count: 29,
            column_count: null,
            crs: null,
          })}
        />,
      );

      expect(screen.queryByText(/cols/i)).not.toBeInTheDocument();
    });

    describe('unknown row count', () => {
      const renderTable = (feature_count: number | null, column_count: number | null) => {
        render(
          <SearchResultCard
            feature={makeFeature({
              record_type: 'table',
              geometry_type: null,
              description: undefined,
              feature_count,
              column_count,
              crs: null,
            })}
          />,
        );
        const thumb = screen.getByTestId('table-thumbnail-icon').parentElement as HTMLElement;
        return { thumb, text: thumb.textContent ?? '' };
      };

      it('null count with columns shows columns only', () => {
        const { thumb, text } = renderTable(null, 5);
        expect(text).toBe('5 cols');
        expect(thumb).toHaveAttribute('aria-label', 'Table with 5 columns');
        expect(screen.queryByText(/Table with 0 rows/)).not.toBeInTheDocument();
        expect(screen.getByText('Geospatial dataset')).toBeInTheDocument();
      });

      it('null count without columns shows no counts', () => {
        const { thumb, text } = renderTable(null, null);
        expect(text).toBe('');
        expect(thumb).toHaveAttribute('aria-label', 'Table');
        expect(screen.getByText('Geospatial dataset')).toBeInTheDocument();
      });

      it('a real zero count still reads 0 rows', () => {
        const { thumb, text } = renderTable(0, 5);
        expect(text).toBe('0 rows · 5 cols');
        expect(thumb).toHaveAttribute('aria-label', 'Table with 0 rows and 5 columns');
        expect(screen.getByText('Table with 0 rows')).toBeInTheDocument();
      });
    });

    it('does NOT render ImageOff for table records', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'table',
            geometry_type: null,
            feature_count: 29,
            crs: null,
          })}
        />,
      );

      // Table2 tile is rendered — ImageOff should not appear
      expect(screen.queryByRole('img', { name: /image.*off/i })).not.toBeInTheDocument();
    });
  });

  // Description tests
  describe('Description display', () => {
    it('renders real description when provided', () => {
      render(<SearchResultCard feature={makeFeature({ description: 'A real description' })} />);

      expect(screen.getByTestId('dataset-card-description')).toHaveTextContent('A real description');
    });

    it('falls back to the generated description when the description repeats the title', () => {
      render(<SearchResultCard feature={makeFeature({ title: 'World Countries', description: 'World Countries' })} />);

      expect(screen.getAllByText('World Countries')).toHaveLength(1);
      expect(screen.getByTestId('dataset-card-description')).not.toHaveTextContent('World Countries');
      expect(screen.getByTestId('dataset-card-description')).toHaveTextContent(/195/);
    });

    it('prints a collection title once when the description repeats it', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            record_type: 'collection',
            title: 'Parks',
            description: 'Parks',
            geometry_type: null,
          })}
        />,
      );

      expect(screen.getAllByText('Parks')).toHaveLength(1);
    });

    it('renders auto-description when description is null', () => {
      render(<SearchResultCard feature={makeFeature({ description: '' })} />);

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
            description: '',
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

    it('describes a 3D Tiles tileset without a description as a tileset', () => {
      render(
        <SearchResultCard
          feature={makeFeature({
            description: '',
            record_type: 'tiles3d_dataset',
            geometry_type: null,
            feature_count: null,
            crs: null,
          })}
        />,
      );

      expect(screen.getByTestId('dataset-card-description')).toHaveTextContent('3D Tiles tileset');
    });

    it('does not render description testid for collection records', () => {
      render(
        <SearchResultCard
          feature={makeFeature(
            {
              type: 'collection',
              title: 'My Collection',
              description: '',
              record_type: 'collection',
              dataset_count: 5,
              keywords: [],
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
              keywords: [],
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
              description: '',
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
              description: '',
              record_type: 'collection',
              dataset_count: 1,
              keywords: [],
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
              description: '',
              record_type: 'collection',
              record_status: 'draft',
              dataset_count: 1,
              keywords: [],
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

  describe('Compact density', () => {
    const compact = (feature: OGCRecordResponse) =>
      render(<SearchResultCard feature={feature} density="compact" />);

    it('shows type, title, spec, source and updated date on one row, without description or tags', () => {
      compact(makeFeature());

      const link = screen.getByTestId('search-result-card');
      expect(link).toHaveAttribute('data-density', 'compact');
      expect(link).toHaveAttribute('href', '/datasets/dataset-1');
      const title = within(link).getByRole('heading', { level: 3, name: 'World Countries' });
      expect(title).toHaveAttribute('title', 'World Countries');
      expect(screen.getByTestId('dataset-card-specs')).toHaveTextContent('195 features');
      expect(screen.getByTestId('dataset-card-specs')).toHaveTextContent('Polygon');
      expect(screen.getByTestId('dataset-card-source')).toHaveTextContent('Natural Earth');
      expect(screen.queryByTestId('dataset-card-description')).not.toBeInTheDocument();
      expect(screen.queryByText('boundaries')).not.toBeInTheDocument();
      expect(screen.queryByTestId('table-thumbnail-icon')).not.toBeInTheDocument();
    });

    it('names the link by its title first, then the type', () => {
      compact(makeFeature());

      expect(screen.getByRole('link', { name: /^World Countries.*Vector/ })).toBeInTheDocument();
    });

    it('shows a dash for a dataset with no update metadata and keeps the words for assistive tech', () => {
      compact(makeFeature({ never_edited: true, updated_by_display: null, created: null }));

      expect(screen.getByTestId('dataset-card-updated-visible')).toHaveTextContent('—');
      expect(screen.getByTestId('dataset-card-updated-attribution')).toHaveTextContent('No update metadata');
    });

    it.each([
      ['missing', 'Source missing'],
      ['inaccessible', 'Source inaccessible'],
    ] as const)('marks a source that is %s with an icon named for it', (state, label) => {
      compact(makeFeature({ source_health: state }));

      const chip = screen.getByTestId('source-health-chip');
      expect(chip).toHaveAttribute('data-state', state);
      expect(within(chip).getByText(label)).toHaveClass('sr-only');
      expect(chip).toHaveAttribute('title', expect.stringContaining(label));
      expect(screen.getByRole('link', { name: new RegExp(label) })).toBeInTheDocument();
    });

    it('marks an overdue refresh and leaves a healthy, fresh or due source unmarked', () => {
      const { unmount } = compact(makeFeature({ source_freshness: 'overdue', source_health: 'healthy' }));
      expect(screen.getByTestId('source-freshness-chip')).toHaveAttribute('data-state', 'overdue');
      expect(within(screen.getByTestId('source-freshness-chip')).getByText('Source refresh overdue')).toHaveClass('sr-only');
      expect(screen.queryByTestId('source-health-chip')).not.toBeInTheDocument();
      unmount();

      compact(makeFeature({ source_freshness: 'due', source_health: 'healthy' }));
      expect(screen.queryByTestId('source-freshness-chip')).not.toBeInTheDocument();
      expect(screen.queryByTestId('source-health-chip')).not.toBeInTheDocument();
    });

    it('shows the type as an icon-only badge named by the type', () => {
      compact(makeFeature({ record_type: 'raster_dataset', geometry_type: null }));

      const badge = screen.getByTitle('Raster');
      expect(badge).toHaveTextContent('Raster');
      expect(within(badge).getByText('Raster')).toHaveClass('sr-only');
      expect(badge.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    });

    it('shows the source inside the title cell only when there is one', () => {
      const { unmount } = render(<SearchResultCard feature={makeFeature()} density="compact" />);
      const title = screen.getByRole('heading', { level: 3, name: 'World Countries' });
      const source = screen.getByTestId('dataset-card-source');
      expect(title.parentElement).toContainElement(source);
      expect(source).toHaveAttribute('title', 'Natural Earth');
      unmount();

      compact(makeFeature({ source_organization: null }));
      expect(screen.queryByTestId('dataset-card-source')).not.toBeInTheDocument();
    });

    it('shows only the relative time, keeping the full sentence for assistive tech', () => {
      compact(makeFeature());

      const cell = screen.getByTestId('dataset-card-updated-attribution');
      const visible = within(cell).getByTestId('dataset-card-updated-visible');
      expect(visible).toHaveAttribute('aria-hidden', 'true');
      expect(visible.textContent).not.toMatch(/updated/i);
      expect(visible.textContent).not.toBe('');
      expect(cell.querySelector('.sr-only')?.textContent).toMatch(/^Updated /);
    });

    it('defaults to the comfortable layout', () => {
      render(<SearchResultCard feature={makeFeature()} />);

      expect(screen.getByTestId('search-result-card')).toHaveAttribute('data-density', 'comfortable');
      expect(screen.getByTestId('dataset-card-description')).toBeInTheDocument();
    });

    it('shows the status badge only when the record is not published', () => {
      const { unmount } = render(
        <SearchResultCard feature={makeFeature({ record_status: 'published' })} density="compact" />,
      );
      expect(screen.queryByText('Published')).not.toBeInTheDocument();
      expect(screen.queryByText('Draft')).not.toBeInTheDocument();
      unmount();

      compact(makeFeature({ record_status: 'draft' }));
      expect(screen.getByText('Draft')).toBeInTheDocument();
    });

    it('omits the source line when the dataset has no source organization', () => {
      compact(makeFeature({ source_organization: null }));

      expect(screen.queryByTestId('dataset-card-source')).not.toBeInTheDocument();
    });

    it('shows rows and columns for a table', () => {
      compact(makeFeature({ record_type: 'table', geometry_type: null, feature_count: 42, column_count: 6 }));

      expect(screen.getByTestId('dataset-card-specs')).toHaveTextContent('42 rows');
      expect(screen.getByTestId('dataset-card-specs')).toHaveTextContent('6 cols');
    });

    it.each([
      ['an unknown row count with columns', { feature_count: null, column_count: 6 }, '6 cols'],
      ['an unknown row count without columns', { feature_count: null, column_count: null }, ''],
      ['a real zero row count', { feature_count: 0, column_count: null }, '0 rows'],
    ])('reads %s correctly for a table', (_name, overrides, expected) => {
      compact(makeFeature({ record_type: 'table', geometry_type: null, ...overrides }));

      const spec = screen.getByTestId('dataset-card-specs');
      expect(spec.textContent).toBe(expected);
      expect(spec.textContent).not.toContain(expected === '6 cols' ? 'rows' : 'zzz');
    });

    it('shows raster bands in the spec', () => {
      compact(makeFeature({ record_type: 'raster_dataset', geometry_type: null, band_count: 3, feature_count: null }));

      expect(screen.getByTestId('dataset-card-specs')).toHaveTextContent('3 bands');
    });

    it('shows a collection as badge, title and dataset count', () => {
      compact(
        makeFeature(
          {
            type: 'collection',
            title: 'My Collection',
            record_type: 'collection',
            dataset_count: 7,
            description: 'A set of datasets',
            source_organization: 'Ignored',
            record_status: 'draft',
          },
          { id: 'coll-1', geometry: null },
        ),
      );

      const link = screen.getByTestId('search-result-card');
      expect(link).toHaveAttribute('href', '/collections/coll-1');
      expect(within(link).getByRole('heading', { name: 'My Collection' })).toBeInTheDocument();
      expect(within(link).getByText('7 datasets')).toBeInTheDocument();
      expect(screen.queryByText('A set of datasets')).not.toBeInTheDocument();
      expect(screen.queryByText('Draft')).not.toBeInTheDocument();
    });

    it('gives a collection no update time, since the search result carries only its creation time', () => {
      compact(
        makeFeature(
          { type: 'collection', title: 'My Collection', record_type: 'collection', dataset_count: 7 },
          { id: 'coll-1', geometry: null },
        ),
      );

      const cell = screen.getByTestId('dataset-card-updated-attribution');
      expect(screen.getByTestId('dataset-card-updated-visible')).toHaveTextContent('—');
      expect(cell).not.toHaveTextContent(/Updated/);
      expect(cell).not.toHaveAttribute('title');
    });

    it('prefetches the dataset on hover and does not fetch a quicklook', async () => {
      // Earlier cards in this file also call the hook, so only this row's calls count.
      vi.mocked(useQuicklook).mockClear();
      compact(makeFeature({ has_quicklook: true }));

      fireEvent.mouseEnter(screen.getByTestId('search-result-card'));

      await waitFor(() => expect(getDataset).toHaveBeenCalledWith('dataset-1'));
      const quicklookIds = vi.mocked(useQuicklook).mock.calls.map(([id]) => id);
      expect(quicklookIds.length).toBeGreaterThan(0);
      expect(quicklookIds.every((id) => id === null)).toBe(true);
    });
  });
});
