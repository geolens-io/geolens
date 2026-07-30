import { useCallback, useEffect, useRef } from 'react';
import type { TileToken } from '@/api/tiles';

// fix(#621): one re-mint per cooldown window bounds the retry loop — MapLibre
// can fire dozens of tile errors per pan, and a mint that just failed will not
// succeed milliseconds later.
const REMINT_COOLDOWN_MS = 30_000;
// fix(#819): settle window — how long after kicking a re-mint we keep treating errors as
// "the same burst the re-mint is about to cure". MapLibre fires one error per
// failing tile, so tiles 2..N of the burst that *triggered* the re-mint arrive
// while the mint request + token→setTiles plumbing are still in flight.
// Treating those as "cooldown" latched a false error overlay over a map the
// re-mint was about to fix. Errors that persist past this window mean the
// fresh token didn't cure them (revoked grant, expired embed token) — those
// fall through to the surface's error UI.
const REMINT_SETTLE_MS = 10_000;

/**
 * fix(#621): shared vector-tile auth recovery for every map surface (builder,
 * viewer, dataset preview). The builder's GUARD-03 re-sign only reuses the
 * token already in hand — when the signature itself has expired, the only fix
 * is a re-mint. Each surface passes its own `remint` (invalidate the
 * tile-token queries, or the viewer's imperative refetch); the fresh token
 * then flows through that surface's existing token→setTiles plumbing.
 *
 * The mint request rides the shared fetch core, so a conclusively dead
 * session (401 + refresh-401) triggers the global signed-out handling (#628)
 * instead of a per-surface toast.
 *
 * Returns true while recovery is plausibly in progress (a re-mint was just
 * kicked off, or the error is part of the burst that kicked it — suppress
 * per-surface error UI); false when errors persist after the re-mint had time
 * to land (it didn't cure them — fall through to existing error UI).
 */
export function useTileAuthRecovery(remint: () => void) {
  const lastAttemptRef = useRef(0);
  return useCallback((): boolean => {
    const elapsed = Date.now() - lastAttemptRef.current;
    if (elapsed < REMINT_SETTLE_MS) return true;
    if (elapsed < REMINT_COOLDOWN_MS) return false;
    lastAttemptRef.current = Date.now();
    remint();
    return true;
  }, [remint]);
}

// fix(#755): a sig that expires seconds from now is already useless — MapLibre's
// resumed tile requests would reach the server after the boundary. Treat any
// vector token inside this window as due for a re-mint.
const EXPIRY_SKEW_MS = 60_000;

/**
 * fix(#755): true when any vector token is past `exp` or within
 * EXPIRY_SKEW_MS of it. Raster tokens carry no expiry (their `tile_url` is
 * stable and auth rides the Authorization header), so they never qualify.
 * `exp` is the unix-seconds expiry the mint endpoint stamps into the tile URL.
 */
export function hasExpiringVectorToken(
  tokens: Iterable<TileToken | null | undefined>,
  nowMs: number = Date.now(),
): boolean {
  for (const token of tokens) {
    if (token?.kind !== 'vector') continue;
    if (token.exp * 1000 - nowMs <= EXPIRY_SKEW_MS) return true;
  }
  return false;
}

/**
 * fix(#755): re-mint tile tokens on the tab-return edge instead of after the
 * 403 burst. Tile sigs are minted on `round_expiry()` 900 s boundaries, so a
 * tab backgrounded for a few minutes routinely crosses one; MapLibre then
 * resumes its fetches with the stale `sig` and every visible tile 403s before
 * the reactive GUARD-03 / #621 handler heals the map.
 *
 * Deliberately the SAME `recover` callback the 403 handler uses, so this only
 * pulls the existing re-mint forward: its 30 s cooldown / 10 s settle window
 * still bound the mint rate, and a 403 that does slip through now lands inside
 * the settle window, where it is reported suppressed instead of surfacing
 * error UI.
 *
 * `getTokens` is read at event time (not captured), so the listener registers
 * once and still sees the current token set.
 *
 * Fires on the VISIBLE edge only: MapLibre 5 drops a `setTiles` reload while
 * the source's TileManager is paused (fix(#584)) and a hidden tab has no rAF,
 * so re-minting while still hidden would silently no-op.
 */
export function useVisibleTileTokenRefresh(
  getTokens: () => Iterable<TileToken | null | undefined>,
  recover: () => boolean,
): void {
  const getTokensRef = useRef(getTokens);
  getTokensRef.current = getTokens;

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState !== 'visible') return;
      if (!hasExpiringVectorToken(getTokensRef.current())) return;
      recover();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => document.removeEventListener('visibilitychange', onVisibilityChange);
  }, [recover]);
}
