/**
 * GPKG-03 Phase 1058-04 — UploadForm multi-layer fan-out (single commitFanOut call).
 *
 * Tests:
 * (a) single-layer entry: commitFanOut NOT called
 * (b) multi-layer entry: commitFanOut called ONCE with all layers in payload
 * (c) results modal renders per-layer success/failure from FanOutCommitResponse
 * (d) entry transitions to 'tracking' on full success; commit-failed on any failure
 * (e) network-level failure (commitFanOut throws) → all layers shown as failed
 *
 * T-1058C-03 resolved: commitImport is NOT called at all — single commitFanOut
 * replaces the N-commit loop that the backend rejected after job_id #1.
 */
import { render, screen, act, waitFor } from '@/test/test-utils';
import { UploadForm } from '../UploadForm';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock('react-i18next', () => ({
  useTranslation: (ns?: string) => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (key === 'common:close') return 'Close';
      if (key === 'upload.multiLayerResultsTitle') return 'Multi-layer ingest results';
      if (key === 'upload.multiLayerResultsSummary' && opts) {
        return `${opts.succeeded} succeeded, ${opts.failed} failed.`;
      }
      if (key === 'upload.multiLayerSuccess' && opts) {
        return `Imported ${opts.count} layers as separate datasets.`;
      }
      if (key === 'upload.multiLayerAllFailed') return 'All layers failed to import.';
      if (key === 'upload.multiLayerPartialFailed' && opts) {
        return `${opts.succeeded} layers imported, ${opts.failed} failed.`;
      }
      if (key === 'upload.multiLayerRetryClose') return 'Close (retry by re-clicking Ingest all layers)';
      if (key === 'upload.commitFailed') return 'Commit failed.';
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

// Mock commitFanOut from datasets.ts (Phase 1058-04 single-call fan-out)
vi.mock('@/api/datasets', () => ({
  commitFanOut: vi.fn(),
}));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useUploadConfig: () => ({ data: null }),
}));

// Stub heavy child components
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
    onIngestAllLayers,
    entries,
  }: {
    onCommitSingle: (id: string, req: object) => void;
    onCommitAll: () => void;
    onRemove: (id: string) => void;
    onIngestAllLayers?: (id: string) => void;
    entries: Array<{ id: string; fileName: string }>;
  }) => (
    <div data-testid="bulk-review-list">
      {entries.map((e) => (
        <div key={e.id} data-testid={`entry-${e.id}`}>
          <button data-testid={`commit-${e.id}`} onClick={() => onCommitSingle(e.id, { title: e.fileName })}>
            Commit
          </button>
          <button data-testid={`ingest-all-${e.id}`} onClick={() => onIngestAllLayers?.(e.id)}>
            Ingest all
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
  toast: { success: vi.fn(), warning: vi.fn() },
}));

// ---------------------------------------------------------------------------
// Imports and helpers
// ---------------------------------------------------------------------------

import { commitImport, previewFile, uploadFile } from '@/api/ingest';
import { commitFanOut } from '@/api/datasets';
import { toast } from 'sonner';

const mockUploadFile = vi.mocked(uploadFile);
const mockPreviewFile = vi.mocked(previewFile);
const mockCommitImport = vi.mocked(commitImport);
const mockCommitFanOut = vi.mocked(commitFanOut);
const mockToast = vi.mocked(toast.success);

/** Multi-layer file preview fixture (layerCount layers). */
function makeMultiLayerPreview(layerCount: number = 2) {
  return {
    job_id: 'job-1',
    source_filename: 'test.gpkg',
    columns: [],
    row_count: 0,
    geometry_type: 'Point',
    crs: null,
    latlon_candidates: null,
    layer_name: 'layer_a',
    layers: Array.from({ length: layerCount }, (_, i) => ({
      name: `layer_${String.fromCharCode(97 + i)}`,
      feature_count: 10 * (i + 1),
      field_count: 3,
    })),
    sample_rows: [],
    feature_count: 10,
    detected_geometry_columns: null,
  };
}

/** Single-layer file preview fixture. */
function makeSingleLayerPreview() {
  return {
    job_id: 'job-1',
    source_filename: 'test.gpkg',
    columns: [],
    row_count: 0,
    geometry_type: 'Point',
    crs: null,
    latlon_candidates: null,
    layer_name: 'only',
    layers: [{ name: 'only', feature_count: 5, field_count: 2 }],
    sample_rows: [],
    feature_count: 5,
    detected_geometry_columns: null,
  };
}

/** Build a FanOutCommitResponse fixture from a list of layer outcomes. */
function makeFanOutResponse(
  layerResults: Array<{ layer_name: string; status: 'queued' | 'failed'; error?: string }>,
) {
  return {
    fan_out_id: 'job-1',
    results: layerResults.map((r) => ({
      layer_name: r.layer_name,
      new_job_id: r.status === 'queued' ? `new-${r.layer_name}` : null,
      dataset_id: null,
      status: r.status,
      error: r.error ?? null,
    })),
  };
}

/** Drive UploadForm to the reviewing phase with the given preview. */
async function driveToReview(preview: ReturnType<typeof makeMultiLayerPreview>) {
  mockUploadFile.mockResolvedValue({ job_id: 'job-1' } as never);
  mockPreviewFile.mockResolvedValue(preview as never);

  render(<UploadForm />);

  await act(async () => {
    screen.getByTestId('simulate-drop').click();
  });

  await screen.findByTestId('bulk-review-list');
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('UploadForm — multi-layer fan-out via commitFanOut (GPKG-03 Phase 1058-04)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('(a) does nothing for single-layer entries — commitFanOut NOT called', async () => {
    await driveToReview(makeSingleLayerPreview());

    const entries = screen.getAllByTestId(/^entry-/);
    const entryId = entries[0].getAttribute('data-testid')!.replace('entry-', '');

    await act(async () => {
      screen.getByTestId(`ingest-all-${entryId}`).click();
    });

    expect(mockCommitFanOut).not.toHaveBeenCalled();
    expect(mockCommitImport).not.toHaveBeenCalled();
  });

  it('(b) commitFanOut called ONCE with all layers — NOT N separate commitImport calls', async () => {
    mockCommitFanOut.mockResolvedValue(
      makeFanOutResponse([
        { layer_name: 'layer_a', status: 'queued' },
        { layer_name: 'layer_b', status: 'queued' },
        { layer_name: 'layer_c', status: 'queued' },
      ]) as never,
    );

    await driveToReview(makeMultiLayerPreview(3));

    const entries = screen.getAllByTestId(/^entry-/);
    const entryId = entries[0].getAttribute('data-testid')!.replace('entry-', '');

    await act(async () => {
      screen.getByTestId(`ingest-all-${entryId}`).click();
    });

    await waitFor(() => {
      expect(mockCommitFanOut).toHaveBeenCalledTimes(1);
    });

    // commitImport must NOT be called (T-1058C-03 fix)
    expect(mockCommitImport).not.toHaveBeenCalled();

    // Verify payload: jobId + all 3 layers
    const [jobId, layersArg] = mockCommitFanOut.mock.calls[0];
    expect(jobId).toBe('job-1');
    expect(layersArg).toHaveLength(3);

    const layerNames = layersArg.map((l: { layer_name: string }) => l.layer_name);
    expect(layerNames).toContain('layer_a');
    expect(layerNames).toContain('layer_b');
    expect(layerNames).toContain('layer_c');

    // Each layer should have a derived title
    const titles = layersArg.map((l: { title?: string }) => l.title);
    expect(titles[0]).toMatch(/^test: layer_/);
  });

  it('(c) results modal renders per-layer success/failure from FanOutCommitResponse', async () => {
    mockCommitFanOut.mockResolvedValue(
      makeFanOutResponse([
        { layer_name: 'layer_a', status: 'queued' },
        { layer_name: 'layer_b', status: 'failed', error: 'Dispatch failed' },
      ]) as never,
    );

    await driveToReview(makeMultiLayerPreview(2));

    const entries = screen.getAllByTestId(/^entry-/);
    const entryId = entries[0].getAttribute('data-testid')!.replace('entry-', '');

    await act(async () => {
      screen.getByTestId(`ingest-all-${entryId}`).click();
    });

    await waitFor(() => {
      expect(screen.getByText('Multi-layer ingest results')).toBeInTheDocument();
    });

    // Summary shows 1 succeeded + 1 failed
    expect(screen.getByText('1 succeeded, 1 failed.')).toBeInTheDocument();

    // Both layer names appear in the modal
    expect(screen.getByText('layer_a')).toBeInTheDocument();
    expect(screen.getByText('layer_b')).toBeInTheDocument();

    // Error message for the failed layer
    expect(screen.getByText('Dispatch failed')).toBeInTheDocument();
  });

  it('(d) entry transitions to tracking on full success; toast fires', async () => {
    mockCommitFanOut.mockResolvedValue(
      makeFanOutResponse([
        { layer_name: 'layer_a', status: 'queued' },
        { layer_name: 'layer_b', status: 'queued' },
      ]) as never,
    );

    await driveToReview(makeMultiLayerPreview(2));

    const entries = screen.getAllByTestId(/^entry-/);
    const entryId = entries[0].getAttribute('data-testid')!.replace('entry-', '');

    await act(async () => {
      screen.getByTestId(`ingest-all-${entryId}`).click();
    });

    // On full success, toast fires and entry moves to 'tracking'
    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith(expect.stringContaining('Imported'));
    });

    // Phase transitions to tracking (all entries tracking → tracking phase)
    await waitFor(() => {
      expect(screen.getByTestId('bulk-tracking-list')).toBeInTheDocument();
    });
  });

  it('(e) network failure in commitFanOut → all layers shown as failed in modal', async () => {
    mockCommitFanOut.mockRejectedValue(new Error('Network error'));

    await driveToReview(makeMultiLayerPreview(2));

    const entries = screen.getAllByTestId(/^entry-/);
    const entryId = entries[0].getAttribute('data-testid')!.replace('entry-', '');

    await act(async () => {
      screen.getByTestId(`ingest-all-${entryId}`).click();
    });

    // Modal opens showing all failed
    await waitFor(() => {
      expect(screen.getByText('Multi-layer ingest results')).toBeInTheDocument();
    });

    // 0 succeeded, 2 failed
    expect(screen.getByText('0 succeeded, 2 failed.')).toBeInTheDocument();
  });
});
