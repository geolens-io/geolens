import { render, screen, within } from '@/test/test-utils';
import { OverviewTab } from '../tabs/OverviewTab';
import type { DatasetResponse } from '@/types/api';
import { buildDatasetEditCapabilities } from '@/components/dataset/hooks/use-dataset-edit-capabilities';

const mockUseDataset = vi.fn((id: string): { data?: { title: string } } => ({ data: { title: `Title of ${id}` } }));
vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetVersions: () => ({ data: { versions: [] }, isLoading: false }),
  useDataset: (id: string) => mockUseDataset(id),
}));
vi.mock('@/components/dataset/hooks/use-records', () => ({
  useKeywords: () => ({ data: { keywords: [] }, isLoading: false }),
}));
vi.mock('@/components/import/hooks/use-vrt', () => ({
  useVrtGenerations: () => ({ data: { generations: [] } }),
}));
vi.mock('@/hooks/use-ai-availability', () => ({
  useAIAvailability: () => ({ isAIAvailable: false }),
}));
vi.mock('@/hooks/use-ai-metadata', () => ({
  useSummaryDraft: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('@/stores/auth-store', () => ({
  useAuthStore: () => false,
}));
vi.mock('@/components/dataset/RelatedDatasets', () => ({ RelatedDatasets: () => null }));
vi.mock('@/components/dataset/UsedInMaps', () => ({ UsedInMaps: () => null }));

const fullLicense = 'Creative Commons Attribution 4.0 International (CC BY 4.0) — attribution required for downstream reuse';
const fullSource = 'National Oceanic and Atmospheric Administration Office for Coastal Management';

function makeDataset(overrides: Partial<DatasetResponse> = {}): DatasetResponse {
  return {
    id: 'ds-1', record_id: 'rec-1', table_name: 'public_parks', has_generic_geometry: false, source_health: 'unknown', schema_drift_status: 'unknown', source_freshness: 'unknown', title: 'Parks', summary: null,
    srid: 4326, geometry_type: 'Polygon', feature_count: 100, extent_bbox: null, column_info: null,
    license: fullLicense, attribution: null, source_organization: fullSource,
    data_vintage_start: null, data_vintage_end: null, source_format: 'geojson', source_filename: null,
    original_srid: null, visibility: 'public', created_by: null, created_by_display: 'admin',
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    last_edited_by_display: null, last_edited_at: null, record_status: 'published', lineage_summary: null,
    update_frequency: null, usage_constraints: null, access_constraints: null, sensitivity_classification: null,
    theme_category: null, owner_org: null, published_at: null, updated_by: null, current_version: 1,
    source_url: null, quality_statement: null, collections: null, record_type: 'vector_dataset', raster: null,
    tile_columns: null,
    ...overrides,
  };
}

function renderOverview(dataset: DatasetResponse) {
  return render(
    <OverviewTab
      dataset={dataset}
      canEdit={false}
      capabilities={buildDatasetEditCapabilities({ isEditor: false })}
      summaryValue=""
      onSummaryDraftSave={vi.fn()}
      onSummaryDirtyChange={vi.fn()}
    />,
  );
}

describe('OverviewTab reuse details', () => {
  it('shows the translated update cadence in the overview', () => {
    renderOverview(makeDataset({ update_frequency: 'asNeeded' }));
    expect(screen.getByText('As needed')).toBeInTheDocument();
    expect(screen.queryByText('asNeeded')).not.toBeInTheDocument();
  });

  it('shows full source and license values without truncation or hover-only titles', () => {
    renderOverview(makeDataset());

    for (const value of [fullLicense, fullSource]) {
      const detail = screen.getByText(value);
      expect(detail).not.toHaveClass('truncate');
      expect(detail).not.toHaveAttribute('title');
      expect(detail).toHaveClass('break-words');
    }
  });

  it('shows a tileset card for a 3D Tiles dataset and none for a vector one', () => {
    const tileset: DatasetResponse = {
      ...makeDataset(),
      record_type: 'tiles3d_dataset',
      tileset: {
        url: '/api/datasets/ds-1/tiles3d/tileset.json',
        size_bytes: 1024,
        version: '1.0',
        geometric_error: 70,
        bounding_volume: 'box',
      },
    };
    const props = {
      canEdit: false,
      capabilities: buildDatasetEditCapabilities({ isEditor: false }),
      summaryValue: '',
      onSummaryDraftSave: vi.fn(),
      onSummaryDirtyChange: vi.fn(),
    };
    const { unmount } = render(<OverviewTab dataset={tileset} {...props} />);

    expect(screen.getByRole('heading', { name: '3D Tiles tileset' })).toBeInTheDocument();
    expect(screen.getByText('Box')).toBeInTheDocument();
    unmount();

    render(<OverviewTab dataset={makeDataset()} {...props} />);
    expect(screen.queryByRole('heading', { name: '3D Tiles tileset' })).not.toBeInTheDocument();
  });
});

describe('OverviewTab Table Name row', () => {
  it('shows the row for a vector dataset', () => {
    renderOverview(makeDataset({ record_type: 'vector_dataset', table_name: 'public_parks' }));

    expect(screen.getByText('public_parks')).toBeInTheDocument();
  });

  it('shows the row for a tabular dataset', () => {
    renderOverview(makeDataset({ record_type: 'table', table_name: 'census_2026' }));

    expect(screen.getByText('census_2026')).toBeInTheDocument();
  });

  it('hides the row for a raster dataset, which has no feature table behind its synthetic name', () => {
    renderOverview(makeDataset({ record_type: 'raster_dataset', table_name: 'raster_a1b2c3' }));

    expect(screen.queryByText('raster_a1b2c3')).not.toBeInTheDocument();
  });

  it('hides the row for a VRT dataset', () => {
    renderOverview(makeDataset({ record_type: 'vrt_dataset', table_name: 'raster_d4e5f6' }));

    expect(screen.queryByText('raster_d4e5f6')).not.toBeInTheDocument();
  });

  it.each([
    [5, true],
    [1, true],
    [0, false],
    [null, false],
  ])('VRT source_count %s shows the Sources row: %s', (count, shown) => {
    renderOverview(
      makeDataset({
        record_type: 'vrt_dataset',
        raster: { vrt_type: 'mosaic', source_count: count } as DatasetResponse['raster'],
      }),
    );

    expect(screen.queryByText('Sources') !== null).toBe(shown);
    if (shown) expect(screen.getByText(String(count))).toBeInTheDocument();
  });

  it('shows N/A for a mosaic whose size is withheld', () => {
    renderOverview(
      makeDataset({
        record_type: 'vrt_dataset',
        raster: { vrt_type: 'mosaic', width: null, height: null } as DatasetResponse['raster'],
      }),
    );

    expect(screen.queryByText(/ x .* px$/)).not.toBeInTheDocument();
    expect(screen.getByText('Dimensions').nextElementSibling).toHaveTextContent('N/A');
  });

  it('shows the size of a mosaic the reader can see in full', () => {
    renderOverview(
      makeDataset({
        record_type: 'vrt_dataset',
        raster: { vrt_type: 'mosaic', width: 1100, height: 100 } as DatasetResponse['raster'],
      }),
    );

    expect(screen.getByText('1100 x 100 px')).toBeInTheDocument();
  });

  it('hides the row for a 3D Tiles dataset', () => {
    renderOverview(makeDataset({ record_type: 'tiles3d_dataset', table_name: 'tiles3d_a1b2c3' }));

    expect(screen.queryByText('tiles3d_a1b2c3')).not.toBeInTheDocument();
  });
});

describe('OverviewTab derived-from row', () => {
  const derived = (operation: string, params: Record<string, unknown> = {}) =>
    makeDataset({
      derived_from: { dataset_id: 'src-1', operation, params, created_at: '2026-01-01T00:00:00Z' },
    } as Partial<DatasetResponse>);

  it('links the source title and names the operation', () => {
    renderOverview(derived('buffer', { distance: 5 }));
    const row = screen.getByTestId('dataset-derived-from');
    expect(screen.getByText('Derived from')).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: 'Title of src-1' })).toHaveAttribute('href', '/datasets/src-1');
    expect(row).toHaveTextContent('Buffer');
    // The organization row keeps its own label.
    expect(screen.getByText('Source')).toBeInTheDocument();
  });

  it('links a second input beside the operation', () => {
    renderOverview(derived('spatial_join', { join_dataset_id: 'join-1' }));
    const row = screen.getByTestId('dataset-derived-from');
    expect(row).toHaveTextContent('Spatial join with Title of join-1');
    expect(within(row).getByRole('link', { name: 'Title of join-1' })).toHaveAttribute('href', '/datasets/join-1');
    expect(within(row).getAllByRole('link')).toHaveLength(2);
  });

  it('reads a clip mask as the second input and falls back for an unknown operation', () => {
    renderOverview(derived('warp_drive', { mask_dataset_id: 'mask-1' }));
    const row = screen.getByTestId('dataset-derived-from');
    expect(row).toHaveTextContent('Analysis with Title of mask-1');
  });

  it('shows a neutral name, never an id, while a title is unavailable', () => {
    mockUseDataset.mockImplementation(() => ({}));
    renderOverview(derived('buffer'));
    const row = screen.getByTestId('dataset-derived-from');
    expect(row).toHaveTextContent('another dataset');
    expect(row).not.toHaveTextContent('src-1');
    expect(within(row).queryByRole('link')).not.toBeInTheDocument();
    mockUseDataset.mockImplementation((id: string) => ({ data: { title: `Title of ${id}` } }));
  });

  it('adds no row for a dataset that was not derived', () => {
    renderOverview(makeDataset({ derived_from: null } as Partial<DatasetResponse>));
    expect(screen.queryByTestId('dataset-derived-from')).not.toBeInTheDocument();
  });
});
