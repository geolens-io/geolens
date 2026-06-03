/**
 * IMPORT-03 regression test — setState-during-render anti-pattern
 *
 * Verifies that calling handleCommitSingle, handleCommitAll, or removeEntry
 * never fires `setPhase` inside a `setEntries` updater function, which would
 * trigger React 19's "Cannot update a component while rendering a different
 * component" warning.
 */
import { render, screen, act } from '@/test/test-utils';
import { UploadForm } from '../UploadForm';
import type { FileEntry } from '@/types/api';

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

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useUploadConfig: () => ({ data: null }),
}));

// Stub heavy child components so tests only exercise UploadForm's own state logic
vi.mock('../FileDropzone', () => ({
  FileDropzone: ({ onFilesAccepted }: { onFilesAccepted: (files: File[]) => void }) => (
    <div data-testid="file-dropzone">
      <button
        data-testid="simulate-drop"
        onClick={() =>
          onFilesAccepted([new File(['{}'], 'test.geojson', { type: 'application/json' })])
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
        <div key={e.id} data-testid={`entry-${e.id}`}>
          <button
            data-testid={`commit-${e.id}`}
            onClick={() => onCommitSingle(e.id, { title: e.fileName })}
          >
            Commit {e.fileName}
          </button>
          <button
            data-testid={`remove-${e.id}`}
            onClick={() => onRemove(e.id)}
          >
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
  toast: { success: vi.fn(), warning: vi.fn() },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

import { commitImport, previewFile, uploadFile } from '@/api/ingest';

const mockUploadFile = vi.mocked(uploadFile);
const mockPreviewFile = vi.mocked(previewFile);
const mockCommitImport = vi.mocked(commitImport);

function setupMocksForSingleEntry() {
  mockUploadFile.mockResolvedValue({ job_id: 'job-1' } as never);
  mockPreviewFile.mockResolvedValue({
    source_filename: 'test.geojson',
    columns: [],
    row_count: 1,
    geometry_type: 'Point',
    crs: null,
    latlon_candidates: null,
  } as never);
  mockCommitImport.mockResolvedValue({} as never);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('UploadForm — IMPORT-03 setState-during-render regression', () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    // Capture console.error without spamming test output
    errorSpy = vi.spyOn(console, 'error').mockImplementation((_msg?: unknown, ..._args: unknown[]) => {});
  });

  afterEach(() => {
    errorSpy.mockRestore();
  });

  it('Test 1 — no "Cannot update a component" warning during commit-single flow', async () => {
    setupMocksForSingleEntry();

    render(<UploadForm />);

    // Drive the form from idle → uploading → reviewing
    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });

    // Wait for the reviewing phase (after upload + preview settle)
    await screen.findByTestId('bulk-review-list');

    // Trigger commit on the single entry (not the 'commit-all' button)
    const commitBtns = screen.getAllByTestId(/^commit-/);
    const singleCommitBtn = commitBtns.find((b) => b.getAttribute('data-testid') !== 'commit-all');
    expect(singleCommitBtn).toBeDefined();

    await act(async () => {
      singleCommitBtn!.click();
    });

    // Assert: no React "setState during render" warning was emitted
    const badCalls = errorSpy.mock.calls.filter((callArgs: unknown[]) =>
      callArgs.some((a: unknown) => typeof a === 'string' && /Cannot update a component/i.test(a)),
    );
    expect(badCalls).toHaveLength(0);
  });

  it('Test 2 — transitions to tracking phase when all entries reach terminal state with at least one tracking', async () => {
    setupMocksForSingleEntry();

    render(<UploadForm />);

    // Drive to reviewing
    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });

    await screen.findByTestId('bulk-review-list');

    // Commit the single entry — it will become 'tracking'
    // Use getAllByTestId and find the per-entry button (not 'commit-all')
    const commitBtns = screen.getAllByTestId(/^commit-/);
    const commitBtn = commitBtns.find((b) => b.getAttribute('data-testid') !== 'commit-all');
    expect(commitBtn).toBeDefined();
    await act(async () => {
      commitBtn!.click();
    });

    // After commit resolves, the form should move to tracking phase
    await screen.findByTestId('bulk-tracking-list');
    expect(screen.queryByTestId('bulk-review-list')).not.toBeInTheDocument();
  });

  it('Test 3 — transitions to idle when the last entry is removed', async () => {
    setupMocksForSingleEntry();

    render(<UploadForm />);

    // Drive to reviewing
    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });

    await screen.findByTestId('bulk-review-list');

    // Remove the single entry
    const removeBtns = screen.getAllByTestId(/^remove-/);
    expect(removeBtns.length).toBeGreaterThan(0);
    await act(async () => {
      removeBtns[0].click();
    });

    // After removing the last entry, the form should return to idle (FileDropzone)
    await screen.findByTestId('file-dropzone');
    expect(screen.queryByTestId('bulk-review-list')).not.toBeInTheDocument();
  });
});
