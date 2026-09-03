// fix(#1805 review round 4 P2): useQueries silently dropped a failed page --
// isError was never surfaced and hasMore stayed true, so a broken page just
// looked unloaded. useApiKeys now surfaces the first failed page (in page
// order) and a retryFailedPage() scoped to that one query.
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';
import { useApiKeys } from '@/hooks/use-admin';
import type { ApiKeyResponse } from '@/types/api';

const mockListApiKeys = vi.fn();
vi.mock('@/api/admin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/admin')>();
  return { ...actual, listApiKeys: (...args: unknown[]) => mockListApiKeys(...args) };
});

function makeKey(name: string): ApiKeyResponse {
  return {
    id: name,
    user_id: 'u1',
    name,
    fingerprint: null,
    is_active: true,
    expires_at: null,
    scope: 'full',
    created_at: '2026-08-01T00:00:00Z',
    last_used_at: null,
  };
}

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
}

describe('useApiKeys page-load error handling (#1805 review round 4 P2)', () => {
  beforeEach(() => {
    mockListApiKeys.mockReset();
  });

  it('surfaces the failed page and retries only that page, not the succeeding one', async () => {
    mockListApiKeys.mockImplementation((_userId: string, options: { skip: number }) => {
      if (options.skip === 0) {
        return Promise.resolve({ items: [makeKey('key-1')], total: 60 });
      }
      // Page 2 (skip=50) fails.
      return Promise.reject(new Error('page 2 failed'));
    });

    const { result } = renderHook(() => useApiKeys('u1', 2), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeInstanceOf(Error);
    expect((result.current.error as Error).message).toBe('page 2 failed');
    // Page 1's data still made it through -- a failed later page must not
    // wipe out an earlier page's already-loaded items.
    expect(result.current.items.map((k) => k.name)).toEqual(['key-1']);
    // Page 1's call, plus page 2's initial call.
    expect(mockListApiKeys).toHaveBeenCalledTimes(2);

    mockListApiKeys.mockClear();
    result.current.retryFailedPage();

    await waitFor(() => expect(mockListApiKeys).toHaveBeenCalledTimes(1));
    // Only page 2 (skip=50) was retried -- page 1 (skip=0) was not refetched.
    expect(mockListApiKeys).toHaveBeenCalledWith('u1', { skip: 50, limit: 50 });
  });

  it('does not report an error when every loaded page succeeds', async () => {
    mockListApiKeys.mockResolvedValue({ items: [makeKey('key-1')], total: 1 });

    const { result } = renderHook(() => useApiKeys('u1', 1), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.isError).toBe(false);
    expect(result.current.error).toBeNull();
  });
});
