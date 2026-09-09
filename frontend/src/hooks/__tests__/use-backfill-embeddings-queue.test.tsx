import { toast } from 'sonner';
import { renderHook, waitFor } from '@/test/test-utils';
import { ApiError } from '@/api/client';
import { triggerBackfill } from '@/api/admin';
import { useBackfillEmbeddings, useEmbeddingStats } from '@/hooks/use-admin';
import { getEmbeddingStats } from '@/api/admin';
import type { EmbeddingStatsResponse } from '@/types/api';

// fix(#1542): the backfill runs on the job queue now. Two consequences reach
// this hook: the response is an acknowledgement with a job id rather than a
// result with counts, and a run already in flight comes back as 409 — a
// refusal, not a failure. Reporting the refusal as "Embedding backfill failed"
// would tell the operator their catalog is broken at the one moment the safe
// thing just happened, and the natural response to that message is the retry
// the guard exists to stop.

vi.mock('@/api/admin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/admin')>();
  return { ...actual, triggerBackfill: vi.fn(), getEmbeddingStats: vi.fn() };
});

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}));

const mockTriggerBackfill = vi.mocked(triggerBackfill);
const mockGetEmbeddingStats = vi.mocked(getEmbeddingStats);

const STATS: EmbeddingStatsResponse = {
  total_records: 10,
  embedded_records: 5,
  missing_records: 5,
  stale_records: 0,
  coverage_percent: 50,
  current_run: null,
  recent_runs: [],
  estimate: null,
};

describe('useBackfillEmbeddings (#1542)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('resolves with the queued job id instead of run counts', async () => {
    mockTriggerBackfill.mockResolvedValueOnce({
      job_id: '5f1e5b2a-0000-4000-8000-000000000001',
      status: 'pending',
    });
    const { result } = renderHook(() => useBackfillEmbeddings());

    const data = await result.current.mutateAsync(true);

    expect(mockTriggerBackfill).toHaveBeenCalledWith(true);
    expect(data.job_id).toBe('5f1e5b2a-0000-4000-8000-000000000001');
    expect(data.status).toBe('pending');
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('reports a run already in flight as a refusal, not a failure', async () => {
    mockTriggerBackfill.mockRejectedValueOnce(
      new ApiError('An embedding backfill is already running', 409),
    );
    const { result } = renderHook(() => useBackfillEmbeddings());

    await expect(result.current.mutateAsync(true)).rejects.toThrow();

    expect(toast.warning).toHaveBeenCalledWith(
      'An embedding backfill is already running — wait for it to finish',
    );
    expect(toast.error).not.toHaveBeenCalled();
  });

  // fix(#2025): the enqueue response proves a run exists, and the stats
  // endpoint is where its progress is read. Without this refetch the operator
  // who queued the run waited out the 30s staleTime before the bar appeared.
  it('refetches the coverage stats so the queued run starts reporting progress', async () => {
    mockGetEmbeddingStats.mockResolvedValue(STATS);
    mockTriggerBackfill.mockResolvedValueOnce({
      job_id: '5f1e5b2a-0000-4000-8000-000000000002',
      status: 'pending',
    });
    const { result } = renderHook(() => ({
      backfill: useBackfillEmbeddings(),
      stats: useEmbeddingStats({ enabled: true }),
    }));
    await waitFor(() => expect(mockGetEmbeddingStats).toHaveBeenCalledTimes(1));

    await result.current.backfill.mutateAsync(false);

    await waitFor(() => expect(mockGetEmbeddingStats).toHaveBeenCalledTimes(2));
  });

  it('still reports a genuine failure as a failure', async () => {
    mockTriggerBackfill.mockRejectedValueOnce(new ApiError('Service unavailable', 503));
    const { result } = renderHook(() => useBackfillEmbeddings());

    await expect(result.current.mutateAsync(false)).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith('Embedding backfill failed');
    expect(toast.warning).not.toHaveBeenCalled();
  });
});
