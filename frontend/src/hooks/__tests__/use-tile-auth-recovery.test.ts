import { renderHook } from '@testing-library/react';
import {
  hasExpiringVectorToken,
  useTileAuthRecovery,
  useVisibleTileTokenRefresh,
} from '@/hooks/use-tile-auth-recovery';
import type { TileToken } from '@/api/tiles';

// fix(#621): one re-mint per cooldown window — MapLibre can fire dozens of
// tile errors per pan, and hammering the mint endpoint cannot help. Errors in
// the settle window ride the pending re-mint (true); errors that persist past
// it mean the re-mint didn't cure them (false).

describe('useTileAuthRecovery', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('kicks the re-mint on the first error and reports it handled', () => {
    const remint = vi.fn();
    const { result } = renderHook(() => useTileAuthRecovery(remint));

    expect(result.current()).toBe(true);
    expect(remint).toHaveBeenCalledTimes(1);
  });

  it('suppresses error UI for the rest of the burst while the re-mint settles', () => {
    const remint = vi.fn();
    const now = Date.now();
    const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(now);
    const { result } = renderHook(() => useTileAuthRecovery(remint));

    expect(result.current()).toBe(true);
    nowSpy.mockReturnValue(now + 500);
    expect(result.current()).toBe(true);
    nowSpy.mockReturnValue(now + 9_000);
    expect(result.current()).toBe(true);
    expect(remint).toHaveBeenCalledTimes(1);
  });

  it('reports failure when errors persist after the settle window', () => {
    const remint = vi.fn();
    const now = Date.now();
    const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(now);
    const { result } = renderHook(() => useTileAuthRecovery(remint));

    expect(result.current()).toBe(true);
    nowSpy.mockReturnValue(now + 15_000);
    expect(result.current()).toBe(false);
    expect(remint).toHaveBeenCalledTimes(1);
  });

  it('allows another re-mint once the cooldown has elapsed', () => {
    const remint = vi.fn();
    const now = Date.now();
    const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(now);
    const { result } = renderHook(() => useTileAuthRecovery(remint));

    expect(result.current()).toBe(true);
    nowSpy.mockReturnValue(now + 31_000);
    expect(result.current()).toBe(true);
    expect(remint).toHaveBeenCalledTimes(2);
  });
});

// fix(#755): tile sigs are minted on 900 s `round_expiry()` boundaries, so a tab
// backgrounded for a few minutes routinely returns with an expired token and
// MapLibre 403s every visible tile before the reactive handler heals the map.
// The proactive path re-mints on the VISIBLE edge instead — on the hidden edge a
// `setTiles` reload would be dropped by the paused TileManager (fix(#584)).

function vectorToken(expSeconds: number): TileToken {
  return { kind: 'vector', sig: 's', exp: expSeconds, scope: 'x', expires_in: 900 };
}

const rasterToken: TileToken = {
  kind: 'raster',
  tile_url: '/raster-tiles/x/tiles/{z}/{x}/{y}.png',
  bounds: null,
  minzoom: 0,
  maxzoom: 18,
  tile_size: 256,
  format: 'png',
};

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  });
}

/** Unix-seconds `exp` relative to now, matching the mint endpoint's shape. */
function expIn(seconds: number): number {
  return Math.floor(Date.now() / 1000) + seconds;
}

describe('hasExpiringVectorToken (fix #755)', () => {
  const now = 1_785_148_200_000; // ms
  const nowS = now / 1000;

  it('flags a token already past exp', () => {
    expect(hasExpiringVectorToken([vectorToken(nowS - 1)], now)).toBe(true);
  });

  it('flags a token inside the 60s skew window', () => {
    expect(hasExpiringVectorToken([vectorToken(nowS + 30)], now)).toBe(true);
    expect(hasExpiringVectorToken([vectorToken(nowS + 60)], now)).toBe(true);
  });

  it('leaves a comfortably fresh token alone', () => {
    expect(hasExpiringVectorToken([vectorToken(nowS + 61)], now)).toBe(false);
    expect(hasExpiringVectorToken([vectorToken(nowS + 900)], now)).toBe(false);
  });

  it('ignores raster tokens (no exp — auth rides the Authorization header)', () => {
    expect(hasExpiringVectorToken([rasterToken], now)).toBe(false);
  });

  it('ignores empty / absent entries', () => {
    expect(hasExpiringVectorToken([], now)).toBe(false);
    expect(hasExpiringVectorToken([undefined, null], now)).toBe(false);
  });

  it('flags the batch when ANY token in it is expiring', () => {
    expect(
      hasExpiringVectorToken([vectorToken(nowS + 900), rasterToken, vectorToken(nowS - 5)], now),
    ).toBe(true);
  });
});

describe('useVisibleTileTokenRefresh (fix #755)', () => {
  afterEach(() => {
    setVisibility('visible');
    vi.restoreAllMocks();
  });

  it('re-mints on the visible edge when the token has expired (kills the 403 burst)', () => {
    const recover = vi.fn(() => true);
    const expired = vectorToken(expIn(-60));
    renderHook(() => useVisibleTileTokenRefresh(() => [expired], recover));

    setVisibility('visible');
    document.dispatchEvent(new Event('visibilitychange'));

    expect(recover).toHaveBeenCalledTimes(1);
  });

  it('does nothing while the tab is still hidden (setTiles reload would be dropped)', () => {
    const recover = vi.fn(() => true);
    const expired = vectorToken(expIn(-60));
    renderHook(() => useVisibleTileTokenRefresh(() => [expired], recover));

    setVisibility('hidden');
    document.dispatchEvent(new Event('visibilitychange'));

    expect(recover).not.toHaveBeenCalled();
  });

  it('does not re-mint when the tokens are still fresh', () => {
    const recover = vi.fn(() => true);
    const fresh = vectorToken(expIn(900));
    renderHook(() => useVisibleTileTokenRefresh(() => [fresh], recover));

    document.dispatchEvent(new Event('visibilitychange'));

    expect(recover).not.toHaveBeenCalled();
  });

  it('reads the CURRENT tokens at event time, not the ones captured at mount', () => {
    const recover = vi.fn(() => true);
    let tokens: TileToken[] = [vectorToken(expIn(900))];
    const { rerender } = renderHook(() => useVisibleTileTokenRefresh(() => tokens, recover));

    document.dispatchEvent(new Event('visibilitychange'));
    expect(recover).not.toHaveBeenCalled();

    tokens = [vectorToken(expIn(-60))];
    rerender();
    document.dispatchEvent(new Event('visibilitychange'));
    expect(recover).toHaveBeenCalledTimes(1);
  });

  it('detaches the listener on unmount', () => {
    const recover = vi.fn(() => true);
    const expired = vectorToken(expIn(-60));
    const { unmount } = renderHook(() => useVisibleTileTokenRefresh(() => [expired], recover));

    unmount();
    document.dispatchEvent(new Event('visibilitychange'));

    expect(recover).not.toHaveBeenCalled();
  });

  it('rides the shared recovery throttle instead of minting per visibility flip', () => {
    // The proactive path is the SAME callback the 403 handler uses, so its
    // cooldown bounds the mint rate across rapid tab switching.
    const remint = vi.fn();
    const expired = vectorToken(expIn(-60));
    const { result } = renderHook(() => useTileAuthRecovery(remint));
    renderHook(() => useVisibleTileTokenRefresh(() => [expired], result.current));

    document.dispatchEvent(new Event('visibilitychange'));
    document.dispatchEvent(new Event('visibilitychange'));
    document.dispatchEvent(new Event('visibilitychange'));

    expect(remint).toHaveBeenCalledTimes(1);
  });

  // fix(#890): the 403 burst this path replaced at least left warnings in the
  // problem-report buffer as evidence that a recovery had happened. The reporter
  // is INJECTED (not imported) so this module keeps no dependency on it.
  it('reports the re-mint it requested', () => {
    const recover = vi.fn(() => true);
    const onRemintRequested = vi.fn();
    const expired = vectorToken(expIn(-60));
    renderHook(() => useVisibleTileTokenRefresh(() => [expired], recover, onRemintRequested));

    document.dispatchEvent(new Event('visibilitychange'));

    expect(recover).toHaveBeenCalledTimes(1);
    expect(onRemintRequested).toHaveBeenCalledTimes(1);
  });

  it('reports nothing when it decides no re-mint is due', () => {
    const recover = vi.fn(() => true);
    const onRemintRequested = vi.fn();
    const fresh = vectorToken(expIn(900));
    const { unmount } = renderHook(() =>
      useVisibleTileTokenRefresh(() => [fresh], recover, onRemintRequested),
    );

    // Fresh sig on the visible edge…
    document.dispatchEvent(new Event('visibilitychange'));
    // …and the hidden edge, which never re-mints at all.
    setVisibility('hidden');
    document.dispatchEvent(new Event('visibilitychange'));
    setVisibility('visible');
    unmount();
    document.dispatchEvent(new Event('visibilitychange'));

    expect(onRemintRequested).not.toHaveBeenCalled();
  });

  it('calls the LATEST reporter without re-registering the listener', () => {
    const recover = vi.fn(() => true);
    const first = vi.fn();
    const second = vi.fn();
    const expired = vectorToken(expIn(-60));
    const addSpy = vi.spyOn(document, 'addEventListener');
    const { rerender } = renderHook(
      ({ report }: { report: () => void }) =>
        useVisibleTileTokenRefresh(() => [expired], recover, report),
      { initialProps: { report: first } },
    );
    const registrations = addSpy.mock.calls.filter(([event]) => event === 'visibilitychange').length;

    rerender({ report: second });
    document.dispatchEvent(new Event('visibilitychange'));

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
    expect(
      addSpy.mock.calls.filter(([event]) => event === 'visibilitychange').length,
    ).toBe(registrations);
  });
});
