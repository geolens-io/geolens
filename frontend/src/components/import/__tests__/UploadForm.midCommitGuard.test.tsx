/**
 * fix(#1778): "no layer change mid-commit" guard, bulk path.
 *
 * The #1708 r24 guard (UrlImportForm.tsx's handleLayerChange) was never
 * applied to UploadForm's handleSheetChange, so a mid-commit layer change
 * drove the entry back to 'preview' unconditionally -- re-enabling the
 * commit button against a request already in flight for the same job.
 *
 * This test pins the handler half: while an entry is 'committing',
 * handleSheetChange must bail out before calling previewFile or touching
 * the entry's status.
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
          onFilesAccepted([new File(['{}'], 'test.gpkg', { type: 'application/octet-stream' })])
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
    onSheetChange,
    entries,
  }: {
    onCommitSingle: (id: string, req: object) => void;
    onCommitAll: () => void;
    onRemove: (id: string) => void;
    onSheetChange?: (id: string, layerName: string) => void;
    entries: FileEntry[];
  }) => (
    <div data-testid="bulk-review-list">
      {entries.map((e) => (
        <div key={e.id} data-testid={`entry-${e.id}`} data-status={e.status}>
          <button data-testid={`commit-${e.id}`} onClick={() => onCommitSingle(e.id, { title: e.fileName })}>
            Commit
          </button>
          <button data-testid={`change-sheet-${e.id}`} onClick={() => onSheetChange?.(e.id, 'layer_b')}>
            Change layer
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

function makeMultiLayerPreview() {
  return {
    job_id: 'job-1',
    source_filename: 'test.gpkg',
    columns: [],
    row_count: 0,
    geometry_type: 'Point',
    crs: null,
    latlon_candidates: null,
    layer_name: 'layer_a',
    layers: [
      { name: 'layer_a', feature_count: 10, field_count: 3 },
      { name: 'layer_b', feature_count: 20, field_count: 5 },
    ],
    sample_rows: [],
    feature_count: 10,
    detected_geometry_columns: null,
  };
}

describe('UploadForm — layer change is a no-op while the entry is committing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not call previewFile or revert the entry to preview when onSheetChange fires mid-commit', async () => {
    mockUploadFile.mockResolvedValue({ job_id: 'job-1' } as never);
    mockPreviewFile.mockResolvedValue(makeMultiLayerPreview() as never);
    // Commit never resolves in this test, so the entry stays 'committing'
    // for the duration -- exactly the window the r24 guard closes.
    mockCommitImport.mockReturnValue(new Promise(() => {}));

    render(<UploadForm />);

    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });

    const entryEl = await screen.findByTestId(/^entry-/);
    const entryId = entryEl.getAttribute('data-testid')!.replace('entry-', '');
    expect(mockPreviewFile).toHaveBeenCalledTimes(1);

    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    expect(screen.getByTestId(`entry-${entryId}`)).toHaveAttribute('data-status', 'committing');

    await act(async () => {
      screen.getByTestId(`change-sheet-${entryId}`).click();
    });

    // The guard must bail out before re-previewing or reverting status.
    expect(mockPreviewFile).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId(`entry-${entryId}`)).toHaveAttribute('data-status', 'committing');
  });
});
