/**
 * PR #274 follow-up regression test — drops during the upload-config fetch
 *
 * The dropzone used to be disabled while useUploadConfig was fetching, which
 * made react-dropzone silently swallow files staged in that window (no toast,
 * no request, no same-page recovery). UploadForm now queues those drops and
 * flushes them once the query settles, re-applying the batch cap with the
 * fresh quota.
 */
import { render, screen, act, waitFor } from '@/test/test-utils';
import { UploadForm } from '../UploadForm';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts?.defaultValue === 'string') return opts.defaultValue;
      return key;
    },
  }),
}));

vi.mock('@/api/ingest', () => ({
  uploadFile: vi.fn(),
  uploadPresigned: vi.fn(),
  previewFile: vi.fn(),
  commitImport: vi.fn(),
}));

// Controllable useUploadConfig state — tests mutate this then rerender.
let mockConfig: { data: unknown; isFetching: boolean } = { data: null, isFetching: false };
vi.mock('@/components/import/hooks/use-ingest', () => ({
  useUploadConfig: () => mockConfig,
}));

// Stub the dropzone: expose onFilesAccepted via buttons so tests can stage
// drops without real DOM file inputs.
vi.mock('../FileDropzone', async (importOriginal) => {
  const original = await importOriginal<typeof import('../FileDropzone')>();
  return {
    effectiveBatchLimit: original.effectiveBatchLimit,
    FileDropzone: ({
      onFilesAccepted,
      remainingQuota,
    }: {
      onFilesAccepted: (files: File[]) => void;
      remainingQuota?: number | null;
    }) => (
      <div data-testid="file-dropzone" data-remaining-quota={String(remainingQuota)}>
        <button
          data-testid="drop-one"
          onClick={() => onFilesAccepted([new File(['{}'], 'a.geojson')])}
        >
          Drop one
        </button>
        <button
          data-testid="drop-two"
          onClick={() =>
            onFilesAccepted([new File(['{}'], 'b.geojson'), new File(['{}'], 'c.geojson')])
          }
        >
          Drop two
        </button>
      </div>
    ),
  };
});

vi.mock('../BulkUploadProgress', () => ({
  BulkUploadProgress: () => <div data-testid="bulk-upload-progress" />,
}));
vi.mock('../BulkReviewList', () => ({
  BulkReviewList: () => <div data-testid="bulk-review-list" />,
}));
vi.mock('../BulkTrackingList', () => ({
  BulkTrackingList: () => <div data-testid="bulk-tracking-list" />,
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

// ---------------------------------------------------------------------------

import { uploadFile, previewFile } from '@/api/ingest';
import { toast } from 'sonner';

const mockUploadFile = vi.mocked(uploadFile);
const mockPreviewFile = vi.mocked(previewFile);

beforeEach(() => {
  vi.clearAllMocks();
  mockConfig = { data: null, isFetching: false };
  mockUploadFile.mockResolvedValue({ job_id: 'job-1' } as never);
  mockPreviewFile.mockResolvedValue({
    source_filename: 'a.geojson',
    columns: [],
    row_count: 1,
    geometry_type: 'Point',
    crs: null,
    latlon_candidates: null,
  } as never);
});

describe('UploadForm — queued drops during config fetch', () => {
  it('queues a drop while fetching and processes it once the config settles', async () => {
    mockConfig = { data: null, isFetching: true };
    const { rerender } = render(<UploadForm />);

    await act(async () => {
      screen.getByTestId('drop-one').click();
    });

    // Still fetching: nothing processed, nothing swallowed silently.
    expect(mockUploadFile).not.toHaveBeenCalled();
    expect(screen.getByTestId('file-dropzone')).toBeInTheDocument();

    mockConfig = { data: { remaining_dataset_quota: null }, isFetching: false };
    await act(async () => {
      rerender(<UploadForm />);
    });

    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(1));
  });

  it('merges multiple drops staged in the same fetch window', async () => {
    mockConfig = { data: null, isFetching: true };
    const { rerender } = render(<UploadForm />);

    await act(async () => {
      screen.getByTestId('drop-one').click();
    });
    await act(async () => {
      screen.getByTestId('drop-two').click();
    });

    mockConfig = { data: { remaining_dataset_quota: null }, isFetching: false };
    await act(async () => {
      rerender(<UploadForm />);
    });

    // All three files from both drops upload — the second drop didn't
    // overwrite the first.
    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(3));
  });

  it('rejects a queued batch that exceeds the fresh quota, whole, with a toast', async () => {
    mockConfig = { data: null, isFetching: true };
    const { rerender } = render(<UploadForm />);

    await act(async () => {
      screen.getByTestId('drop-two').click();
    });

    // Fresh quota allows only 1 dataset — the 2-file batch is over the cap.
    mockConfig = { data: { remaining_dataset_quota: 1 }, isFetching: false };
    await act(async () => {
      rerender(<UploadForm />);
    });

    expect(mockUploadFile).not.toHaveBeenCalled();
    expect(vi.mocked(toast.error)).toHaveBeenCalledTimes(1);
    // Form stays idle so the user can retry immediately.
    expect(screen.getByTestId('file-dropzone')).toBeInTheDocument();
  });

  it('passes a permissive quota to the dropzone while fetching, the live one after', async () => {
    // Cached stale-LOW quota during the refetch window must not reach
    // react-dropzone's maxFiles — it would reject a multi-file drop before the
    // queue could re-validate it against the fresh value (Codex P2 on #432).
    mockConfig = { data: { remaining_dataset_quota: 1 }, isFetching: true };
    const { rerender } = render(<UploadForm />);
    expect(screen.getByTestId('file-dropzone')).toHaveAttribute('data-remaining-quota', 'null');

    mockConfig = { data: { remaining_dataset_quota: 7 }, isFetching: false };
    await act(async () => {
      rerender(<UploadForm />);
    });
    expect(screen.getByTestId('file-dropzone')).toHaveAttribute('data-remaining-quota', '7');
  });

  it('processes immediately when the config is already settled', async () => {
    mockConfig = { data: { remaining_dataset_quota: null }, isFetching: false };
    render(<UploadForm />);

    await act(async () => {
      screen.getByTestId('drop-one').click();
    });

    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(1));
    expect(vi.mocked(toast.error)).not.toHaveBeenCalled();
  });
});
