/**
 * "Report this problem" CTA on failed staged files.
 *
 * The import UI showed a failure state with no path to the in-app problem
 * reporter, so a stuck uploader had no nudge toward filing a report. Tests:
 * (a) renders on the sole/first entry's upload-failed error (regression for
 *     the isExpanded/canExpand bug that hid the error entirely — see below)
 * (b) renders on a non-first upload-failed entry too
 * (c) renders inside the expanded panel for a commit-failed entry
 * (d) does NOT render for a healthy 'preview' entry
 * (e) clicking it opens the report wizard via useReportDialog().openReport
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
      if (key === 'upload.reportProblem') return 'Report this problem';
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
  kindFromExtension: () => 'table',
}));

vi.mock('../StatusPill', () => ({
  StatusPill: () => <div data-testid="status-pill" />,
}));

const mockOpenReport = vi.fn();
vi.mock('@/lib/report', () => ({
  useReportDialog: (selector: (s: { openReport: () => void }) => unknown) =>
    selector({ openReport: mockOpenReport }),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeEntry(overrides: Partial<FileEntry>): FileEntry {
  return {
    id: 'entry-1',
    file: null,
    fileName: 'parcels.csv',
    status: 'preview',
    jobId: 'job-1',
    previewData: null,
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('BulkReviewList — "Report this problem" CTA', () => {
  beforeEach(() => {
    mockOpenReport.mockClear();
  });

  it('(a) renders for the sole/first entry\'s upload-failed error', () => {
    const entry = makeEntry({
      id: 'entry-1',
      status: 'upload-failed',
      error: 'Upload failed: HTTP 500',
    });

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    // Regression: expandedId seeds from entries[0], so isExpanded is true for
    // the first entry even though upload-failed is never expandable
    // (canExpand === false) — a guard on isExpanded alone hid this error.
    expect(screen.getByText('Upload failed: HTTP 500')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Report this problem/ })).toBeInTheDocument();
  });

  it('(b) renders for a non-first upload-failed entry', () => {
    const entries = [
      makeEntry({ id: 'entry-ok', status: 'preview', previewData: null }),
      makeEntry({ id: 'entry-bad', status: 'upload-failed', error: 'Upload failed: HTTP 500' }),
    ];

    render(
      <BulkReviewList
        entries={entries}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    expect(screen.getByText('Upload failed: HTTP 500')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Report this problem/ })).toBeInTheDocument();
  });

  it('(c) renders inside the expanded panel for a commit-failed entry', () => {
    const entry = makeEntry({
      id: 'entry-1',
      status: 'commit-failed',
      error: 'Failed to start import',
      previewData: {
        job_id: 'job-1',
        source_filename: 'parcels.csv',
        columns: [],
        geometry_type: 'Point',
        crs: 4326,
        layer_name: 'only',
        layers: [{ name: 'only', feature_count: 5, field_count: 2 }],
        sample_rows: [],
        feature_count: 5,
        detected_geometry_columns: null,
      },
    });

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    expect(screen.getByText('Failed to start import')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Report this problem/ })).toBeInTheDocument();
  });

  it('(d) does NOT render for a healthy preview entry', () => {
    const entry = makeEntry({
      id: 'entry-1',
      status: 'preview',
      previewData: {
        job_id: 'job-1',
        source_filename: 'parcels.csv',
        columns: [],
        geometry_type: 'Point',
        crs: 4326,
        layer_name: 'only',
        layers: [{ name: 'only', feature_count: 5, field_count: 2 }],
        sample_rows: [],
        feature_count: 5,
        detected_geometry_columns: null,
      },
    });

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    expect(screen.queryByRole('button', { name: /Report this problem/ })).not.toBeInTheDocument();
  });

  it('(e) clicking it opens the report wizard', async () => {
    const user = userEvent.setup();
    const entry = makeEntry({
      id: 'entry-1',
      status: 'upload-failed',
      error: 'Upload failed: HTTP 500',
    });

    render(
      <BulkReviewList
        entries={[entry]}
        onCommitSingle={noopCommitSingle}
        onCommitAll={noopCommitAll}
        onRemove={noopRemove}
        isCommitting={false}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Report this problem/ }));

    expect(mockOpenReport).toHaveBeenCalledOnce();
  });
});
