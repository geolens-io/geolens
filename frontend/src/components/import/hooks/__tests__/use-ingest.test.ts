import { act, renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import { useRef } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';

vi.mock('@/api/ingest', () => ({
  uploadFile: vi.fn(),
  getJobStatus: vi.fn(),
  getJobStatusByDataset: vi.fn(),
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

import { uploadFile, getJobStatus, getJobStatusByDataset, discoverTables, getUploadConfig, createVrt } from '@/api/ingest';
import {
  useUploadFile,
  useJobStatus,
  useDatasetJobStatus,
  useDiscoverTables,
  useUploadConfig,
  useCreateVrt,
  isTerminalJobStatus,
} from '@/components/import/hooks/use-ingest';
import { queryKeys } from '@/lib/query-keys';
import { useAuthStore } from '@/stores/auth-store';
import { ApiError } from '@/api/client';

const mockUploadFile = vi.mocked(uploadFile);
const mockGetJobStatus = vi.mocked(getJobStatus);
const mockGetJobStatusByDataset = vi.mocked(getJobStatusByDataset);
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

    // Hook wraps uploadFile so TanStack's injected context isn't passed as
    // the (onProgress) 2nd arg — uploadFile receives the file only.
    expect(mockUploadFile).toHaveBeenCalledWith(file);
  });

  it('returns error state on upload failure', async () => {
    mockUploadFile.mockRejectedValueOnce(new Error('Too large'));

    const { result } = renderHook(() => useUploadFile());

    const file = new File(['{}'], 'test.geojson');
    await expect(result.current.mutateAsync(file)).rejects.toThrow('Too large');
  });
});

describe('useJobStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // fix(#762): the hook now gates on an auth token; these tests run as an
    // authenticated user unless they say otherwise.
    useAuthStore.setState({ token: 'jwt-token', refreshToken: null, expiresAt: null, user: null });
  });

  it('does not poll a persisted analysis job for anonymous visitors (fix #762)', () => {
    // AnalysisJobWatcher mounts in RootLayout with a persist-backed job id; a
    // stale one used to make an anonymous session fire an authenticated-only
    // poll whose 401 logged the visitor out of public pages.
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
    const { result } = renderHook(() => useJobStatus('j-stale'));

    expect(result.current.fetchStatus).toBe('idle');
    expect(mockGetJobStatus).not.toHaveBeenCalled();
  });

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

  /**
   * fix(#1556): the poll's terminal check is a DENYLIST, so a terminal status
   * missing from it does not merely mis-render — it polls /jobs/{id} every 2s
   * for the life of the tab. An abandoned presigned upload now settles
   * 'cancelled', which was the missing one.
   */
  it('stops polling once a job settles cancelled', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockGetJobStatus.mockResolvedValue({ job_id: 'j-c', status: 'cancelled' } as never);

      const { result } = renderHook(() => useJobStatus('j-c'));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.isSuccess).toBe(true);
      expect(mockGetJobStatus).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(mockGetJobStatus).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps polling a job that is still running', async () => {
    // The control for the test above: without it, a hook that never polls at
    // all would satisfy the cancelled case for the wrong reason.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockGetJobStatus.mockResolvedValue({ job_id: 'j-r', status: 'running' } as never);

      renderHook(() => useJobStatus('j-r'));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(mockGetJobStatus).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(mockGetJobStatus.mock.calls.length).toBeGreaterThan(1);
    } finally {
      vi.useRealTimers();
    }
  });

  /**
   * fix(#1778): before this, refetchInterval only checked
   * query.state.data?.status, so a query stuck in isError (data stays
   * undefined) polled /jobs/{id} every 2s for the life of the tab.
   */
  it('stops polling once the status read settles a definitive 404', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockGetJobStatus.mockRejectedValue(new ApiError('Job not found', 404));

      const { result } = renderHook(() => useJobStatus('j-gone'));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.isError).toBe(true);
      expect(mockGetJobStatus).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(mockGetJobStatus).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('isTerminalJobStatus', () => {
  // Enumerated over the whole JobStatusResponse status enum rather than the
  // one status that was reported, because the failure mode is "a status is
  // missing from the denylist" and only enumeration can see that.
  it.each(['complete', 'failed', 'fanned_out', 'cancelled'])(
    'treats %s as terminal',
    (status) => {
      expect(isTerminalJobStatus(status)).toBe(true);
    },
  );

  it.each(['pending', 'running'])('keeps %s pollable', (status) => {
    expect(isTerminalJobStatus(status)).toBe(false);
  });

  it('treats an absent status as pollable', () => {
    expect(isTerminalJobStatus(undefined)).toBe(false);
  });
});

describe('useDatasetJobStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
  });

  it('does not fetch protected ingest-job metadata for anonymous dataset viewers', () => {
    const { result } = renderHook(() => useDatasetJobStatus('ds-1'));

    expect(result.current.fetchStatus).toBe('idle');
    expect(mockGetJobStatusByDataset).not.toHaveBeenCalled();
  });

  it('fetches dataset job metadata when authenticated', async () => {
    const status = { job_id: 'j-1', status: 'complete', filename: 'test.geojson' };
    mockGetJobStatusByDataset.mockResolvedValueOnce(status as never);
    useAuthStore.setState({ token: 'jwt-token', refreshToken: null, expiresAt: null, user: null });

    const { result } = renderHook(() => useDatasetJobStatus('ds-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockGetJobStatusByDataset).toHaveBeenCalledWith('ds-1');
    expect(result.current.data).toEqual(status);
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
