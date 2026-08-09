import { render, screen } from '@/test/test-utils';
import { buildDatasetEditCapabilities } from '@/components/dataset/hooks/use-dataset-edit-capabilities';
import { DetailPanel } from '../panels/DetailPanel';
import type { DatasetResponse, RecordType } from '@/types/api';

vi.mock('@/components/dataset/tabs/OverviewTab', () => ({ OverviewTab: () => null }));
vi.mock('@/components/dataset/tabs/MetadataTab', () => ({ MetadataTab: () => null }));
vi.mock('@/components/dataset/tabs/DataTab', () => ({ DataTab: () => null }));
vi.mock('@/components/dataset/tabs/StructureTab', () => ({ StructureTab: () => null }));
vi.mock('@/components/dataset/tabs/AccessTab', () => ({ AccessTab: () => null }));
vi.mock('@/components/dataset/SourcePanel', () => ({
  SourcePanel: ({ dataset, actions }: { dataset: DatasetResponse; actions?: React.ReactNode }) => (
    <div data-testid="source-panel" data-dataset-type={dataset.record_type} data-has-actions={Boolean(actions)} />
  ),
}));

function makeDataset(recordType: RecordType): DatasetResponse {
  return {
    id: `dataset-${recordType}`,
    record_id: 'record-1',
    table_name: 'ds_source',
    title: 'Source dataset',
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
    tile_columns: null,
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
    record_type: recordType,
    raster: null,
  };
}

// feat(#1285): DetailPanel now wires the "Refresh from source" action into
// SourcePanel's `actions` slot, gated on canEdit AND REFRESHABLE_ORIGINS
// (fix, codex round 1: origin presence alone was too broad — an upload,
// created, or STAC origin resolves just fine but the refresh door refuses
// all three). These synthetic datasets all set source_format: null, which
// datasetOrigin() reads as a registered-table (postgis) origin — allowlisted
// — for every record type except vrt_dataset, which has no origin at all.
it.each<[RecordType, boolean]>([
  ['vector_dataset', true],
  ['table', true],
  ['raster_dataset', true],
  ['vrt_dataset', false],
])(
  'mounts the read-only Source panel for %s detail pages (has-actions: %s)',
  (recordType, expectsActions) => {
    render(
      <DetailPanel
        dataset={makeDataset(recordType)}
        canEdit
        capabilities={buildDatasetEditCapabilities({ isEditor: true })}
        activeTab="sources"
        onTabChange={vi.fn()}
        resolveDraftValue={() => ''}
        stagePendingDraft={vi.fn()}
        handleDraftDirtyChange={vi.fn()}
        onNavigateToValidationField={vi.fn()}
      />,
    );

    expect(screen.getByRole('tab', { name: 'Source' })).toBeInTheDocument();
    expect(screen.getByTestId('source-panel')).toHaveAttribute('data-dataset-type', recordType);
    expect(screen.getByTestId('source-panel')).toHaveAttribute(
      'data-has-actions',
      String(expectsActions),
    );
  },
);

it.each<[string, string]>([
  ['geojson', 'upload'],
  ['created', 'created'],
  ['stac', 'stac'],
])(
  'withholds the refresh action for a %s-sourced (%s-origin) dataset the refresh door cannot serve yet',
  (sourceFormat) => {
    render(
      <DetailPanel
        dataset={{ ...makeDataset('vector_dataset'), source_format: sourceFormat }}
        canEdit
        capabilities={buildDatasetEditCapabilities({ isEditor: true })}
        activeTab="sources"
        onTabChange={vi.fn()}
        resolveDraftValue={() => ''}
        stagePendingDraft={vi.fn()}
        handleDraftDirtyChange={vi.fn()}
        onNavigateToValidationField={vi.fn()}
      />,
    );

    expect(screen.getByTestId('source-panel')).toHaveAttribute('data-has-actions', 'false');
  },
);

it('withholds the refresh action from a reader who cannot edit, even with a resolvable origin', () => {
  render(
    <DetailPanel
      dataset={makeDataset('vector_dataset')}
      canEdit={false}
      capabilities={buildDatasetEditCapabilities({ isEditor: false })}
      activeTab="sources"
      onTabChange={vi.fn()}
      resolveDraftValue={() => ''}
      stagePendingDraft={vi.fn()}
      handleDraftDirtyChange={vi.fn()}
      onNavigateToValidationField={vi.fn()}
    />,
  );

  expect(screen.getByTestId('source-panel')).toHaveAttribute('data-has-actions', 'false');
});
