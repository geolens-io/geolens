import { useCallback, useEffect, useRef } from 'react';
import type { TileToken } from '@/api/tiles';
import { useAuthStore } from '@/stores/auth-store';
import { tryRefresh } from '@/api/client';

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
 *
 * fix(#890): `onRemint` fires exactly when this hook kicks a FRESH mint — never
 * inside the settle window or the cooldown gap, where the returned boolean says
 * nothing about whether a mint ran. That makes it the only honest place to
 * report a re-mint from; `trigger` names the path that asked for one so the
 * report distinguishes a tab return from a tile error. It is injected (not
 * imported) so this hook stays free of any reporting dependency, and held in a
 * ref so the returned callback keeps a stable identity — ViewerMap and
 * DatasetMap list it in `handleLoad`'s deps.
 */
export function useTileAuthRecovery(
  remint: () => void,
  onRemint?: (trigger: string) => void,
) {
  const lastAttemptRef = useRef(0);
  const onRemintRef = useRef(onRemint);
  onRemintRef.current = onRemint;
  return useCallback((trigger: string = 'tile-error'): boolean => {
    const elapsed = Date.now() - lastAttemptRef.current;
    if (elapsed < REMINT_SETTLE_MS) return true;
    if (elapsed < REMINT_COOLDOWN_MS) return false;
    lastAttemptRef.current = Date.now();
    remint();
    onRemintRef.current?.(trigger);
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
 * fix(#907): true when the session access token is at or inside the same skew
 * window. Raster/DEM tiles authenticate with that JWT through
 * `buildTileTransformRequest`'s Authorization header, not with a signed tile
 * sig, so `hasExpiringVectorToken` can never see their credential expire — a
 * raster-only map has nothing that qualifies and 401s its whole tile surface
 * once on tab return. `null` (anonymous / embed-token surfaces) is not
 * expiring: there is no session credential to renew.
 */
export function hasExpiringSession(
  expiresAt: number | null | undefined,
  nowMs: number = Date.now(),
): boolean {
  return expiresAt != null && expiresAt - nowMs <= EXPIRY_SKEW_MS;
}

// fix(#907): how long to keep watching for a rotation after our own refresh
// attempt failed. Bounded so a permanently dead session leaves no listener
// behind; the reactive 401 path still owns anything slower than this.
const RENEWAL_WATCH_MS = 30_000;

/** Run `reload` once the session token has actually rotated — immediately when
 * our own refresh produced the new one, otherwise on the first store change a
 * concurrent mint's refresh writes, and never if neither happens.
 *
 * The token comparison is the ONLY evidence used. `tryRefresh` resolves
 * `!!useAuthStore.getState().token` (api/client.ts), so it answers "is there
 * still a token", not "did it rotate" — it comes back true for a transient
 * failure that left the stale one in place, and reloading on that would just
 * 401 against the same Bearer. */
function reloadOnTokenRotation(reload: () => void): void {
  const tokenBefore = useAuthStore.getState().token;
  void tryRefresh().then(() => {
    if (useAuthStore.getState().token !== tokenBefore) {
      reload();
      return;
    }
    let unsubscribe: (() => void) | null = null;
    const timer = setTimeout(() => unsubscribe?.(), RENEWAL_WATCH_MS);
    unsubscribe = useAuthStore.subscribe((state) => {
      if (state.token === tokenBefore) return;
      clearTimeout(timer);
      unsubscribe?.();
      reload();
    });
  });
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
 *
 * fix(#890): passes the `tab-return` trigger so `useTileAuthRecovery`'s
 * `onRemint` reports which path recovered — the 403 burst this replaced at
 * least evidenced a recovery, and a proactive re-mint otherwise leaves none.
 */
export function useVisibleTileTokenRefresh(
  getTokens: () => Iterable<TileToken | null | undefined>,
  recover: (trigger?: string) => boolean,
  onCredentialRenewed?: () => void,
): void {
  const getTokensRef = useRef(getTokens);
  getTokensRef.current = getTokens;
  const onCredentialRenewedRef = useRef(onCredentialRenewed);
  onCredentialRenewedRef.current = onCredentialRenewed;

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState !== 'visible') return;
      // fix(#907): the session JWT counts too. Raster/DEM tiles authenticate
      // with it through `buildTileTransformRequest`'s Authorization header,
      // not a signed sig, so `hasExpiringVectorToken` can never see their
      // credential expire and a raster-only map had nothing to trigger on.
      const sessionExpiring = hasExpiringSession(useAuthStore.getState().expiresAt);
      if (!hasExpiringVectorToken(getTokensRef.current()) && !sessionExpiring) return;
      if (sessionExpiring) {
        // fix(#907) (codex P1): renewing the credential is not enough on its
        // own — MapLibre resumes its fetches as soon as the tab is visible and
        // races the refresh, and a raster descriptor does not change across
        // one, so nothing in the token→setTiles plumbing retries the tiles that
        // 401'd. Reload them explicitly, but only once the token has ACTUALLY
        // rotated: `tryRefresh` resolves false on a transient failure (offline,
        // 429), and reloading against the same stale Bearer would just 401
        // again. `recover`'s own mint collapses into this same refresh (the
        // in-flight singleton in api/client.ts), so this costs no extra request
        // — and when our attempt is the one that fails, that mint's later
        // rotation is what the store subscription below picks up.
        reloadOnTokenRotation(() => onCredentialRenewedRef.current?.());
      }
      recover('tab-return');
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => document.removeEventListener('visibilitychange', onVisibilityChange);
  }, [recover]);
}
