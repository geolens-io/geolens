import { useQueryClient } from '@tanstack/react-query';
import { act, renderHook } from '@/test/test-utils';
import { getJobStatus } from '@/api/ingest';
import { useRefreshSearchWhenQuicklookLands } from '@/components/dataset/hooks/use-quicklook-settled';
import { ApiError } from '@/api/client';
import { queryKeys } from '@/lib/query-keys';

vi.mock('@/api/ingest', () => ({ getJobStatus: vi.fn() }));
vi.mock('@/components/import/hooks/use-ingest', async (importOriginal) => ({
  isDefinitiveJobError: (await importOriginal<typeof import('@/components/import/hooks/use-ingest')>()).isDefinitiveJobError,
}));

const mockGetJobStatus = vi.mocked(getJobStatus);

function status(quicklookPending: boolean) {
  return { id: 'job-1', status: 'complete', quicklook_pending: quicklookPending } as Awaited<
    ReturnType<typeof getJobStatus>
  >;
}

function renderWatch(jobId: string | null) {
  return renderHook(() => {
    useRefreshSearchWhenQuicklookLands(jobId);
    return useQueryClient();
  });
}

describe('useRefreshSearchWhenQuicklookLands', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockGetJobStatus.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('refreshes search results only once the quicklook is no longer pending', async () => {
    mockGetJobStatus
      .mockResolvedValueOnce(status(true))
      .mockResolvedValueOnce(status(false));
    const { result } = renderWatch('job-1');
    const invalidate = vi.spyOn(result.current, 'invalidateQueries');

    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(invalidate).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.search.all });
    expect(mockGetJobStatus).toHaveBeenCalledTimes(2);
  });

  it('does not poll without a job', async () => {
    renderWatch(null);

    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(mockGetJobStatus).not.toHaveBeenCalled();
  });

  it('stops watching after a bounded number of polls', async () => {
    mockGetJobStatus.mockResolvedValue(status(true));
    renderWatch('job-1');

    await act(() => vi.advanceTimersByTimeAsync(10 * 60 * 1000));

    expect(mockGetJobStatus).toHaveBeenCalledTimes(30);
  });

  it('keeps polling through a transient read failure', async () => {
    mockGetJobStatus
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(status(false));
    const { result } = renderWatch('job-1');
    const invalidate = vi.spyOn(result.current, 'invalidateQueries');

    await act(() => vi.advanceTimersByTimeAsync(4000));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.search.all });
  });

  it('stops on a read that can never succeed', async () => {
    mockGetJobStatus.mockRejectedValue(new ApiError('gone', 404));
    renderWatch('job-1');

    await act(() => vi.advanceTimersByTimeAsync(60_000));

    expect(mockGetJobStatus).toHaveBeenCalledTimes(1);
  });
});
