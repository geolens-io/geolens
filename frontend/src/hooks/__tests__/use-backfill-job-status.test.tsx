import { QueryClient } from '@tanstack/react-query';
import { waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { renderHook } from '@/test/test-utils';
import { getJobStatus } from '@/api/ingest';
import { useBackfillJobStatus } from '@/hooks/use-admin';
import { queryKeys } from '@/lib/query-keys';

// fix(#1550 review): since #1542 the backfill returns as soon as it is queued,
// so the coverage figure the panel shows is a pre-run number and stays one.
// Invalidating at enqueue — which is what the synchronous version did — now
// re-reads the same stale values and makes the panel look like it checked. The
// refresh has to happen where the run actually lands. An operator watching a
// number that never moves clicks Regenerate again, which the concurrency guard
// refuses, and the feature looks broken twice.

vi.mock('@/api/ingest', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/ingest')>();
  return { ...actual, getJobStatus: vi.fn() };
});

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}));

const mockGetJobStatus = vi.mocked(getJobStatus);

function jobStatus(status: string) {
  return {
    id: 'job-1',
    status,
    dataset_id: null,
    source_filename: 'embedding-backfill',
    error_message: null,
    can_retry: false,
    retry_reason: null,
    warnings: [],
  } as unknown as Awaited<ReturnType<typeof getJobStatus>>;
}

describe('useBackfillJobStatus (#1550 review)', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it('does not poll when no run has been queued', () => {
    renderHook(() => useBackfillJobStatus(null));
    expect(mockGetJobStatus).not.toHaveBeenCalled();
  });

  it('does not refresh coverage while the run is still going', async () => {
    const invalidateQueries = vi
      .spyOn(QueryClient.prototype, 'invalidateQueries')
      .mockResolvedValue(undefined);
    mockGetJobStatus.mockResolvedValue(jobStatus('running'));

    const { result } = renderHook(() => useBackfillJobStatus('job-1'));
    await waitFor(() => expect(result.current.data?.status).toBe('running'));

    // Non-vacuity: the hook really did read the job, so "no invalidation" is a
    // statement about the run being unfinished, not about nothing happening.
    expect(mockGetJobStatus).toHaveBeenCalledWith('job-1');
    expect(invalidateQueries).not.toHaveBeenCalledWith({
      queryKey: queryKeys.admin.embeddingStats,
    });
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('refreshes coverage exactly once when the run lands', async () => {
    const invalidateQueries = vi
      .spyOn(QueryClient.prototype, 'invalidateQueries')
      .mockResolvedValue(undefined);
    mockGetJobStatus.mockResolvedValue(jobStatus('complete'));

    const { result } = renderHook(() => useBackfillJobStatus('job-1'));
    await waitFor(() => expect(result.current.data?.status).toBe('complete'));

    await waitFor(() =>
      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: queryKeys.admin.embeddingStats,
      }),
    );
    expect(toast.success).toHaveBeenCalledWith('Embedding backfill finished');

    // A re-read of a job that is already terminal must not re-announce it.
    await result.current.refetch();
    const refreshes = invalidateQueries.mock.calls.filter(
      ([arg]) =>
        JSON.stringify((arg as { queryKey: unknown }).queryKey) ===
        JSON.stringify(queryKeys.admin.embeddingStats),
    );
    expect(refreshes).toHaveLength(1);
    expect(toast.success).toHaveBeenCalledTimes(1);
  });

  it('polls a live run and stops once it is terminal', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockGetJobStatus.mockResolvedValue(jobStatus('running'));
      const { result } = renderHook(() => useBackfillJobStatus('job-1'));
      await waitFor(() => expect(result.current.data?.status).toBe('running'));

      // Non-vacuity for the half below: a live run really is polled, so
      // "no further calls" afterwards is the timer stopping rather than one
      // that was never started.
      const whileRunning = mockGetJobStatus.mock.calls.length;
      await vi.advanceTimersByTimeAsync(13_000);
      expect(mockGetJobStatus.mock.calls.length).toBeGreaterThan(whileRunning);

      mockGetJobStatus.mockResolvedValue(jobStatus('complete'));
      await vi.advanceTimersByTimeAsync(5_000);
      await waitFor(() => expect(result.current.data?.status).toBe('complete'));

      const whenDone = mockGetJobStatus.mock.calls.length;
      await vi.advanceTimersByTimeAsync(13_000);
      expect(mockGetJobStatus.mock.calls.length).toBe(whenDone);
    } finally {
      vi.useRealTimers();
    }
  });

  it('says so when the run failed rather than claiming it finished', async () => {
    mockGetJobStatus.mockResolvedValue(jobStatus('failed'));
    const { result } = renderHook(() => useBackfillJobStatus('job-1'));
    await waitFor(() => expect(result.current.data?.status).toBe('failed'));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        'The embedding backfill run failed — check the server logs',
      ),
    );
    expect(toast.success).not.toHaveBeenCalled();
  });
});
