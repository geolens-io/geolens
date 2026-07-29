import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getTileTokensBatch } from '@/api/tiles';
import { useViewerTokens } from '@/components/viewer/hooks/use-viewer-tokens';
import type { SharedLayerResponse } from '@/types/api';

vi.mock('@/api/tiles', () => ({
  getTileTokensBatch: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockedGetTileTokensBatch = vi.mocked(getTileTokensBatch);

const layers = [{ dataset_id: 'dataset-1' }] as unknown as SharedLayerResponse[];

/** Flush pending microtasks (promise rejections) without advancing timers. */
async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe('useViewerTokens retry scheduling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockedGetTileTokensBatch.mockReset();
    mockedGetTileTokensBatch.mockRejectedValue(new Error('mint endpoint down'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // fix(#831): an out-of-band refreshTokens() during an outage must replace
  // the pending retry timer, not add a second retry loop alongside it.
  it('keeps a single retry timer when refreshTokens fires during an outage', async () => {
    const { result, unmount } = renderHook(() => useViewerTokens({ layers }));

    // The mount fetch fails and arms the first backoff retry timer (5s).
    await flushMicrotasks();
    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);

    // Out-of-band refresh (tile-auth recovery, visibility change) while the
    // retry timer is still pending. It fails too and re-arms the backoff.
    act(() => {
      result.current.refreshTokens();
    });
    await flushMicrotasks();
    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(2);

    // Only ONE retry timer may be pending: the stale 5s timer from the first
    // failure must have been cleared when the 10s backoff was armed.
    expect(vi.getTimerCount()).toBe(1);

    // Advance past both the stale 5s slot and the live 10s backoff — exactly
    // one retry fires. Before the fix both timers fired, doubling the loops.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(3);

    unmount();
  });
});
