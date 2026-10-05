import {
  clearUploadBatch,
  commitUploadEntry,
  commitUploadEntries,
  commitUploadFanOut,
  dismissUploadFanOutResults,
  removeUploadSessionEntry,
  peekUploadBatch,
  startLayerPreview,
  startUploadEntry,
} from '@/api/upload-session';
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

const SUBMISSION = { title: 'Roads', visibility: 'private', kind: 'vector' as const };
const initialAuthState = useAuthStore.getState();

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function startReviewedEntry(id: string, jobId: string) {
  mockUploadFile.mockResolvedValueOnce({ job_id: jobId, status: 'pending' });
  mockPreviewFile.mockResolvedValueOnce({ job_id: jobId, layer_name: 'a', layers: [], geometry_type: 'LineString' });
  startUploadEntry(id, new File(['{}'], `${id}.geojson`), false);
  await vi.waitFor(() =>
    expect(peekUploadBatch()?.entries.find((e) => e.id === id)?.status).toBe('preview'),
  );
}

function statusOf(id: string) {
  return peekUploadBatch()?.entries.find((e) => e.id === id)?.status;
}

beforeEach(() => {
  vi.clearAllMocks();
  clearUploadBatch();
  useAuthStore.setState(initialAuthState, true);
});

async function startMultiLayerEntry() {
  mockUploadFile.mockResolvedValueOnce({ job_id: 'job-multi' });
  mockPreviewFile.mockResolvedValueOnce({
    job_id: 'job-multi', source_filename: 'survey.gpkg', layer_name: 'roads',
    layers: [{ name: 'roads' }, { name: 'stations' }], geometry_type: null,
  });
  startUploadEntry('multi', new File([''], 'uploaded.gpkg'), false);
  await vi.waitFor(() => expect(statusOf('multi')).toBe('preview'));
}

describe('upload commit policy', () => {
  test('reviewed metadata uses the current layer and tracks metadata-derived geometry', async () => {
    await startMultiLayerEntry();
    mockPreviewFile.mockResolvedValueOnce({
      job_id: 'job-multi', source_filename: 'survey.gpkg', layer_name: 'stations',
      layers: [{ name: 'roads' }, { name: 'stations' }], geometry_type: null,
    });
    startLayerPreview('multi', 'job-multi', 'stations');
    await vi.waitFor(() => expect(statusOf('multi')).toBe('preview'));
    mockCommitImport.mockResolvedValueOnce({});
    await commitUploadEntry('multi', { title: 'Edited survey', visibility: 'public', x_column: 'lon', y_column: 'lat', layer_name: 'roads' });
    expect(mockCommitImport).toHaveBeenCalledWith('job-multi', expect.objectContaining({ layer_name: 'stations' }));
    expect(peekUploadBatch()?.entries[0].submitted).toEqual({ title: 'Edited survey', visibility: 'public', kind: 'vector' });
    expect(peekUploadBatch()?.canTrack).toBe(true);
  });

  test('batch defaults use preview filenames and selected layers and skip refused requests', async () => {
    await startMultiLayerEntry();
    await startReviewedEntry('e2', 'job-2');
    mockCommitImport.mockRejectedValueOnce(new ApiError('Refused', 409));
    await commitUploadEntry('e2', { title: 'Edited title', visibility: 'public', summary: 'Edited summary' });
    mockCommitImport.mockResolvedValueOnce({});
    await commitUploadEntries({ autoOpenVrt: true });
    expect(mockCommitImport).toHaveBeenCalledTimes(2);
    expect(mockCommitImport).toHaveBeenLastCalledWith('job-multi', { title: 'survey', layer_name: 'roads' });
    expect(peekUploadBatch()?.entries.find((e) => e.id === 'multi')?.submitted).toEqual({ title: 'survey', visibility: 'private', kind: 'table' });
    expect(peekUploadBatch()?.entries.find((e) => e.id === 'e2')?.request?.title).toBe('Edited title');
    expect(peekUploadBatch()).toMatchObject({ autoOpenVrt: true, canTrack: false });
    mockCommitImport.mockResolvedValueOnce({});
    await commitUploadEntry('e2', { title: 'Retry title' });
    expect(peekUploadBatch()?.canTrack).toBe(true);
  });

  test('batch defaults send the geometry columns the preview detected', async () => {
    mockUploadFile.mockResolvedValueOnce({ job_id: 'job-csv' });
    mockPreviewFile.mockResolvedValueOnce({
      job_id: 'job-csv', source_filename: 'places.csv', layer_name: 'places', layers: [],
      geometry_type: null, detected_geometry_columns: { x_column: 'lon', y_column: 'lat', wkt_column: null },
    });
    startUploadEntry('csv', new File([''], 'places.csv'), false);
    await vi.waitFor(() => expect(statusOf('csv')).toBe('preview'));
    mockCommitImport.mockResolvedValueOnce({});
    await commitUploadEntries();
    expect(mockCommitImport).toHaveBeenCalledWith('job-csv', { title: 'places', x_column: 'lon', y_column: 'lat' });
    expect(peekUploadBatch()?.entries.find((e) => e.id === 'csv')?.submitted?.kind).toBe('vector');
  });

  test('partial fan-out derives requests and tracking kind and waits for results acknowledgement', async () => {
    await startMultiLayerEntry();
    mockCommitFanOut.mockResolvedValueOnce({ results: [
      { layer_name: 'roads', status: 'queued', new_job_id: 'child-1', error: null },
      { layer_name: 'stations', status: 'failed', new_job_id: null, error: 'Refused' },
    ] });
    await commitUploadFanOut('multi');
    expect(mockCommitFanOut).toHaveBeenCalledWith('job-multi', [
      { layer_name: 'roads', title: 'survey: roads' },
      { layer_name: 'stations', title: 'survey: stations' },
    ]);
    expect(peekUploadBatch()).toMatchObject({ canTrack: false });
    expect(peekUploadBatch()?.entries.find((e) => e.jobId === 'child-1')?.submitted).toEqual({ title: 'survey: roads', visibility: 'private', kind: 'table' });
    dismissUploadFanOutResults();
    expect(peekUploadBatch()?.canTrack).toBe(true);
  });

  test('all-failed fan-out remains reviewable after results are dismissed', async () => {
    await startMultiLayerEntry();
    mockCommitFanOut.mockRejectedValueOnce(new ApiError('Unavailable', 503));
    await commitUploadFanOut('multi');
    dismissUploadFanOutResults();
    expect(peekUploadBatch()).toMatchObject({ canTrack: false });
    mockCommitImport.mockResolvedValueOnce({});
    await expect(commitUploadEntry('multi', { title: 'Retry' })).resolves.toBe(true);
    expect(peekUploadBatch()?.canTrack).toBe(true);
  });

  test.each(['remove', 'reset'] as const)('%s drops a late commit settlement', async (action) => {
    await startReviewedEntry('e1', 'job-1');
    const commit = deferred<unknown>();
    mockCommitImport.mockReturnValueOnce(commit.promise);
    const settled = commitUploadEntry('e1', { title: 'Roads' });
    if (action === 'remove') removeUploadSessionEntry('e1');
    else clearUploadBatch();
    commit.resolve({});
    await expect(settled).resolves.toBe(false);
    expect(peekUploadBatch()).toBeNull();
  });
});

afterEach(() => {
  clearUploadBatch();
  useAuthStore.setState(initialAuthState, true);
});

describe('upload session commit settlement', () => {
  test('an entry whose commit was issued is never committed again or re-previewed', async () => {
    await startReviewedEntry('e1', 'job-1');
    const commit = deferred<unknown>();
    mockCommitImport.mockReturnValueOnce(commit.promise);

    const first = commitUploadEntry('e1', { title: 'Roads' });
    expect(statusOf('e1')).toBe('committing');
    await expect(commitUploadEntry('e1', { title: 'Roads' })).resolves.toBe(false);
    startLayerPreview('e1', 'job-1', 'b');

    commit.resolve({});
    await expect(first).resolves.toBe(true);
    expect(statusOf('e1')).toBe('committed');
    expect(peekUploadBatch()?.entries[0].submitted).toEqual(SUBMISSION);

    await expect(commitUploadEntry('e1', { title: 'Roads' })).resolves.toBe(false);
    startLayerPreview('e1', 'job-1', 'b');
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
    expect(mockPreviewFile).toHaveBeenCalledTimes(1);
  });

  test('a refused commit keeps its error and can be retried', async () => {
    await startReviewedEntry('e1', 'job-1');
    const refusal = new ApiError('Title already in use', 409);
    mockCommitImport.mockRejectedValueOnce(refusal).mockResolvedValueOnce({});

    await expect(commitUploadEntry('e1', { title: 'Roads' })).resolves.toBe(false);
    expect(statusOf('e1')).toBe('commit-failed');
    expect(peekUploadBatch()?.entries[0].error).toBe(refusal);

    await expect(commitUploadEntry('e1', { title: 'Roads 2' })).resolves.toBe(true);
    expect(statusOf('e1')).toBe('committed');
    expect(mockCommitImport).toHaveBeenLastCalledWith('job-1', { title: 'Roads 2' });
  });

  test("a commit that settles after another identity's batch started is dropped", async () => {
    useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
    await startReviewedEntry('e1', 'job-1');
    const commit = deferred<unknown>();
    mockCommitImport.mockReturnValueOnce(commit.promise);
    const settled = commitUploadEntry('e1', { title: 'Roads' });

    useAuthStore.setState({ token: 't2', user: { id: 'user-2' } as UserResponse });
    await startReviewedEntry('e2', 'job-2');

    commit.resolve({});
    await expect(settled).resolves.toBe(false);
    expect(peekUploadBatch()?.entries.map((e) => [e.id, e.status])).toEqual([['e2', 'preview']]);
  });
});
