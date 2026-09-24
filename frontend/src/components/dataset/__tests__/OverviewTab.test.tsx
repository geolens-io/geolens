import { render, screen } from '@/test/test-utils';
import { OverviewTab } from '../tabs/OverviewTab';
import type { DatasetResponse } from '@/types/api';
import { buildDatasetEditCapabilities } from '@/components/dataset/hooks/use-dataset-edit-capabilities';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetVersions: () => ({ data: { versions: [] }, isLoading: false }),
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

function makeDataset(): DatasetResponse {
  return {
    id: 'ds-1', record_id: 'rec-1', table_name: 'public_parks', title: 'Parks', summary: null,
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
  };
}

describe('OverviewTab reuse details', () => {
  it('shows full source and license values without truncation or hover-only titles', () => {
    render(
      <OverviewTab
        dataset={makeDataset()}
        canEdit={false}
        capabilities={buildDatasetEditCapabilities({ isEditor: false })}
        summaryValue=""
        onSummaryDraftSave={vi.fn()}
        onSummaryDirtyChange={vi.fn()}
      />,
    );

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
