/**
 * fix(#1832): a drop made while the upload-config query is still fetching
 * must survive the form unmounting before that query settles.
 *
 * `e2e/upload.spec.ts:51` ("a tab switch mid-upload does not strand the
 * batch") flaked ~30% of the time: `handleFilesAccepted` queued the drop in
 * a plain `useState` (`pendingFiles`) while `useUploadConfig()` was still
 * fetching, and a tab switch that unmounted `UploadForm` before the flush
 * effect ran discarded that queue outright — nothing had reached
 * `startUploadEntry`'s module-scoped session yet for a remount to adopt, so
 * the remounted form came back to a genuinely empty dropzone. This pins the
 * fix: the queue itself moved to module scope (`upload-session.ts`'s
 * `queuePendingUploadFiles`/`peekPendingUploadFiles`), so a remount rehydrates
 * it instead of starting blank.
 */
import { render, screen, waitFor, act } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { UploadForm } from '../UploadForm';
import { clearUploadBatch, clearPendingUploadFiles } from '@/api/upload-session';

const mockUploadFile = vi.fn();
const mockPreviewFile = vi.fn();

vi.mock('@/api/ingest', () => ({
  uploadFile: (...args: unknown[]) => mockUploadFile(...args),
  uploadPresigned: (...args: unknown[]) => mockUploadFile(...args),
  previewFile: (...args: unknown[]) => mockPreviewFile(...args),
  commitImport: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts?.defaultValue === 'string') return opts.defaultValue;
      return key;
    },
  }),
}));

// fix(#1832): unlike UploadForm.unmount.test.tsx's static mock, this one
// needs to flip from fetching to settled WHILE the form is unmounted, the
// exact window the report pins. `vi.hoisted` so the mutable flag survives
// the vi.mock factory's hoist.
const uploadConfigState = vi.hoisted(() => ({ isFetching: true }));
vi.mock('@/components/import/hooks/use-ingest', () => ({
  useUploadConfig: () => ({
    data: uploadConfigState.isFetching
      ? undefined
      : {
          allowed_extensions: null,
          max_file_size_bytes: 1_000_000_000,
          remaining_dataset_quota: 100,
          presigned_uploads: false,
        },
    isFetching: uploadConfigState.isFetching,
  }),
}));

vi.mock('../FileDropzone', () => ({
  FileDropzone: ({ onFilesAccepted }: { onFilesAccepted: (files: File[]) => void }) => (
    <div data-testid="file-dropzone">
      <button
        data-testid="simulate-drop"
        onClick={() => onFilesAccepted([new File(['{}'], 'sample.geojson')])}
      >
        Drop
      </button>
    </div>
  ),
  // Real implementation would need the live quota; a fixed cap is enough
  // for this race, which never approaches it.
  effectiveBatchLimit: () => 10,
}));

vi.mock('../BulkUploadProgress', () => ({
  BulkUploadProgress: () => <div data-testid="bulk-upload-progress" />,
}));

vi.mock('../BulkReviewList', () => ({
  BulkReviewList: ({
    entries,
  }: {
    entries: Array<{ id: string; fileName: string }>;
  }) => (
    <div data-testid="bulk-review-list">
      {entries.map((e) => (
        <span key={e.id} data-testid={`entry-${e.id}`}>
          {e.fileName}
        </span>
      ))}
    </div>
  ),
}));

vi.mock('../BulkTrackingList', () => ({
  BulkTrackingList: () => <div data-testid="bulk-tracking-list" />,
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
  uploadConfigState.isFetching = true;
  clearUploadBatch();
  clearPendingUploadFiles();
});

afterEach(() => {
  clearUploadBatch();
  clearPendingUploadFiles();
});

describe('UploadForm config-fetch race (#1832)', () => {
  test('a drop queued while the config is fetching survives an unmount before the fetch settles', async () => {
    const user = userEvent.setup();
    // Config still fetching when the drop lands.
    uploadConfigState.isFetching = true;
    const view = render(<UploadForm />);

    await user.click(screen.getByTestId('simulate-drop'));

    // Nothing has reached startUploadEntry yet — the drop is queued, not
    // uploading — so the reported "empty dropzone on return" is exactly
    // what an unmount here would show without the module-scoped queue.
    expect(mockUploadFile).not.toHaveBeenCalled();

    // Switch tabs: the Import page unmounts the form BEFORE the config
    // query settles.
    view.unmount();

    // The config query finishes while nothing is mounted to flush its
    // effect.
    uploadConfigState.isFetching = false;

    // Coming back rehydrates the queued drop from module scope and flushes
    // it now that the config is ready, instead of starting from a blank
    // dropzone.
    render(<UploadForm />);

    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(1));
    expect(mockUploadFile.mock.calls[0][0].name).toBe('sample.geojson');
  });

  test('a second remount does not re-flush a queue the first remount already claimed', async () => {
    // Guards the other half of the fix: `clearPendingUploadFiles()` in the
    // flush effect must actually empty the module-scoped queue, or a
    // second remount racing the same settle (e.g. two quick tab switches)
    // would re-submit the same drop a second time. Each mount below is
    // unmounted before the next, matching how the Import page actually
    // swaps tabs (one form mounted at a time) rather than leaving two
    // instances live at once.
    const user = userEvent.setup();
    uploadConfigState.isFetching = true;
    const first = render(<UploadForm />);

    await user.click(screen.getByTestId('simulate-drop'));
    expect(mockUploadFile).not.toHaveBeenCalled();

    first.unmount();
    uploadConfigState.isFetching = false;

    // First remount observes the now-settled config and claims the queue.
    const second = render(<UploadForm />);
    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(1));

    // Second remount right after finds nothing left to claim.
    second.unmount();
    render(<UploadForm />);
    await act(async () => {});
    expect(mockUploadFile).toHaveBeenCalledTimes(1);
  });
});
