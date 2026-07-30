// fix(#890): the viewer used to refresh tile tokens by a hand-rolled
// `useState` + `setTimeout` loop while the builder and dataset preview used
// TanStack Query — two opposite policies for one problem. Chrome throttles a
// hidden tab's timers but still FIRES them, so the viewer's refresh could land
// while hidden and push a fresh tile URL at a paused map (the dropped-`setTiles`
// hazard from fix(#584)), while the TanStack surfaces did nothing at all until
// the tab returned.
//
// The viewer is now on the same TanStack path, so these specs pin the unified
// policy rather than the deleted timer machinery (the fix(#831) single-retry-timer
// and fix(#850) late-rejection specs went with it — TanStack owns scheduling and
// cancellation now):
//   1. a HIDDEN tab performs zero refreshes (refetchIntervalInBackground: false)
//   2. a VISIBLE tab refreshes at 80% of the shortest vector TTL
//   3. the tab-return edge re-mints through the fix(#755) visible-edge hook
//   4. a failed mint keeps retrying, and surfaces the token-error toast
import { act, renderHook, waitFor } from '@/test/test-utils';
import { getTileTokensBatch } from '@/api/tiles';
import { useViewerTokens } from '@/components/viewer/hooks/use-viewer-tokens';
import { useTileAuthRecovery, useVisibleTileTokenRefresh } from '@/hooks/use-tile-auth-recovery';
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

import { toast } from 'sonner';

const mockedGetTileTokensBatch = vi.mocked(getTileTokensBatch);

const layers = [{ dataset_id: 'dataset-1' }] as unknown as SharedLayerResponse[];

/** `expires_in` 300 s → the refresh interval is 300 * 800 = 240_000 ms. */
const TTL_SECONDS = 300;
const REFRESH_MS = TTL_SECONDS * 800;

function batchResponse(expOffsetSeconds = 900) {
  return {
    tokens: {
      'dataset-1': {
        kind: 'vector' as const,
        sig: 'sig-1',
        exp: Math.floor(Date.now() / 1000) + expOffsetSeconds,
        scope: 'dataset-1',
        expires_in: TTL_SECONDS,
      },
    },
  };
}

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
}

describe('useViewerTokens refresh policy (fix #890)', () => {
  beforeEach(() => {
    mockedGetTileTokensBatch.mockReset();
    mockedGetTileTokensBatch.mockResolvedValue(batchResponse());
    vi.mocked(toast.error).mockClear();
    setVisibility('visible');
  });

  afterEach(() => {
    setVisibility('visible');
    vi.useRealTimers();
  });

  it('exposes the minted tokens as a token map', async () => {
    const { result } = renderHook(() => useViewerTokens({ layers }));

    await waitFor(() => expect(result.current.tokenMap.size).toBe(1));
    expect(result.current.tokenMap.get('dataset-1')).toMatchObject({ kind: 'vector', sig: 'sig-1' });
    expect(result.current.tokenError).toBe(false);
  });

  it('skips the mint entirely when the map has no layers', () => {
    renderHook(() => useViewerTokens({ layers: [] }));
    expect(mockedGetTileTokensBatch).not.toHaveBeenCalled();
  });

  // Fake timers are installed BEFORE the render in the two cadence specs: the
  // refetch interval is scheduled during the mount fetch, and a timer created
  // under real timers is never advanced by fake ones.
  it('does NOT refresh while the tab is hidden', async () => {
    vi.useFakeTimers();
    setVisibility('hidden');
    const { result } = renderHook(() => useViewerTokens({ layers }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.tokenMap.size).toBe(1);
    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(1);

    // TanStack's interval timer still ticks; `refetchIntervalInBackground: false`
    // makes it a no-op while document.visibilityState is 'hidden'.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_MS * 3);
    });

    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(1);
  });

  it('refreshes on the TTL cadence while the tab is visible', async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useViewerTokens({ layers }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.tokenMap.size).toBe(1);
    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_MS + 1_000);
    });

    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(2);
  });

  it('re-mints on the visible edge when the sig has expired (the fix(#755) hook path)', async () => {
    // An already-expired sig, i.e. the tab-return case the burst came from.
    mockedGetTileTokensBatch.mockResolvedValue(batchResponse(-60));
    const { result } = renderHook(() => {
      const tokens = useViewerTokens({ layers });
      const recover = useTileAuthRecovery(tokens.refreshTokens);
      useVisibleTileTokenRefresh(() => tokens.tokenMap.values(), recover);
      return tokens;
    });
    await waitFor(() => expect(result.current.tokenMap.size).toBe(1));
    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(1);

    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await waitFor(() => expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(2));
  });

  it('does not re-mint on the visible edge while the sig is still fresh', async () => {
    const { result } = renderHook(() => {
      const tokens = useViewerTokens({ layers });
      const recover = useTileAuthRecovery(tokens.refreshTokens);
      useVisibleTileTokenRefresh(() => tokens.tokenMap.values(), recover);
      return tokens;
    });
    await waitFor(() => expect(result.current.tokenMap.size).toBe(1));

    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(1);
  });

  it('refreshes on demand for the 401/403 recovery path', async () => {
    const { result } = renderHook(() => useViewerTokens({ layers }));
    await waitFor(() => expect(result.current.tokenMap.size).toBe(1));
    const refreshTokens = result.current.refreshTokens;

    await act(async () => {
      refreshTokens();
    });

    expect(mockedGetTileTokensBatch).toHaveBeenCalledTimes(2);
    // Stable identity: the map error handlers close over it once (fix #621).
    expect(result.current.refreshTokens).toBe(refreshTokens);
  });

  it('surfaces the token-error toast and keeps retrying when the mint endpoint is down', async () => {
    vi.useFakeTimers();
    mockedGetTileTokensBatch.mockRejectedValue(new Error('mint endpoint down'));
    const { result } = renderHook(() => useViewerTokens({ layers }));

    // The bounded `retry: 3` backoff runs first, then the query settles as error.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(result.current.tokenError).toBe(true);
    expect(toast.error).toHaveBeenCalledWith(
      'viewer.tokenError',
      expect.objectContaining({ id: 'viewer-token-error' }),
    );
    const attemptsAfterFailure = mockedGetTileTokensBatch.mock.calls.length;

    // A failed query has no TTL to derive a cadence from, so the outage retry
    // interval keeps it trying instead of leaving the viewer permanently blank.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });

    expect(mockedGetTileTokensBatch.mock.calls.length).toBeGreaterThan(attemptsAfterFailure);
  });
});
