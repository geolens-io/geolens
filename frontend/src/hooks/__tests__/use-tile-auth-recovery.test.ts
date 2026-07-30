import { renderHook } from '@testing-library/react';
import {
  hasExpiringSession,
  hasExpiringVectorToken,
  useTileAuthRecovery,
  useVisibleTileTokenRefresh,
} from '@/hooks/use-tile-auth-recovery';
import type { TileToken } from '@/api/tiles';
import { useAuthStore } from '@/stores/auth-store';

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

  // fix(#890): telemetry lives here because this is the only place that knows a
  // mint actually started — the returned boolean is `true` both for a fresh mint
  // and for an error riding the settle window, and `false` mid-cooldown.
  describe('onRemint telemetry (fix #890)', () => {
    it('fires once per real mint, with the trigger that asked for it', () => {
      const remint = vi.fn();
      const onRemint = vi.fn();
      const { result } = renderHook(() => useTileAuthRecovery(remint, onRemint));

      expect(result.current('tab-return')).toBe(true);

      expect(onRemint).toHaveBeenCalledTimes(1);
      expect(onRemint).toHaveBeenCalledWith('tab-return');
    });

    it('defaults the trigger for the reactive tile-error path', () => {
      const onRemint = vi.fn();
      const { result } = renderHook(() => useTileAuthRecovery(vi.fn(), onRemint));

      result.current();

      expect(onRemint).toHaveBeenCalledWith('tile-error');
    });

    it('stays silent when the throttle swallows the call (no mint ran)', () => {
      const remint = vi.fn();
      const onRemint = vi.fn();
      const now = Date.now();
      const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(now);
      const { result } = renderHook(() => useTileAuthRecovery(remint, onRemint));

      expect(result.current('tab-return')).toBe(true);
      // Settle window: returns true WITHOUT minting — reporting here would claim
      // a rotation that never happened.
      nowSpy.mockReturnValue(now + 5_000);
      expect(result.current('tab-return')).toBe(true);
      // Cooldown gap: returns false, still no mint.
      nowSpy.mockReturnValue(now + 20_000);
      expect(result.current('tab-return')).toBe(false);

      expect(remint).toHaveBeenCalledTimes(1);
      expect(onRemint).toHaveBeenCalledTimes(1);
    });

    it('calls the LATEST reporter without churning the callback identity', () => {
      const first = vi.fn();
      const second = vi.fn();
      const remint = vi.fn();
      const { result, rerender } = renderHook(
        ({ report }: { report: (trigger: string) => void }) => useTileAuthRecovery(remint, report),
        { initialProps: { report: first as (trigger: string) => void } },
      );
      const recover = result.current;

      rerender({ report: second as (trigger: string) => void });
      // Identity must survive an inline-arrow reporter: ViewerMap and DatasetMap
      // list this callback in `handleLoad`'s deps.
      expect(result.current).toBe(recover);
      result.current();

      expect(first).not.toHaveBeenCalled();
      expect(second).toHaveBeenCalledTimes(1);
    });
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

describe('hasExpiringSession (fix #907)', () => {
  const now = 1_785_148_200_000; // ms

  it('flags a session already past expiry', () => {
    expect(hasExpiringSession(now - 1, now)).toBe(true);
  });

  it('flags a session inside the 60s skew window', () => {
    expect(hasExpiringSession(now + 30_000, now)).toBe(true);
    expect(hasExpiringSession(now + 60_000, now)).toBe(true);
  });

  it('leaves a comfortably fresh session alone', () => {
    expect(hasExpiringSession(now + 60_001, now)).toBe(false);
    expect(hasExpiringSession(now + 900_000, now)).toBe(false);
  });

  it('treats an absent expiry as not expiring (anonymous / embed-token surfaces)', () => {
    expect(hasExpiringSession(null, now)).toBe(false);
    expect(hasExpiringSession(undefined, now)).toBe(false);
  });
});

describe('useVisibleTileTokenRefresh (fix #755)', () => {
  afterEach(() => {
    setVisibility('visible');
    useAuthStore.setState({ expiresAt: null });
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

  // fix(#890): the trigger is what makes the re-mint traceable — the reactive
  // 403 burst this path replaced at least left warnings behind as evidence that
  // a recovery happened. `useTileAuthRecovery` turns it into one report per
  // actual mint (see its onRemint suite above).
  it('names itself as the trigger so the report can distinguish a tab return', () => {
    const recover = vi.fn(() => true);
    const expired = vectorToken(expIn(-60));
    renderHook(() => useVisibleTileTokenRefresh(() => [expired], recover));

    document.dispatchEvent(new Event('visibilitychange'));

    expect(recover).toHaveBeenCalledTimes(1);
    expect(recover).toHaveBeenCalledWith('tab-return');
  });

  it('reports nothing through the recovery hook when no re-mint is due', () => {
    const remint = vi.fn();
    const onRemint = vi.fn();
    const fresh = vectorToken(expIn(900));
    const { result } = renderHook(() => useTileAuthRecovery(remint, onRemint));
    const { unmount } = renderHook(() =>
      useVisibleTileTokenRefresh(() => [fresh], result.current),
    );

    // Fresh sig on the visible edge…
    document.dispatchEvent(new Event('visibilitychange'));
    // …and the hidden edge, which never re-mints at all.
    setVisibility('hidden');
    document.dispatchEvent(new Event('visibilitychange'));
    setVisibility('visible');
    unmount();
    document.dispatchEvent(new Event('visibilitychange'));

    expect(remint).not.toHaveBeenCalled();
    expect(onRemint).not.toHaveBeenCalled();
  });

  // fix(#907): raster/DEM tiles carry the session JWT in an Authorization
  // header, so a raster-only map has no `exp` for hasExpiringVectorToken to
  // see. Without the session half of the gate it 401s its whole tile surface
  // once on tab return.
  it('re-mints for a raster-only map whose session JWT is expiring', () => {
    const recover = vi.fn(() => true);
    useAuthStore.setState({ expiresAt: Date.now() + 10_000 });
    renderHook(() => useVisibleTileTokenRefresh(() => [rasterToken], recover));

    document.dispatchEvent(new Event('visibilitychange'));

    expect(recover).toHaveBeenCalledWith('tab-return');
  });

  it('leaves a raster-only map alone while its session JWT is fresh', () => {
    const recover = vi.fn(() => true);
    useAuthStore.setState({ expiresAt: Date.now() + 3_600_000 });
    renderHook(() => useVisibleTileTokenRefresh(() => [rasterToken], recover));

    document.dispatchEvent(new Event('visibilitychange'));

    expect(recover).not.toHaveBeenCalled();
  });

  it('still does nothing on the hidden edge when only the session is expiring', () => {
    const recover = vi.fn(() => true);
    useAuthStore.setState({ expiresAt: Date.now() + 10_000 });
    renderHook(() => useVisibleTileTokenRefresh(() => [rasterToken], recover));

    setVisibility('hidden');
    document.dispatchEvent(new Event('visibilitychange'));

    expect(recover).not.toHaveBeenCalled();
  });
});
