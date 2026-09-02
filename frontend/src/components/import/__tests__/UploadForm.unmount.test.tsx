/**
 * fix(#1712): an upload batch must survive the form unmounting.
 *
 * The Import page renders tabs conditionally, so switching away mid-upload
 * unmounts UploadForm. The upload (and the preview call chained after it)
 * keeps running server-side, so if the returned job id lands in dead
 * component state the user is left with an unreachable pending job and its
 * staged bytes until the stale-pending sweep collects them. Mirrors
 * UrlImportForm.unmount.test.tsx (#1708) for this tab's batch shape.
 */
import { render, screen, waitFor, act } from '@/test/test-utils';
import { UploadForm } from '../UploadForm';
import { clearUploadBatch, peekUploadBatch } from '@/api/upload-session';
import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';

const mockUploadFile = vi.fn();
const mockPreviewFile = vi.fn();
const mockCommitImport = vi.fn();

vi.mock('@/api/ingest', () => ({
  uploadFile: (...args: unknown[]) => mockUploadFile(...args),
  uploadPresigned: (...args: unknown[]) => mockUploadFile(...args),
  previewFile: (...args: unknown[]) => mockPreviewFile(...args),
  commitImport: (...args: unknown[]) => mockCommitImport(...args),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts?.defaultValue === 'string') return opts.defaultValue;
      return key;
    },
  }),
}));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useUploadConfig: () => ({ data: null, isFetching: false }),
}));

vi.mock('../FileDropzone', () => ({
  FileDropzone: ({ onFilesAccepted }: { onFilesAccepted: (files: File[]) => void }) => (
    <div data-testid="file-dropzone">
      <button
        data-testid="simulate-drop"
        onClick={() => onFilesAccepted([new File(['{}'], 'roads.geojson')])}
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
    onSheetChange,
    entries,
  }: {
    onCommitSingle: (id: string, req: object) => void;
    onSheetChange?: (id: string, layerName: string) => void;
    entries: Array<{
      id: string;
      fileName: string;
      error: string | null;
      previewData: { layer_name: string; layers?: { name: string }[] | null } | null;
    }>;
  }) => (
    <div data-testid="bulk-review-list">
      {entries.map((e) => {
        // Mirrors BulkReviewList's real layerName derivation: only sent on
        // an actual multi-layer file, matching #1685.
        const multiLayer = (e.previewData?.layers?.length ?? 0) > 1;
        const layerName = multiLayer ? e.previewData?.layer_name : undefined;
        return (
          <div key={e.id} data-testid={`entry-${e.id}`}>
            {e.error && <span data-testid={`error-${e.id}`}>{e.error}</span>}
            {e.previewData && (
              <span data-testid={`layer-${e.id}`}>{e.previewData.layer_name}</span>
            )}
            {multiLayer &&
              e.previewData?.layers?.map((layer) => (
                <button
                  key={layer.name}
                  data-testid={`select-layer-${e.id}-${layer.name}`}
                  onClick={() => onSheetChange?.(e.id, layer.name)}
                >
                  {layer.name}
                </button>
              ))}
            <button
              data-testid={`commit-${e.id}`}
              onClick={() =>
                onCommitSingle(e.id, layerName ? { title: e.fileName, layer_name: layerName } : { title: e.fileName })
              }
            >
              Commit
            </button>
          </div>
        );
      })}
    </div>
  ),
}));

vi.mock('../BulkTrackingList', () => ({
  BulkTrackingList: () => <div data-testid="bulk-tracking-list" />,
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

const VECTOR_PREVIEW = {
  job_id: 'job-survives',
  source_filename: 'roads.geojson',
  columns: [{ name: 'id', type: 'Integer' }],
  crs: 4326,
  geometry_type: 'LineString',
  feature_count: 3,
  sample_rows: [],
  layer_name: 'roads',
  layers: null,
};

// fix(codex #1763 r2): a multi-layer file, so switching the reviewed layer
// (BulkReviewList's layer picker) is exercisable.
const MULTI_LAYER_PREVIEW = {
  job_id: 'job-multi',
  source_filename: 'parcels.gpkg',
  columns: [{ name: 'id', type: 'Integer' }],
  crs: 4326,
  geometry_type: 'Polygon',
  feature_count: 10,
  sample_rows: [],
  layer_name: 'layer_a',
  layers: [
    { name: 'layer_a', feature_count: 10, field_count: 2 },
    { name: 'layer_b', feature_count: 5, field_count: 3 },
  ],
};

const initialAuthState = useAuthStore.getState();

beforeEach(() => {
  vi.clearAllMocks();
  clearUploadBatch();
  useAuthStore.setState(initialAuthState, true);
});

afterEach(() => {
  clearUploadBatch();
  useAuthStore.setState(initialAuthState, true);
});

describe('UploadForm unmount survival', () => {
  test('a job returned while unmounted is captured', async () => {
    let resolveUpload!: (v: { job_id: string; status: string }) => void;
    mockUploadFile.mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );
    mockPreviewFile.mockResolvedValue(VECTOR_PREVIEW);

    const view = render(<UploadForm />);
    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });
    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(1));

    // Switch tabs: the Import page unmounts the form.
    view.unmount();

    // The server finishes anyway.
    resolveUpload({ job_id: 'job-survives', status: 'pending' });

    await waitFor(() => {
      const entries = peekUploadBatch();
      expect(entries?.[0]?.jobId).toBe('job-survives');
    });
    await waitFor(() => {
      const entries = peekUploadBatch();
      expect(entries?.[0]?.status).toBe('preview');
    });
  });

  test('remount adopts the in-flight batch instead of starting a second one', async () => {
    mockUploadFile.mockReturnValue(new Promise(() => {}));

    const view = render(<UploadForm />);
    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });
    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(1));

    view.unmount();
    render(<UploadForm />);

    // Still exactly one server-side upload, and the remounted form shows
    // the in-flight progress view rather than an idle dropzone.
    expect(mockUploadFile).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.getByTestId('bulk-upload-progress')).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('file-dropzone')).not.toBeInTheDocument();
  });

  test('failure while unmounted settles and clears', async () => {
    let rejectUpload!: (e: unknown) => void;
    mockUploadFile.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectUpload = reject;
      }),
    );

    const view = render(<UploadForm />);
    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });
    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(1));

    view.unmount();
    rejectUpload(new Error('boom'));

    // The rejection is handled at module scope (no unhandled rejection —
    // startUploadEntry's promise chain never rejects), and the session
    // records the failure rather than losing it.
    await waitFor(() => {
      const entries = peekUploadBatch();
      expect(entries?.[0]?.status).toBe('upload-failed');
    });

    // Remounting surfaces the failure in the review list...
    render(<UploadForm />);
    await waitFor(() =>
      expect(screen.getByTestId('bulk-review-list')).toBeInTheDocument(),
    );
    const errorNode = screen.getByText(/upload\.uploadFailed/);
    expect(errorNode).toBeInTheDocument();
    expect(mockPreviewFile).not.toHaveBeenCalled();

    // ...and once the user dismisses it (Start Over), the session clears.
    await act(async () => {
      screen.getByText('upload.startOver').click();
    });
    expect(peekUploadBatch()).toBeNull();
  });

  test('successful commit releases the session', async () => {
    mockUploadFile.mockResolvedValue({ job_id: 'job-committed', status: 'pending' });
    mockPreviewFile.mockResolvedValue({ ...VECTOR_PREVIEW, job_id: 'job-committed' });
    mockCommitImport.mockResolvedValue({});

    render(<UploadForm />);
    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });
    await waitFor(() =>
      expect(screen.getByTestId('bulk-review-list')).toBeInTheDocument(),
    );
    expect(peekUploadBatch()).not.toBeNull();

    await act(async () => {
      const commitBtn = screen.getByTestId(/^commit-/);
      commitBtn.click();
    });

    await waitFor(() =>
      expect(screen.getByTestId('bulk-tracking-list')).toBeInTheDocument(),
    );
    // fix(#1712): holding the session past commit would let a later remount
    // re-preview an already-processed job, which the API refuses with 400.
    expect(peekUploadBatch()).toBeNull();
  });

  test('a different identity does not adopt the batch', async () => {
    useAuthStore.setState({
      token: 't1',
      user: { id: 'user-1' } as UserResponse,
    });
    mockUploadFile.mockReturnValue(new Promise(() => {}));

    const view = render(<UploadForm />);
    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });
    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(1));
    view.unmount();

    // A different identity signs in before the next mount.
    useAuthStore.setState({ token: 't2', user: { id: 'user-2' } as UserResponse });

    render(<UploadForm />);

    // No adoption: the second identity sees an idle dropzone, and does not
    // start a second upload against the first identity's abandoned batch.
    await waitFor(() => expect(screen.getByTestId('file-dropzone')).toBeInTheDocument());
    expect(mockUploadFile).toHaveBeenCalledTimes(1);
    expect(peekUploadBatch()).toBeNull();
  });

  // fix(codex #1763 r2): a layer reselect used to write only to component
  // state, so the session kept the ORIGINAL layer and a remount restored
  // it — a subsequent default commit would silently ingest the wrong layer.
  test('a layer reselected before unmount is still selected on remount, and commit sends it', async () => {
    mockUploadFile.mockResolvedValue({ job_id: 'job-multi', status: 'pending' });
    mockPreviewFile.mockImplementation((_jobId: string, layerName?: string) =>
      Promise.resolve(
        layerName
          ? { ...MULTI_LAYER_PREVIEW, layer_name: layerName }
          : MULTI_LAYER_PREVIEW,
      ),
    );
    mockCommitImport.mockResolvedValue({});

    const view = render(<UploadForm />);
    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });
    await waitFor(() => expect(screen.getByTestId(/^layer-/)).toHaveTextContent('layer_a'));

    const entryTestId = screen.getAllByTestId(/^entry-/)[0].getAttribute('data-testid')!;
    const entryId = entryTestId.replace('entry-', '');

    // Select the second layer.
    await act(async () => {
      screen.getByTestId(`select-layer-${entryId}-layer_b`).click();
    });
    await waitFor(() =>
      expect(screen.getByTestId(`layer-${entryId}`)).toHaveTextContent('layer_b'),
    );

    // Switch tabs and back.
    view.unmount();
    const sessionEntries = peekUploadBatch();
    expect(sessionEntries?.[0]?.previewData).toMatchObject({ layer_name: 'layer_b' });

    render(<UploadForm />);
    await waitFor(() =>
      expect(screen.getByTestId(`layer-${entryId}`)).toHaveTextContent('layer_b'),
    );

    // A default commit after the remount sends the reselected layer, not
    // the original one.
    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    await waitFor(() => expect(mockCommitImport).toHaveBeenCalledTimes(1));
    expect(mockCommitImport).toHaveBeenCalledWith(
      'job-multi',
      expect.objectContaining({ layer_name: 'layer_b' }),
    );
  });

  test('a layer re-preview still in flight when the form unmounts is captured on remount', async () => {
    mockUploadFile.mockResolvedValue({ job_id: 'job-multi', status: 'pending' });
    mockPreviewFile.mockResolvedValueOnce(MULTI_LAYER_PREVIEW);

    const view = render(<UploadForm />);
    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });
    await waitFor(() => expect(screen.getByTestId(/^layer-/)).toHaveTextContent('layer_a'));

    const entryTestId = screen.getAllByTestId(/^entry-/)[0].getAttribute('data-testid')!;
    const entryId = entryTestId.replace('entry-', '');

    // Re-preview under layer_b never resolves on its own — the test settles
    // it after the unmount below.
    let resolveReselect!: (v: unknown) => void;
    mockPreviewFile.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveReselect = resolve;
      }),
    );

    await act(async () => {
      screen.getByTestId(`select-layer-${entryId}-layer_b`).click();
    });
    await waitFor(() => expect(mockPreviewFile).toHaveBeenCalledWith('job-multi', 'layer_b'));

    // Switch tabs while the re-preview is still in flight.
    view.unmount();
    expect(peekUploadBatch()?.[0]?.status).toBe('previewing');

    // The server answers anyway.
    resolveReselect({ ...MULTI_LAYER_PREVIEW, layer_name: 'layer_b' });

    await waitFor(() => {
      const entries = peekUploadBatch();
      expect(entries?.[0]?.previewData).toMatchObject({ layer_name: 'layer_b' });
    });
    expect(peekUploadBatch()?.[0]?.status).toBe('preview');

    // A later remount shows the resumed selection.
    render(<UploadForm />);
    await waitFor(() =>
      expect(screen.getByTestId(`layer-${entryId}`)).toHaveTextContent('layer_b'),
    );
  });
});
