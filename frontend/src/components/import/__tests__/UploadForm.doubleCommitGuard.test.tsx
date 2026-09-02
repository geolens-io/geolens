/**
 * fix(#1778): handleCommitSingle had no in-flight guard, distinct from the
 * layer-picker bulk guard (BulkReviewList.midCommitGuard.test.tsx /
 * UploadForm.midCommitGuard.test.tsx) and from the in-flight upload session
 * (#1763). The commit button only disables once the entry's status has
 * actually re-rendered as 'committing' (isCommitting flows down through
 * BulkReviewList -> ImportMetadataForm's submit button); a click that lands
 * before that re-render commits reached the handler with no guard at all,
 * so a double click issued commitImport twice for one job.
 *
 * This test pins the handler half: a second click on the same entry's
 * commit button, once the first click's 'committing' status has landed,
 * must not call commitImport again.
 */
import { render, screen, act } from '@/test/test-utils';
import { UploadForm } from '../UploadForm';
import type { FileEntry } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: (_ns?: string) => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts?.defaultValue === 'string') return opts.defaultValue;
      return key;
    },
    i18n: { language: 'en' },
  }),
  Trans: ({ i18nKey }: { i18nKey: string }) => i18nKey,
}));

vi.mock('@/api/ingest', () => ({
  uploadFile: vi.fn(),
  uploadPresigned: vi.fn(),
  previewFile: vi.fn(),
  commitImport: vi.fn(),
}));

vi.mock('@/api/datasets', () => ({
  commitFanOut: vi.fn(),
}));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useUploadConfig: () => ({ data: null }),
}));

vi.mock('../FileDropzone', () => ({
  FileDropzone: ({ onFilesAccepted }: { onFilesAccepted: (files: File[]) => void }) => (
    <div data-testid="file-dropzone">
      <button
        data-testid="simulate-drop"
        onClick={() =>
          onFilesAccepted([new File(['{}'], 'test.geojson', { type: 'application/geo+json' })])
        }
      >
        Drop
      </button>
    </div>
  ),
}));

vi.mock('../BulkUploadProgress', () => ({
  BulkUploadProgress: () => <div data-testid="bulk-upload-progress" />,
}));

vi.mock('../BulkReviewList', () => ({
  BulkReviewList: ({
    onCommitSingle,
    onCommitAll,
    onRemove,
    entries,
  }: {
    onCommitSingle: (id: string, req: object) => void;
    onCommitAll: () => void;
    onRemove: (id: string) => void;
    entries: FileEntry[];
  }) => (
    <div data-testid="bulk-review-list">
      {entries.map((e) => (
        <div key={e.id} data-testid={`entry-${e.id}`} data-status={e.status}>
          <button data-testid={`commit-${e.id}`} onClick={() => onCommitSingle(e.id, { title: e.fileName })}>
            Commit
          </button>
          <button data-testid={`remove-${e.id}`} onClick={() => onRemove(e.id)}>
            Remove
          </button>
        </div>
      ))}
      <button data-testid="commit-all" onClick={onCommitAll}>
        Commit All
      </button>
    </div>
  ),
}));

vi.mock('../BulkTrackingList', () => ({
  BulkTrackingList: () => <div data-testid="bulk-tracking-list" />,
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

import { commitImport, previewFile, uploadFile } from '@/api/ingest';

const mockUploadFile = vi.mocked(uploadFile);
const mockPreviewFile = vi.mocked(previewFile);
const mockCommitImport = vi.mocked(commitImport);

function makeSingleLayerPreview() {
  return {
    job_id: 'job-1',
    source_filename: 'test.geojson',
    columns: [],
    row_count: 0,
    geometry_type: 'Point',
    crs: null,
    latlon_candidates: null,
    layer_name: null,
    layers: null,
    sample_rows: [],
    feature_count: 3,
    detected_geometry_columns: null,
  };
}

describe('UploadForm: handleCommitSingle in-flight guard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('two rapid clicks on the commit button issue exactly one commitImport call', async () => {
    mockUploadFile.mockResolvedValue({ job_id: 'job-1' } as never);
    mockPreviewFile.mockResolvedValue(makeSingleLayerPreview() as never);
    // Commit never resolves in this test, so the entry stays 'committing'
    // for the duration -- exactly the window a double click races.
    mockCommitImport.mockReturnValue(new Promise(() => {}));

    render(<UploadForm />);

    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });

    const entryEl = await screen.findByTestId(/^entry-/);
    const entryId = entryEl.getAttribute('data-testid')!.replace('entry-', '');

    // Two rapid clicks. Each is its own act() so the intervening re-render
    // (status -> 'committing') lands between them, the way two separate
    // browser click events -- and two separate calls into the SAME
    // `handleCommitSingle` closure -- would in real double-click timing.
    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });

    expect(mockCommitImport).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId(`entry-${entryId}`)).toHaveAttribute('data-status', 'committing');

    // A third click after the status has settled to 'committing' must also
    // be a no-op -- this is the guard's steady-state behavior, not just the
    // same-tick race.
    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
  });
});
