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

  // fix(#850): a cancelled generation whose request rejects late must not
  // clear the newer generation's valid refresh timer from the shared ref.
  it('preserves the new generation timer when a stale request rejects late', async () => {
    type BatchResult = Awaited<ReturnType<typeof getTileTokensBatch>>;
    const deferreds: Array<{
      resolve: (value: BatchResult) => void;
      reject: (reason: unknown) => void;
    }> = [];
    mockedGetTileTokensBatch.mockImplementation(
      () =>
        new Promise<BatchResult>((resolve, reject) => {
          deferreds.push({ resolve, reject });
        }),
    );

    const layersB = [{ dataset_id: 'dataset-2' }] as unknown as SharedLayerResponse[];
    const { rerender, unmount } = renderHook(
      ({ l }: { l: SharedLayerResponse[] }) => useViewerTokens({ layers: l }),
      { initialProps: { l: layers } },
    );
    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(1);

    // Deps change while the first request is still in flight: the old
    // generation is cancelled and the new generation starts its own fetch.
    rerender({ l: layersB });
    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(2);

    // The new generation succeeds and arms its 80%-of-TTL refresh timer
    // (300s * 800 = 240s).
    await act(async () => {
      deferreds[1].resolve({
        tokens: {
          'dataset-2': { kind: 'vector', sig: 's', exp: 1, scope: 'dataset-2', expires_in: 300 },
        },
      } as BatchResult);
    });
    expect(vi.getTimerCount()).toBe(1);

    // The stale generation's request rejects late. It must not clear the new
    // generation's timer or replace it with a dead (cancelled) callback.
    await act(async () => {
      deferreds[0].reject(new Error('stale request failed'));
    });

    // The refresh timer must survive and actually fire the next fetch.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(240_000);
    });
    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(3);

    unmount();
  });
});
