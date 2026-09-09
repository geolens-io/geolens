// fix(#2033): useAdminJobs had no refetchInterval, so a retried job kept
// showing its pre-retry status until the page was reloaded.
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';
import { useAdminJobs } from '@/hooks/use-admin';
import type { AdminJobListResponse } from '@/types/api';

const mockListAdminJobs = vi.fn();
vi.mock('@/api/admin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/admin')>();
  return { ...actual, listAdminJobs: (...args: unknown[]) => mockListAdminJobs(...args) };
});

function makeJob(status: string): AdminJobListResponse['jobs'][number] {
  return {
    id: 'job-1',
    status,
    source_filename: 'a.gpkg',
    dataset_id: null,
    error_message: null,
    can_retry: status === 'failed',
    retry_reason: null,
    user_metadata: null,
    created_by: null,
    username: null,
    started_at: null,
    completed_at: null,
    created_at: '2026-09-09T00:00:00Z',
  };
}

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
}

describe('useAdminJobs polling (#2033)', () => {
  beforeEach(() => {
    mockListAdminJobs.mockReset();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('keeps polling a non-terminal row and picks up its settled status without a manual refetch', async () => {
    mockListAdminJobs
      .mockResolvedValueOnce({ jobs: [makeJob('running')], total: 1 })
      .mockResolvedValueOnce({ jobs: [makeJob('complete')], total: 1 });

    const { result } = renderHook(() => useAdminJobs({}), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.data?.jobs[0].status).toBe('running'));
    expect(mockListAdminJobs).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(3_000);

    await waitFor(() => expect(result.current.data?.jobs[0].status).toBe('complete'));
    expect(mockListAdminJobs).toHaveBeenCalledTimes(2);
  });

  it('stops polling once every row is terminal', async () => {
    mockListAdminJobs.mockResolvedValue({ jobs: [makeJob('complete')], total: 1 });

    const { result } = renderHook(() => useAdminJobs({}), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.data?.jobs[0].status).toBe('complete'));
    expect(mockListAdminJobs).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(10_000);

    // No further fetches — nothing left to watch.
    expect(mockListAdminJobs).toHaveBeenCalledTimes(1);
  });
});
