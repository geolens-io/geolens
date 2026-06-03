import { screen, fireEvent } from '@testing-library/react';
import { render } from '@/test/test-utils';
import { useVrtSources, useAddVrtSource, useRemoveVrtSource, useVrtStatus, useVrtGenerations, useRegenerateVrt } from '@/components/import/hooks/use-vrt';
import { searchDatasets } from '@/api/search';
import { SourcesTab } from '../tabs/SourcesTab';
import type { DatasetResponse } from '@/types/api';

vi.mock('@/components/import/hooks/use-vrt', () => ({
  useVrtSources: vi.fn(),
  useAddVrtSource: vi.fn(),
  useRemoveVrtSource: vi.fn(),
  useVrtStatus: vi.fn(),
  useVrtGenerations: vi.fn(),
  useRegenerateVrt: vi.fn(),
}));

vi.mock('@/api/search', () => ({
  searchDatasets: vi.fn(),
}));

const mockDataset: DatasetResponse = {
  id: 'vrt-1',
  record_id: 'rec-1',
  table_name: 'vrt_table',
  title: 'My VRT',
  summary: null,
  srid: null,
  geometry_type: null,
  feature_count: null,
  extent_bbox: null,
  column_info: null,
  license: null,
  source_organization: null,
  data_vintage_start: null,
  data_vintage_end: null,
  source_format: null,
  source_filename: null,
  original_srid: null,
  visibility: 'private',
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
  tile_columns: null,
  record_type: 'vrt_dataset',
  raster: {
    epsg: 4326,
    res_x: 0.001,
    res_y: 0.001,
    band_count: 3,
    nodata: null,
    compression: 'deflate',
    width: 1000,
    height: 1000,
    size_bytes: null,
    tile_url: null,
    bands: [],
    connect: null,
    status: 'ready',
    vrt_type: 'mosaic',
    source_count: 2,
    resolution_strategy: 'finest',
  },
};

const mockSources = [
  {
    dataset_id: 'src-1',
    title: 'Source COG A',
    position: 0,
    band_count: 3,
    resolution_x: 0.001,
    resolution_y: 0.001,
    crs_epsg: 4326,
    extent_bbox: null,
  },
  {
    dataset_id: 'src-2',
    title: 'Source COG B',
    position: 1,
    band_count: 3,
    resolution_x: 0.001,
    resolution_y: 0.001,
    crs_epsg: 4326,
    extent_bbox: null,
  },
];

const mockAddMutation = { mutateAsync: vi.fn(), isPending: false };
const mockRemoveMutation = { mutateAsync: vi.fn(), isPending: false };
const mockRegenerateMutation = { mutateAsync: vi.fn(), isPending: false };

beforeEach(() => {
  vi.mocked(useVrtSources).mockReturnValue({
    data: { sources: mockSources },
    isLoading: false,
  } as ReturnType<typeof useVrtSources>);
  vi.mocked(useAddVrtSource).mockReturnValue(
    mockAddMutation as unknown as ReturnType<typeof useAddVrtSource>,
  );
  vi.mocked(useRemoveVrtSource).mockReturnValue(
    mockRemoveMutation as unknown as ReturnType<typeof useRemoveVrtSource>,
  );
  vi.mocked(useVrtStatus).mockReturnValue({
    data: { status: 'ready', last_generation_at: null, source_count: 2, active_generation: null, source_health: [] },
    isLoading: false,
  } as unknown as ReturnType<typeof useVrtStatus>);
  vi.mocked(useVrtGenerations).mockReturnValue({
    data: { generations: [], total: 0 },
    isLoading: false,
  } as unknown as ReturnType<typeof useVrtGenerations>);
  vi.mocked(useRegenerateVrt).mockReturnValue(
    mockRegenerateMutation as unknown as ReturnType<typeof useRegenerateVrt>,
  );
});

describe('SourcesTab', () => {
  // 8 deferred test cases migrated 2026-05-07 (Phase 278, TEST-07) to:
  //   .planning/backlog/SourcesTab-test-todos.md
  // Pick up there before adding new placeholder entries here — keep this file
  // honest about what's tested.

  it('uses centralized semantic colors for VRT generation badges (A11Y-04)', () => {
    vi.mocked(useVrtGenerations).mockReturnValue({
      data: {
        generations: [
          { id: 'g1', status: 'completed', started_at: '2026-01-01T00:00:00Z', duration_seconds: 1.5, source_count: 2, triggered_by: 'system', error_message: null },
          { id: 'g2', status: 'failed', started_at: '2026-01-02T00:00:00Z', duration_seconds: 0.5, source_count: 2, triggered_by: 'user', error_message: 'bad' },
        ],
        total: 2,
      },
      isLoading: false,
    } as ReturnType<typeof useVrtGenerations>);

    render(
      <SourcesTab dataset={mockDataset} canEdit={false} datasetId="vrt-1" />,
    );

    // Find badge elements by their text
    const completedBadge = screen.getByText('completed');
    const failedBadge = screen.getByText('failed');

    // Should NOT have hardcoded colors
    expect(completedBadge.className).not.toContain('bg-green-600');
    expect(failedBadge.className).not.toContain('bg-yellow-500');

    // Should use centralized semantic colors (emerald for success, rose for destructive)
    expect(completedBadge.className).toContain('border-emerald');
    expect(failedBadge.className).toContain('border-rose');
  });

  it('renders source rows', () => {
    render(
      <SourcesTab dataset={mockDataset} canEdit={false} datasetId="vrt-1" />,
    );
    expect(screen.getByText('Source COG A')).toBeInTheDocument();
    expect(screen.getByText('Source COG B')).toBeInTheDocument();
  });

  // Backlog items from .planning/backlog/SourcesTab-test-todos.md (Phase 1048, FOLLOWUP-03)

  it('renders source table with rows in position order', () => {
    // Supply sources in reverse position order — component should preserve API arrival order
    // (no client-side sort by position). Sorting, if any, must happen server-side.
    const outOfOrderSources = [
      { dataset_id: 'src-2', title: 'Source COG B', position: 1, band_count: 3, resolution_x: 0.001, resolution_y: 0.001, crs_epsg: 4326, extent_bbox: null },
      { dataset_id: 'src-1', title: 'Source COG A', position: 0, band_count: 3, resolution_x: 0.001, resolution_y: 0.001, crs_epsg: 4326, extent_bbox: null },
    ];
    vi.mocked(useVrtSources).mockReturnValue({
      data: { sources: outOfOrderSources },
      isLoading: false,
    } as ReturnType<typeof useVrtSources>);

    render(<SourcesTab dataset={mockDataset} canEdit={false} datasetId="vrt-1" />);

    const rows = screen.getAllByRole('row');
    // rows[0] is the header; rows[1] and rows[2] are data rows
    expect(rows[1]).toHaveTextContent('Source COG B');
    expect(rows[2]).toHaveTextContent('Source COG A');
    // Position column displays 1-indexed values: B has position 1 → displays "2", A has position 0 → displays "1"
    expect(rows[1]).toHaveTextContent('2');
    expect(rows[2]).toHaveTextContent('1');
  });

  it('source title is a clickable link to /datasets/{dataset_id}', () => {
    render(<SourcesTab dataset={mockDataset} canEdit={false} datasetId="vrt-1" />);

    const linkA = screen.getByRole('link', { name: 'Source COG A' });
    expect(linkA).toBeInTheDocument();
    expect(linkA).toHaveAttribute('href', '/datasets/src-1');

    const linkB = screen.getByRole('link', { name: 'Source COG B' });
    expect(linkB).toHaveAttribute('href', '/datasets/src-2');
  });

  it('shows regenerating banner when dataset.raster.status === "regenerating"', () => {
    const regeneratingDataset: DatasetResponse = {
      ...mockDataset,
      raster: { ...mockDataset.raster!, status: 'regenerating' },
    };

    render(<SourcesTab dataset={regeneratingDataset} canEdit={false} datasetId="vrt-1" />);

    expect(
      screen.getByText('VRT is regenerating. Source changes are disabled until complete.'),
    ).toBeInTheDocument();
  });

  it('shows failed banner when dataset.raster.status === "failed"', () => {
    const failedDataset: DatasetResponse = {
      ...mockDataset,
      raster: { ...mockDataset.raster!, status: 'failed' },
    };

    render(<SourcesTab dataset={failedDataset} canEdit={false} datasetId="vrt-1" />);

    expect(
      screen.getByText('VRT regeneration failed. Remove the problem source and try again.'),
    ).toBeInTheDocument();
  });

  it('disables the Add Source button when status is "regenerating"', () => {
    const regeneratingDataset: DatasetResponse = {
      ...mockDataset,
      raster: { ...mockDataset.raster!, status: 'regenerating' },
    };

    render(<SourcesTab dataset={regeneratingDataset} canEdit={true} datasetId="vrt-1" />);

    const addBtn = screen.getByRole('button', { name: /Add Source/i });
    expect(addBtn).toBeDisabled();
  });

  it('disables remove buttons when status is "regenerating"', () => {
    const regeneratingDataset: DatasetResponse = {
      ...mockDataset,
      raster: { ...mockDataset.raster!, status: 'regenerating' },
    };
    // 3 sources so min-sources guard doesn't also disable
    const threeSources = [
      ...mockSources,
      { dataset_id: 'src-3', title: 'Source COG C', position: 2, band_count: 3, resolution_x: 0.001, resolution_y: 0.001, crs_epsg: 4326, extent_bbox: null },
    ];
    vi.mocked(useVrtSources).mockReturnValue({
      data: { sources: threeSources },
      isLoading: false,
    } as ReturnType<typeof useVrtSources>);

    render(<SourcesTab dataset={regeneratingDataset} canEdit={true} datasetId="vrt-1" />);

    const removeBtns = screen.getAllByRole('button', { name: /Remove source/i });
    removeBtns.forEach((btn) => expect(btn).toBeDisabled());
  });

  it('remove button triggers the confirm dialog', () => {
    // 3 sources so remove is not disabled due to min-sources floor
    const threeSources = [
      ...mockSources,
      { dataset_id: 'src-3', title: 'Source COG C', position: 2, band_count: 3, resolution_x: 0.001, resolution_y: 0.001, crs_epsg: 4326, extent_bbox: null },
    ];
    vi.mocked(useVrtSources).mockReturnValue({
      data: { sources: threeSources },
      isLoading: false,
    } as ReturnType<typeof useVrtSources>);

    render(<SourcesTab dataset={mockDataset} canEdit={true} datasetId="vrt-1" />);

    // Click the first active remove button (for src-1)
    const removeBtns = screen.getAllByRole('button', { name: /Remove source/i });
    fireEvent.click(removeBtns[0]);

    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toBeInTheDocument();
    // Dialog title should say "Remove Source"
    expect(screen.getAllByText('Remove Source').length).toBeGreaterThan(0);
  });

  it('disables remove buttons when only 2 sources remain (minimum floor)', () => {
    // Default mock already has exactly 2 sources
    render(<SourcesTab dataset={mockDataset} canEdit={true} datasetId="vrt-1" />);

    const removeBtns = screen.getAllByRole('button', { name: /Remove source/i });
    removeBtns.forEach((btn) => expect(btn).toBeDisabled());
  });

  it('add source picker filters out already-linked sources from search results', async () => {
    vi.mocked(searchDatasets).mockResolvedValue({
      type: 'FeatureCollection',
      numberMatched: 2,
      numberReturned: 2,
      features: [
        // src-1 is already linked — should be filtered out
        {
          type: 'Feature',
          id: 'src-1',
          geometry: null,
          properties: { type: 'raster_dataset', title: 'Source COG A', description: null, keywords: null, created: null, updated: null, updated_by_display: null, never_edited: false, crs: 'EPSG:4326', geometry_type: null, feature_count: null, license: null, source_organization: null, band_count: 3 },
          links: [],
        },
        // src-99 is NOT linked — should appear
        {
          type: 'Feature',
          id: 'src-99',
          geometry: null,
          properties: { type: 'raster_dataset', title: 'New COG Dataset', description: null, keywords: null, created: null, updated: null, updated_by_display: null, never_edited: false, crs: 'EPSG:4326', geometry_type: null, feature_count: null, license: null, source_organization: null, band_count: 1 },
          links: [],
        },
      ],
    });

    render(<SourcesTab dataset={mockDataset} canEdit={true} datasetId="vrt-1" />);

    // Open the picker
    fireEvent.click(screen.getByRole('button', { name: /Add Source/i }));

    // Type a query of ≥ 2 characters to trigger search
    const searchInput = screen.getByPlaceholderText('Search for a COG dataset...');
    fireEvent.change(searchInput, { target: { value: 'cog' } });

    // Wait for the unlinked result to appear in the picker.
    // Explicit 3 s timeout: the component has a 300 ms debounce before
    // firing the query, and the default 1000 ms window is too tight on slow CI.
    const newResult = await screen.findByText('New COG Dataset', {}, { timeout: 3000 });
    expect(newResult).toBeInTheDocument();

    // The picker should NOT offer src-1 (already linked) as a button to click
    // "Source COG A" appears in the table but NOT as a picker result button
    const pickerButtons = screen.queryAllByRole('button', { name: /Source COG A/i });
    // The only buttons with that text would be picker items — there should be none
    expect(pickerButtons).toHaveLength(0);
  });
});
