/**
 * fix(#1778): "no layer change mid-commit" guard, bulk path.
 *
 * The #1708 r24 guard (UrlImportForm.tsx's handleLayerChange) was never
 * applied to BulkReviewList's layer/sheet picker, so it stayed enabled while
 * a commit was in flight -- changing it drove the entry back to 'preview',
 * re-enabling the commit button against a request that was already running.
 *
 * This test pins the UI half of the fix: the layer/sheet <Select> is
 * disabled once the entry's status is 'committing'.
 */
import { render, screen } from '@/test/test-utils';
import { BulkReviewList } from '../BulkReviewList';
import type { FileEntry, CommitImportRequest } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts?.defaultValue === 'string') return opts.defaultValue;
      return key;
    },
  }),
}));

vi.mock('@/i18n/labels', () => ({
  getGeometryTypeLabel: (_t: unknown, type: string) => type,
}));

vi.mock('@/lib/format', () => ({
  formatNumber: (n: number) => String(n),
}));

vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: () => <div data-testid="import-metadata-form" />,
}));

vi.mock('../TypeTag', () => ({
  TypeTag: () => <div data-testid="type-tag" />,
}));

vi.mock('../StatusPill', () => ({
  StatusPill: () => <div data-testid="status-pill" />,
}));

function makeMultiLayerEntry(overrides: Partial<FileEntry> = {}): FileEntry {
  return {
    id: 'entry-1',
    file: null,
    fileName: 'test.gpkg',
    status: 'preview',
    jobId: 'job-1',
    previewData: {
      job_id: 'job-1',
      source_filename: 'test.gpkg',
      columns: [],
      geometry_type: 'Point',
      crs: 4326,
      layer_name: 'layer_a',
      layers: [
        { name: 'layer_a', feature_count: 10, field_count: 3 },
        { name: 'layer_b', feature_count: 20, field_count: 5 },
      ],
      sample_rows: [],
      feature_count: 10,
      detected_geometry_columns: null,
    },
    error: null,
    submittedTitle: null,
    submittedVisibility: null,
    submittedKind: null,
    ...overrides,
  };
}

const noopCommitSingle = (_entryId: string, _request: CommitImportRequest) => {};
const noopCommitAll = () => {};
const noopRemove = (_entryId: string) => {};

describe('BulkReviewList — layer picker disabled mid-commit', () => {
  it('leaves the layer/sheet Select enabled while the entry is in "preview"', () => {
    const entry = makeMultiLayerEntry({ status: 'preview' });

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
        onSheetChange={vi.fn()}
      />,
    );

    const trigger = screen.getByLabelText('bulk.layerLabel');
    expect(trigger).not.toBeDisabled();
  });

  it('disables the layer/sheet Select while the entry is "committing"', () => {
    const entry = makeMultiLayerEntry({ status: 'committing' });

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={true}
        onSheetChange={vi.fn()}
      />,
    );

    const trigger = screen.getByLabelText('bulk.layerLabel');
    expect(trigger).toBeDisabled();
  });
});
