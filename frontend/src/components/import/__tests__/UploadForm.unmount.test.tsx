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
import { ApiError } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';

const mockUploadFile = vi.fn();
const mockPreviewFile = vi.fn();
const mockCommitImport = vi.fn();
const mockCommitFanOut = vi.fn();

vi.mock('@/api/ingest', () => ({
  uploadFile: (...args: unknown[]) => mockUploadFile(...args),
  uploadPresigned: (...args: unknown[]) => mockUploadFile(...args),
  previewFile: (...args: unknown[]) => mockPreviewFile(...args),
  commitImport: (...args: unknown[]) => mockCommitImport(...args),
}));

vi.mock('@/api/datasets', () => ({
  commitFanOut: (...args: unknown[]) => mockCommitFanOut(...args),
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
      <button
        data-testid="simulate-drop-two"
        onClick={() =>
          onFilesAccepted([new File(['{}'], 'roads.geojson'), new File(['[]'], 'rivers.geojson')])
        }
      >
        Drop two
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
    onCommitAllAsVrt,
    onRemove,
    onSheetChange,
    onIngestAllLayers,
    entries,
  }: {
    onCommitSingle: (id: string, req: object) => void;
    onCommitAll: () => void;
    onCommitAllAsVrt: () => void;
    onRemove: (id: string) => void;
    onSheetChange?: (id: string, layerName: string) => void;
    onIngestAllLayers?: (id: string) => void;
    entries: Array<{
      id: string;
      fileName: string;
      status: string;
      error: string | null;
      previewData: { layer_name: string; layers?: { name: string }[] | null } | null;
    }>;
  }) => (
    <div data-testid="bulk-review-list">
      <button data-testid="commit-all" onClick={onCommitAll}>
        Commit all
      </button>
      <button data-testid="commit-all-vrt" onClick={onCommitAllAsVrt}>
        Commit all as VRT
      </button>
      {entries.map((e) => {
        // Mirrors BulkReviewList's real layerName derivation: only sent on
        // an actual multi-layer file, matching #1685.
        const multiLayer = (e.previewData?.layers?.length ?? 0) > 1;
        const layerName = multiLayer ? e.previewData?.layer_name : undefined;
        return (
          <div key={e.id} data-testid={`entry-${e.id}`} data-status={e.status}>
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
            <button data-testid={`ingest-all-${e.id}`} onClick={() => onIngestAllLayers?.(e.id)}>
              Ingest all layers
            </button>
            <button data-testid={`remove-${e.id}`} onClick={() => onRemove(e.id)}>
              Remove
            </button>
          </div>
        );
      })}
    </div>
  ),
}));

vi.mock('../BulkTrackingList', () => ({
  BulkTrackingList: ({
    entries,
    autoOpenVrt,
  }: {
    entries: Array<{ id: string; jobId: string | null; submittedTitle?: string | null }>;
    autoOpenVrt?: boolean;
  }) => (
    <div data-testid="bulk-tracking-list" data-auto-open-vrt={String(!!autoOpenVrt)}>
      {entries.map((e) => (
        <div key={e.id} data-testid={`tracked-${e.jobId}`} data-title={e.submittedTitle ?? ''} />
      ))}
    </div>
  ),
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
      const entries = peekUploadBatch()?.entries;
      expect(entries?.[0]?.jobId).toBe('job-survives');
    });
    await waitFor(() => {
      const entries = peekUploadBatch()?.entries;
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
      const entries = peekUploadBatch()?.entries;
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

  test('a commit shown as tracked is released, so a later visit neither re-previews nor re-commits it', async () => {
    mockUploadFile.mockResolvedValue({ job_id: 'job-committed', status: 'pending' });
    mockPreviewFile.mockResolvedValue({ ...VECTOR_PREVIEW, job_id: 'job-committed' });
    mockCommitImport.mockResolvedValue({});

    const view = render(<UploadForm />);
    await act(async () => {
      screen.getByTestId('simulate-drop').click();
    });
    const entryEl = await screen.findByTestId(/^entry-/);
    const entryId = entryEl.getAttribute('data-testid')!.replace('entry-', '');

    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    expect(await screen.findByTestId('tracked-job-committed')).toBeInTheDocument();

    view.unmount();
    render(<UploadForm />);
    expect(await screen.findByTestId('file-dropzone')).toBeInTheDocument();
    expect(mockPreviewFile).toHaveBeenCalledTimes(1);
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
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
    const sessionEntries = peekUploadBatch()?.entries;
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
    expect(peekUploadBatch()?.entries[0]?.status).toBe('previewing');

    // The server answers anyway.
    resolveReselect({ ...MULTI_LAYER_PREVIEW, layer_name: 'layer_b' });

    await waitFor(() => {
      const entries = peekUploadBatch()?.entries;
      expect(entries?.[0]?.previewData).toMatchObject({ layer_name: 'layer_b' });
    });
    expect(peekUploadBatch()?.entries[0]?.status).toBe('preview');

    // A later remount shows the resumed selection.
    render(<UploadForm />);
    await waitFor(() =>
      expect(screen.getByTestId(`layer-${entryId}`)).toHaveTextContent('layer_b'),
    );
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function dropAndReview(preview: { job_id: string } = VECTOR_PREVIEW) {
  mockUploadFile.mockResolvedValue({ job_id: preview.job_id, status: 'pending' });
  mockPreviewFile.mockResolvedValue(preview);
  const view = render(<UploadForm />);
  await act(async () => {
    screen.getByTestId('simulate-drop').click();
  });
  const entryEl = await screen.findByTestId(/^entry-/);
  const entryId = entryEl.getAttribute('data-testid')!.replace('entry-', '');
  return { view, entryId };
}

describe('UploadForm commit settlement across unmount', () => {
  test('a commit that succeeds while unmounted is tracked on remount, without another preview or commit', async () => {
    const commit = deferred<unknown>();
    mockCommitImport.mockReturnValue(commit.promise);
    const { view, entryId } = await dropAndReview();

    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    view.unmount();
    await act(async () => {
      commit.resolve({ job_id: 'job-survives', status: 'queued' });
    });

    const remount = render(<UploadForm />);
    expect(await screen.findByTestId('bulk-tracking-list')).toBeInTheDocument();
    expect(screen.getByTestId('tracked-job-survives')).toHaveAttribute('data-title', 'roads.geojson');

    // Shown once, so the next visit starts from the dropzone.
    remount.unmount();
    render(<UploadForm />);
    expect(await screen.findByTestId('file-dropzone')).toBeInTheDocument();
    expect(mockPreviewFile).toHaveBeenCalledTimes(1);
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
  });

  test('remounting before the commit settles adopts it as committing, then tracks it', async () => {
    const commit = deferred<unknown>();
    mockCommitImport.mockReturnValue(commit.promise);
    const { view, entryId } = await dropAndReview();

    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    view.unmount();

    render(<UploadForm />);
    expect(await screen.findByTestId(`entry-${entryId}`)).toHaveAttribute('data-status', 'committing');

    // A commit click on the adopted row must not issue a second commit.
    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });

    await act(async () => {
      commit.resolve({ job_id: 'job-survives', status: 'queued' });
    });
    expect(await screen.findByTestId('tracked-job-survives')).toBeInTheDocument();
    expect(mockPreviewFile).toHaveBeenCalledTimes(1);
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
  });

  test('a commit refused while unmounted comes back reviewable with its error', async () => {
    const commit = deferred<unknown>();
    mockCommitImport.mockReturnValueOnce(commit.promise);
    const { view, entryId } = await dropAndReview();

    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    view.unmount();
    await act(async () => {
      commit.reject(new ApiError('Title already in use', 409));
    });

    render(<UploadForm />);
    expect(await screen.findByTestId(`entry-${entryId}`)).toHaveAttribute('data-status', 'commit-failed');
    expect(screen.getByTestId(`error-${entryId}`)).toHaveTextContent('Title already in use');

    // The review is still usable: a retry commits the same job again.
    mockCommitImport.mockResolvedValueOnce({ job_id: 'job-survives', status: 'queued' });
    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    expect(await screen.findByTestId('tracked-job-survives')).toBeInTheDocument();
    expect(mockCommitImport).toHaveBeenCalledTimes(2);
    expect(mockCommitImport).toHaveBeenLastCalledWith('job-survives', { title: 'roads.geojson' });
    expect(mockPreviewFile).toHaveBeenCalledTimes(1);
  });

  test('a quota refusal while unmounted keeps the quota notice', async () => {
    const commit = deferred<unknown>();
    mockCommitImport.mockReturnValue(commit.promise);
    const { view, entryId } = await dropAndReview();

    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    view.unmount();
    await act(async () => {
      commit.reject(new ApiError('Dataset quota exceeded: 10 of 10 datasets used', 422));
    });

    render(<UploadForm />);
    expect(await screen.findByTestId(`error-${entryId}`)).toHaveTextContent('upload.quotaShort');
    expect(screen.getByText('upload.quotaBannerTitle')).toBeInTheDocument();
    expect(screen.getByText('Dataset quota exceeded: 10 of 10 datasets used')).toBeInTheDocument();
  });

  test('Start Over while a commit is in flight is not revived when it settles', async () => {
    const commit = deferred<unknown>();
    mockCommitImport.mockReturnValue(commit.promise);
    const { view, entryId } = await dropAndReview();

    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    await act(async () => {
      screen.getByText('upload.startOver').click();
    });
    expect(screen.getByTestId('file-dropzone')).toBeInTheDocument();

    await act(async () => {
      commit.resolve({ job_id: 'job-survives', status: 'queued' });
    });
    expect(screen.getByTestId('file-dropzone')).toBeInTheDocument();
    view.unmount();
    render(<UploadForm />);
    expect(await screen.findByTestId('file-dropzone')).toBeInTheDocument();
  });

  test('a removed row is not revived when its commit settles', async () => {
    const commit = deferred<unknown>();
    mockCommitImport.mockReturnValue(commit.promise);
    const { view, entryId } = await dropAndReview();

    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    await act(async () => {
      screen.getByTestId(`remove-${entryId}`).click();
    });
    view.unmount();
    await act(async () => {
      commit.reject(new ApiError('Title already in use', 409));
    });

    render(<UploadForm />);
    expect(await screen.findByTestId('file-dropzone')).toBeInTheDocument();
  });

  test('a commit that settles after an identity change is not adopted by anyone', async () => {
    useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
    const commit = deferred<unknown>();
    mockCommitImport.mockReturnValue(commit.promise);
    const { view, entryId } = await dropAndReview();

    await act(async () => {
      screen.getByTestId(`commit-${entryId}`).click();
    });
    view.unmount();

    useAuthStore.setState({ token: 't2', user: { id: 'user-2' } as UserResponse });
    const secondView = render(<UploadForm />);
    expect(await screen.findByTestId('file-dropzone')).toBeInTheDocument();
    await act(async () => {
      commit.resolve({ job_id: 'job-survives', status: 'queued' });
    });
    expect(screen.getByTestId('file-dropzone')).toBeInTheDocument();
    secondView.unmount();

    // Cleared rather than hidden: the first identity does not get it back.
    useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
    render(<UploadForm />);
    expect(await screen.findByTestId('file-dropzone')).toBeInTheDocument();
    expect(screen.queryByTestId('bulk-tracking-list')).not.toBeInTheDocument();
  });
});

describe('UploadForm Commit All and fan-out across unmount', () => {
  async function dropTwoAndReview() {
    mockUploadFile.mockImplementation((file: File) =>
      Promise.resolve({ job_id: `job-${file.name.split('.')[0]}`, status: 'pending' }),
    );
    mockPreviewFile.mockImplementation((jobId: string) =>
      Promise.resolve({ ...VECTOR_PREVIEW, job_id: jobId, source_filename: `${jobId.slice(4)}.geojson` }),
    );
    const view = render(<UploadForm />);
    await act(async () => {
      screen.getByTestId('simulate-drop-two').click();
    });
    await waitFor(() => expect(screen.getAllByTestId(/^entry-/)).toHaveLength(2));
    const [roadsId, riversId] = screen
      .getAllByTestId(/^entry-/)
      .map((el) => el.getAttribute('data-testid')!.replace('entry-', ''));
    return { view, roadsId, riversId };
  }

  function deferCommitsByJob() {
    const commits = { 'job-roads': deferred<unknown>(), 'job-rivers': deferred<unknown>() };
    mockCommitImport.mockImplementation((jobId: keyof typeof commits) => commits[jobId].promise);
    return commits;
  }

  test('a partial Commit All adopted mid-flight keeps the settled row and tracks the rest', async () => {
    const commits = deferCommitsByJob();
    const { view, roadsId, riversId } = await dropTwoAndReview();

    await act(async () => {
      screen.getByTestId('commit-all').click();
    });
    view.unmount();
    await act(async () => {
      commits['job-roads'].resolve({ job_id: 'job-roads', status: 'queued' });
    });

    render(<UploadForm />);
    expect(await screen.findByTestId(`entry-${roadsId}`)).toHaveAttribute('data-status', 'tracking');
    expect(screen.getByTestId(`entry-${riversId}`)).toHaveAttribute('data-status', 'committing');

    await act(async () => {
      commits['job-rivers'].resolve({ job_id: 'job-rivers', status: 'queued' });
    });
    expect(await screen.findByTestId('tracked-job-roads')).toHaveAttribute('data-title', 'roads');
    expect(screen.getByTestId('tracked-job-rivers')).toHaveAttribute('data-title', 'rivers');
    expect(mockCommitImport).toHaveBeenCalledTimes(2);
  });

  test('a Commit All with a refusal stays in review, across tab switches, until the refusal is retried', async () => {
    const commits = deferCommitsByJob();
    const { view, roadsId, riversId } = await dropTwoAndReview();

    await act(async () => {
      screen.getByTestId('commit-all').click();
    });
    await act(async () => {
      commits['job-roads'].resolve({ job_id: 'job-roads', status: 'queued' });
      commits['job-rivers'].reject(new ApiError('Title already in use', 409));
    });
    expect(await screen.findByTestId(`entry-${riversId}`)).toHaveAttribute('data-status', 'commit-failed');
    expect(screen.getByTestId(`error-${riversId}`)).toHaveTextContent('Title already in use');
    expect(screen.getByTestId(`entry-${roadsId}`)).toHaveAttribute('data-status', 'tracking');
    expect(screen.queryByTestId('bulk-tracking-list')).not.toBeInTheDocument();

    view.unmount();
    render(<UploadForm />);
    expect(await screen.findByTestId(`entry-${riversId}`)).toHaveAttribute('data-status', 'commit-failed');
    expect(screen.getByTestId(`entry-${roadsId}`)).toHaveAttribute('data-status', 'tracking');

    mockCommitImport.mockResolvedValueOnce({ job_id: 'job-rivers', status: 'queued' });
    await act(async () => {
      screen.getByTestId(`commit-${riversId}`).click();
    });
    expect(await screen.findByTestId('tracked-job-rivers')).toBeInTheDocument();
    expect(screen.getByTestId('tracked-job-roads')).toBeInTheDocument();
  });

  test('Commit All refusals settled while unmounted keep their errors and the quota notice', async () => {
    const commits = deferCommitsByJob();
    const { view, roadsId, riversId } = await dropTwoAndReview();

    await act(async () => {
      screen.getByTestId('commit-all').click();
    });
    view.unmount();
    await act(async () => {
      commits['job-roads'].reject(new ApiError('Dataset quota exceeded: 10 of 10 datasets used', 422));
      commits['job-rivers'].reject(new Error('network down'));
    });

    render(<UploadForm />);
    expect(await screen.findByTestId(`error-${roadsId}`)).toHaveTextContent('upload.quotaShort');
    expect(screen.getByTestId(`error-${riversId}`)).toHaveTextContent('upload.bulkCommitFailed');
    expect(screen.getByTestId(`entry-${riversId}`)).toHaveAttribute('data-status', 'commit-failed');
    expect(screen.getByText('Dataset quota exceeded: 10 of 10 datasets used')).toBeInTheDocument();
  });

  test('Commit All as VRT still opens the VRT dialog when it settles while unmounted', async () => {
    const commits = deferCommitsByJob();
    const { view } = await dropTwoAndReview();

    await act(async () => {
      screen.getByTestId('commit-all-vrt').click();
    });
    view.unmount();
    await act(async () => {
      commits['job-roads'].resolve({ job_id: 'job-roads', status: 'queued' });
      commits['job-rivers'].resolve({ job_id: 'job-rivers', status: 'queued' });
    });

    render(<UploadForm />);
    expect(await screen.findByTestId('bulk-tracking-list')).toHaveAttribute('data-auto-open-vrt', 'true');
  });

  function fanOutResponse(layers: Array<{ name: string; queued: boolean; error?: string }>) {
    return {
      fan_out_id: 'job-multi',
      results: layers.map((l) => ({
        layer_name: l.name,
        new_job_id: l.queued ? `new-${l.name}` : null,
        dataset_id: null,
        status: l.queued ? 'queued' : 'failed',
        error: l.error ?? null,
      })),
    };
  }

  test('a fan-out that succeeds while unmounted tracks each layer on remount', async () => {
    const fanOut = deferred<unknown>();
    mockCommitFanOut.mockReturnValue(fanOut.promise);
    const { view, entryId } = await dropAndReview(MULTI_LAYER_PREVIEW);

    await act(async () => {
      screen.getByTestId(`ingest-all-${entryId}`).click();
    });
    view.unmount();
    await act(async () => {
      fanOut.resolve(fanOutResponse([{ name: 'layer_a', queued: true }, { name: 'layer_b', queued: true }]));
    });

    render(<UploadForm />);
    expect(await screen.findByTestId('tracked-new-layer_a')).toHaveAttribute('data-title', 'parcels: layer_a');
    expect(screen.getByTestId('tracked-new-layer_b')).toHaveAttribute('data-title', 'parcels: layer_b');
    expect(screen.queryByTestId('tracked-job-multi')).not.toBeInTheDocument();
    expect(mockCommitFanOut).toHaveBeenCalledTimes(1);
    expect(mockCommitImport).not.toHaveBeenCalled();
    expect(mockPreviewFile).toHaveBeenCalledTimes(1);
  });

  test('a fan-out row removed mid-commit does not bring its layers back when it settles', async () => {
    const fanOut = deferred<unknown>();
    mockCommitFanOut.mockReturnValue(fanOut.promise);
    mockUploadFile.mockImplementation((file: File) =>
      Promise.resolve({ job_id: `job-${file.name.split('.')[0]}`, status: 'pending' }),
    );
    mockPreviewFile.mockImplementation((jobId: string) =>
      Promise.resolve(jobId === 'job-roads' ? MULTI_LAYER_PREVIEW : { ...VECTOR_PREVIEW, job_id: jobId }),
    );
    const view = render(<UploadForm />);
    await act(async () => {
      screen.getByTestId('simulate-drop-two').click();
    });
    await waitFor(() => expect(screen.getAllByTestId(/^entry-/)).toHaveLength(2));
    const [roadsId, riversId] = screen
      .getAllByTestId(/^entry-/)
      .map((el) => el.getAttribute('data-testid')!.replace('entry-', ''));

    await act(async () => {
      screen.getByTestId(`ingest-all-${roadsId}`).click();
    });
    await act(async () => {
      screen.getByTestId(`remove-${roadsId}`).click();
    });
    view.unmount();
    await act(async () => {
      fanOut.resolve(fanOutResponse([{ name: 'layer_a', queued: true }, { name: 'layer_b', queued: true }]));
    });

    render(<UploadForm />);
    expect(await screen.findByTestId(`entry-${riversId}`)).toHaveAttribute('data-status', 'preview');
    expect(screen.getAllByTestId(/^entry-/)).toHaveLength(1);
    expect(screen.queryByText('upload.multiLayerResultsTitle')).not.toBeInTheDocument();
  });

  test('a partial fan-out settled while unmounted shows its per-layer results before tracking', async () => {
    const fanOut = deferred<unknown>();
    mockCommitFanOut.mockReturnValue(fanOut.promise);
    const { view, entryId } = await dropAndReview(MULTI_LAYER_PREVIEW);

    await act(async () => {
      screen.getByTestId(`ingest-all-${entryId}`).click();
    });
    view.unmount();
    await act(async () => {
      fanOut.resolve(
        fanOutResponse([
          { name: 'layer_a', queued: true },
          { name: 'layer_b', queued: false, error: 'Dispatch failed' },
        ]),
      );
    });

    const remount = render(<UploadForm />);
    expect(await screen.findByText('upload.multiLayerResultsTitle')).toBeInTheDocument();
    expect(screen.getByText('Dispatch failed')).toBeInTheDocument();
    expect(screen.getByTestId(`error-${entryId}`)).toHaveTextContent('upload.multiLayerPartialFailed');

    // Switching away with the results still open brings them back.
    remount.unmount();
    render(<UploadForm />);
    expect(await screen.findByText('Dispatch failed')).toBeInTheDocument();

    await act(async () => {
      screen.getByRole('button', { name: 'common:close' }).click();
    });
    expect(await screen.findByTestId('tracked-new-layer_a')).toBeInTheDocument();
    expect(mockCommitFanOut).toHaveBeenCalledTimes(1);
  });
});
