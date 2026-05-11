import { screen } from '@testing-library/react';
import { render } from '@/test/test-utils';
import { useVrtSources, useAddVrtSource, useRemoveVrtSource, useVrtStatus, useVrtGenerations, useRegenerateVrt } from '@/components/import/hooks/use-vrt';
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
});
