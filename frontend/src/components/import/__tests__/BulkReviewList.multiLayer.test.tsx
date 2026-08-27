/**
 * GPKG-03 Phase 1058 — BulkReviewList multi-layer "Ingest all layers" button tests.
 *
 * Tests:
 * (a) Renders button when entry has > 1 layer and onIngestAllLayers is provided.
 * (b) Does NOT render button for single-layer entries.
 * (c) Does NOT render button when onIngestAllLayers prop is omitted.
 * (d) Calls onIngestAllLayers with entry.id on click.
 */
import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { BulkReviewList } from '../BulkReviewList';
import type { FileEntry, CommitImportRequest } from '@/types/api';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (key === 'bulk.ingestAllLayers' && opts?.count != null) {
        return `Ingest all ${opts.count} layers as separate datasets`;
      }
      if (key === 'bulk.layerCount' && opts?.value != null) {
        return `${opts.value} layers`;
      }
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

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

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

function makeSingleLayerEntry(): FileEntry {
  return {
    ...makeMultiLayerEntry(),
    id: 'entry-single',
    previewData: {
      job_id: 'job-1',
      source_filename: 'test.gpkg',
      columns: [],
      geometry_type: 'Point',
      crs: 4326,
      layer_name: 'only',
      layers: [{ name: 'only', feature_count: 5, field_count: 2 }],
      sample_rows: [],
      feature_count: 5,
      detected_geometry_columns: null,
    },
  };
}

const noopCommitSingle = (_entryId: string, _request: CommitImportRequest) => {};
const noopCommitAll = () => {};
const noopRemove = (_entryId: string) => {};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('BulkReviewList — multi-layer "Ingest all layers" button (GPKG-03)', () => {
  it('(a) renders Ingest all layers button when entry has > 1 layer and onIngestAllLayers is provided', () => {
    const entry = makeMultiLayerEntry();
    const onIngestAllLayers = vi.fn();

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
        onIngestAllLayers={onIngestAllLayers}
      />,
    );

    // Entry is auto-expanded (first entry)
    const btn = screen.getByTestId('ingest-all-layers-entry-1');
    expect(btn).toBeInTheDocument();
    expect(btn.textContent).toMatch(/Ingest all 2 layers/);
  });

  it('(b) does NOT render the button for single-layer entries (layers.length === 1)', () => {
    const entry = makeSingleLayerEntry();
    const onIngestAllLayers = vi.fn();

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
        onIngestAllLayers={onIngestAllLayers}
      />,
    );

    expect(screen.queryByTestId(/ingest-all-layers-/)).not.toBeInTheDocument();
  });

  it('(c) does NOT render the button when onIngestAllLayers prop is omitted', () => {
    const entry = makeMultiLayerEntry();

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
        // onIngestAllLayers intentionally omitted
      />,
    );

    expect(screen.queryByTestId(/ingest-all-layers-/)).not.toBeInTheDocument();
  });

  it('(d) calls onIngestAllLayers with entry.id on click', async () => {
    const user = userEvent.setup();
    const entry = makeMultiLayerEntry();
    const onIngestAllLayers = vi.fn();

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
        onIngestAllLayers={onIngestAllLayers}
      />,
    );

    const btn = screen.getByTestId('ingest-all-layers-entry-1');
    await user.click(btn);

    expect(onIngestAllLayers).toHaveBeenCalledOnce();
    expect(onIngestAllLayers).toHaveBeenCalledWith('entry-1');
  });
});

// ---------------------------------------------------------------------------
// import-multilayer-ux: "Layer" vs "Sheet" vocabulary + layer-count badge
// ---------------------------------------------------------------------------

describe('BulkReviewList — layer label uses container-appropriate vocabulary', () => {
  it('labels the picker "bulk.layerLabel" for a multi-layer GeoPackage', () => {
    const entry = makeMultiLayerEntry(); // fileName: 'test.gpkg'

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    expect(screen.getByText('bulk.layerLabel')).toBeInTheDocument();
    expect(screen.queryByText('bulk.sheetLabel')).not.toBeInTheDocument();
  });

  it('labels the picker "bulk.layerLabel" for a multi-layer zipped FileGDB', () => {
    const entry = makeMultiLayerEntry({ fileName: 'parcels.gdb.zip' });

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    expect(screen.getByText('bulk.layerLabel')).toBeInTheDocument();
    expect(screen.queryByText('bulk.sheetLabel')).not.toBeInTheDocument();
  });

  it('keeps the picker labeled "bulk.sheetLabel" for a multi-sheet spreadsheet', () => {
    const entry = makeMultiLayerEntry({ fileName: 'budget.xlsx' });

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    expect(screen.getByText('bulk.sheetLabel')).toBeInTheDocument();
    expect(screen.queryByText('bulk.layerLabel')).not.toBeInTheDocument();
  });
});

describe('BulkReviewList — layer-count badge on the collapsed card', () => {
  it('shows a layer-count badge when the preview has more than one layer', () => {
    const entry = makeMultiLayerEntry();

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    const badge = screen.getByTestId('layer-count-badge-entry-1');
    expect(badge).toBeInTheDocument();
    expect(badge.textContent).toMatch(/2 layers/);
  });

  it('does NOT show a layer-count badge for single-layer entries', () => {
    const entry = makeSingleLayerEntry();

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    expect(screen.queryByTestId(/layer-count-badge-/)).not.toBeInTheDocument();
  });
});

describe('BulkReviewList — default-import hint acknowledges multi-layer files', () => {
  it('shows the multi-layer hint when a staged file has more than one layer', () => {
    const entry = makeMultiLayerEntry();

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    expect(screen.getByText('review.actionHintMultiLayer')).toBeInTheDocument();
    expect(screen.queryByText('review.actionHint')).not.toBeInTheDocument();
  });

  it('shows the plain hint when no staged file has more than one layer', () => {
    const entry = makeSingleLayerEntry();

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    expect(screen.getByText('review.actionHint')).toBeInTheDocument();
    expect(screen.queryByText('review.actionHintMultiLayer')).not.toBeInTheDocument();
  });
});
