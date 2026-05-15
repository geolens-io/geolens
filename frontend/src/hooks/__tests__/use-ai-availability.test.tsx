import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { vi } from 'vitest';
import type { ReactNode } from 'react';

vi.mock('@/api/admin', () => ({
  getAIStatus: vi.fn(),
}));

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: () => true }),
}));

import { getAIStatus } from '@/api/admin';
import { useAIStatus } from '@/hooks/use-admin';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { useAuthStore } from '@/stores/auth-store';

const mockGetAIStatus = vi.mocked(getAIStatus);

function makeWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe('useAIStatus / useAIAvailability — caching (SP-08)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      token: 'test-token',
      refreshToken: null,
      expiresAt: null,
      user: null,
    });
    mockGetAIStatus.mockResolvedValue({
      enabled: true,
      configured: true,
      provider: 'openai',
      model: 'gpt-4',
    } as never);
  });

  it('shares a single in-flight query across multiple consumers (queryKey-deduped)', async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 5 * 60_000 } },
    });
    const wrapper = makeWrapper(qc);

    // Mount three independent consumers of the underlying hook
    const a = renderHook(() => useAIStatus({ enabled: true }), { wrapper });
    const b = renderHook(() => useAIAvailability(), { wrapper });
    const c = renderHook(() => useAIAvailability(), { wrapper });

    await waitFor(() => {
      expect(a.result.current.data).toBeDefined();
      expect(b.result.current.data).toBeDefined();
      expect(c.result.current.data).toBeDefined();
    });

    // Despite 3 consumers, only one network call
    expect(mockGetAIStatus).toHaveBeenCalledTimes(1);
  });

  it('does not refetch within 60s staleTime when a new consumer mounts', async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 5 * 60_000 } },
    });
    const wrapper = makeWrapper(qc);

    const first = renderHook(() => useAIAvailability(), { wrapper });
    await waitFor(() => expect(first.result.current.data).toBeDefined());
    expect(mockGetAIStatus).toHaveBeenCalledTimes(1);

    // Mount a second consumer immediately — within staleTime → no refetch
    const second = renderHook(() => useAIAvailability(), { wrapper });
    await waitFor(() => expect(second.result.current.data).toBeDefined());

    expect(mockGetAIStatus).toHaveBeenCalledTimes(1);
  });

  it('does NOT poll on a refetchInterval (no idle network storm)', async () => {
    vi.useFakeTimers();
    try {
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 5 * 60_000 } },
      });
      const wrapper = makeWrapper(qc);

      const view = renderHook(() => useAIAvailability(), { wrapper });

      // Advance well past the old 60s refetchInterval to ensure no auto-poll
      await vi.advanceTimersByTimeAsync(180_000);

      // The first mount triggers exactly one call; no further polling
      expect(mockGetAIStatus).toHaveBeenCalledTimes(1);
      view.unmount();
    } finally {
      vi.useRealTimers();
    }
  });
});
