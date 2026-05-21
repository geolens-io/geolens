import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import { useRef } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';

vi.mock('@/api/ingest', () => ({
  uploadFile: vi.fn(),
  getJobStatus: vi.fn(),
  previewFile: vi.fn(),
  commitImport: vi.fn(),
  retryJob: vi.fn(),
  probeService: vi.fn(),
  previewServiceLayer: vi.fn(),
  discoverTables: vi.fn(),
  bulkRegisterTables: vi.fn(),
  getUploadConfig: vi.fn(),
  createVrt: vi.fn(),
}));

import { uploadFile, getJobStatus, discoverTables, getUploadConfig, createVrt } from '@/api/ingest';
import {
  useUploadFile,
  useJobStatus,
  useDiscoverTables,
  useUploadConfig,
  useCreateVrt,
} from '@/components/import/hooks/use-ingest';
import { queryKeys } from '@/lib/query-keys';

const mockUploadFile = vi.mocked(uploadFile);
const mockGetJobStatus = vi.mocked(getJobStatus);
const mockDiscoverTables = vi.mocked(discoverTables);
const mockGetUploadConfig = vi.mocked(getUploadConfig);
const mockCreateVrt = vi.mocked(createVrt);

/** Capture the QueryClient from the renderHook wrapper. */
function renderWithClient<T>(factory: () => T): { result: { current: T }; qc: QueryClient } {
  let captured: QueryClient | null = null;
  const { result } = renderHook(() => {
    const qc = useQueryClient();
    const ref = useRef<QueryClient | null>(null);
    if (ref.current === null) ref.current = qc;
    captured = ref.current;
    return factory();
  });
  if (!captured) throw new Error('QueryClient capture failed');
  return { result, qc: captured as QueryClient };
}

describe('useUploadFile', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls uploadFile on mutate', async () => {
    const response = { job_id: 'j-1', filename: 'test.geojson' };
    mockUploadFile.mockResolvedValueOnce(response as never);

    const { result } = renderHook(() => useUploadFile());

    const file = new File(['{}'], 'test.geojson', { type: 'application/json' });
    await result.current.mutateAsync(file);

    expect(mockUploadFile).toHaveBeenCalledWith(file, expect.anything());
  });

  it('returns error state on upload failure', async () => {
    mockUploadFile.mockRejectedValueOnce(new Error('Too large'));

    const { result } = renderHook(() => useUploadFile());

    const file = new File(['{}'], 'test.geojson');
    await expect(result.current.mutateAsync(file)).rejects.toThrow('Too large');
  });
});

describe('useJobStatus', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches job status when jobId is provided', async () => {
    const status = { job_id: 'j-1', status: 'complete', filename: 'test.geojson' };
    mockGetJobStatus.mockResolvedValueOnce(status as never);

    const { result } = renderHook(() => useJobStatus('j-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(status);
  });

  it('does not fetch when jobId is null', () => {
    const { result } = renderHook(() => useJobStatus(null));

    expect(result.current.fetchStatus).toBe('idle');
    expect(mockGetJobStatus).not.toHaveBeenCalled();
  });

  it('returns error state on failure', async () => {
    mockGetJobStatus.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useJobStatus('bad-id'));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useDiscoverTables', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches discovered tables', async () => {
    const data = { tables: [{ schema: 'public', table: 'my_table' }] };
    mockDiscoverTables.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useDiscoverTables());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
  });

  it('returns error state on failure', async () => {
    mockDiscoverTables.mockRejectedValueOnce(new Error('DB error'));

    const { result } = renderHook(() => useDiscoverTables());

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useUploadConfig', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches upload config', async () => {
    const data = { max_file_size: 500_000_000, storage_backend: 'local' };
    mockGetUploadConfig.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useUploadConfig());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
  });
});

/**
 * REMED-01 (ingest-audit P2-06): useCreateVrt must invalidate the
 * jobStatus cache on success so any UI subscribed to the new job's
 * progress refetches immediately. VrtCreateResponse carries only
 * `job_id` (no `dataset_id`), so we invalidate jobStatus(job_id).
 */
describe('useCreateVrt', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls createVrt on mutate', async () => {
    const response = { job_id: 'j-vrt-1', status: 'queued', message: 'ok' };
    mockCreateVrt.mockResolvedValueOnce(response as never);

    const { result } = renderHook(() => useCreateVrt());

    const request = {
      source_dataset_ids: ['ds-a', 'ds-b'],
      vrt_type: 'mosaic' as const,
      resolution_strategy: 'finest' as const,
      title: 'My VRT',
    };
    await result.current.mutateAsync(request);

    expect(mockCreateVrt).toHaveBeenCalledWith(request);
  });

  it('invalidates jobStatus(job_id) on success', async () => {
    const response = { job_id: 'j-vrt-1', status: 'queued', message: 'ok' };
    mockCreateVrt.mockResolvedValueOnce(response as never);
    const { result, qc } = renderWithClient(() => useCreateVrt());
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await result.current.mutateAsync({
      source_dataset_ids: ['ds-a'],
      vrt_type: 'mosaic',
      resolution_strategy: 'finest',
      title: 'My VRT',
    });

    // VrtCreateResponse exposes job_id (no dataset_id) — invalidate the
    // job-status cache for the new VRT job.
    expect(spy).toHaveBeenCalledWith({
      queryKey: queryKeys.ingest.jobStatus('j-vrt-1'),
    });
  });
});
