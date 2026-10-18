import { useCallback, useEffect, useRef } from 'react';
import type { TileToken } from '@/api/tiles';
import { useAuthStore } from '@/stores/auth-store';
import { tryRefresh } from '@/api/client';

// One re-mint per cooldown window bounds the retry loop: MapLibre can fire
// dozens of tile errors per pan, and a mint that just failed won't succeed
// milliseconds later.
const REMINT_COOLDOWN_MS = 30_000;
// Settle window: errors in the burst that triggered a re-mint arrive while the
// mint and token→setTiles plumbing are in flight, and must not latch a false
// error overlay. Errors persisting past it mean the fresh token didn't cure them
// (revoked grant, expired embed token) and fall through to the surface's error UI.
const REMINT_SETTLE_MS = 10_000;

/**
 * Shared vector-tile auth recovery for every map surface (builder, viewer,
 * dataset preview). The builder's re-sign only reuses the token already in hand,
 * so an expired signature needs a re-mint. Each surface passes its own `remint`
 * (invalidate the tile-token queries, or the viewer's imperative refetch); the
 * fresh token flows through that surface's token→setTiles plumbing.
 *
 * The mint request rides the shared fetch core, so a conclusively dead session
 * (401 + refresh-401) triggers the global signed-out handling instead of a toast.
 *
 * Returns true while recovery is plausibly in progress (a re-mint was just kicked
 * off, or the error is part of its burst: suppress per-surface error UI); false
 * when errors persist after the re-mint had time to land.
 *
 * `onRemint` fires exactly when this hook kicks a fresh mint, never inside the
 * settle window or cooldown gap, so it is the only honest place to report one;
 * `trigger` distinguishes a tab return from a tile error. It is injected so the
 * hook has no reporting dependency, and held in a ref so the returned callback
 * keeps a stable identity (ViewerMap and DatasetMap list it in `handleLoad`'s deps).
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

// A sig expiring seconds from now is already useless: resumed tile requests
// would reach the server after the boundary. Re-mint any vector token inside this window.
const EXPIRY_SKEW_MS = 60_000;

/**
 * True when any vector token is past `exp` or within EXPIRY_SKEW_MS of it.
 * Raster tokens carry no expiry (auth rides the Authorization header), so they
 * never qualify. `exp` is the unix-seconds expiry the mint endpoint stamps into
 * the tile URL.
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
 * True when the session access token is at or inside the same skew window.
 * Raster/DEM tiles authenticate with that JWT, not a signed sig, so
 * `hasExpiringVectorToken` never sees their credential expire and a raster-only
 * map would 401 its whole tile surface once on tab return. `null` (anonymous /
 * embed-token surfaces) is not expiring: there is no session credential to renew.
 */
export function hasExpiringSession(
  expiresAt: number | null | undefined,
  nowMs: number = Date.now(),
): boolean {
  return expiresAt != null && expiresAt - nowMs <= EXPIRY_SKEW_MS;
}

// How long a raster/DEM auth failure stays attributable to a renewal we are
// running. MapLibre resumes fetches the instant the tab is visible and can 401
// before the refresh lands; the post-rotation reload cures those. Time-boxed: a
// revoked grant 403s long after any renewal window and must still surface.
const RENEWAL_SUPPRESS_MS = 10_000;

// Hard ceiling on how long an in-flight renewal can keep suppressing:
// `refreshAccessToken` rides an unbounded fetch, and a hung request would
// otherwise silence raster auth errors for the session.
const RENEWAL_MAX_MS = 60_000;

let renewalInFlight = false;
let renewalDeadline = 0;
let renewalPendingUntil = 0;

/**
 * True while a visible-edge session renewal is in flight (or has just reloaded
 * the raster sources). Surfaces use it to stop telling the user to reload for a
 * raster 401 that is seconds from healing; raster failures are otherwise
 * unsuppressed because nothing else can cure them.
 */
export function isSessionRenewalPending(nowMs: number = Date.now()): boolean {
  // Tied to the refresh promise, not a fixed deadline: a slow `/auth/refresh/`
  // can outlast any preset window, and a 401 in that gap would latch DatasetMap's
  // permanent error overlay for tiles the rotation heals. The grace period after
  // it settles covers the reload and the errors the race already queued.
  if (renewalInFlight && nowMs < renewalDeadline) return true;
  return nowMs < renewalPendingUntil;
}

// How long to keep watching for a rotation after our own refresh failed.
// Bounded so a dead session leaves no listener; the reactive 401 path owns
// anything slower.
const RENEWAL_WATCH_MS = 30_000;

/** Run `reload` once the session token has actually rotated: immediately when
 * our own refresh produced the new one, otherwise on the first store change a
 * concurrent mint's refresh writes, and never if neither happens. Compares
 * token values; the reload needs the new token, not just a refresh's success. */
function reloadOnTokenRotation(reload: () => void): void {
  const tokenBefore = useAuthStore.getState().token;
  renewalInFlight = true;
  renewalDeadline = Date.now() + RENEWAL_MAX_MS;
  renewalPendingUntil = Date.now() + RENEWAL_SUPPRESS_MS;
  const reloadAndExtend = () => {
    // Cover the errors already queued by the race, which arrive just after the
    // reload is issued.
    renewalPendingUntil = Date.now() + RENEWAL_SUPPRESS_MS;
    reload();
  };
  // A changed token isn't necessarily renewed: a dead session makes
  // `notifySessionExpired` log out and null the token, and reloading then would
  // refetch every raster tile with no Authorization header (a second 401 burst).
  // Only a non-null, different token is a rotation.
  const isRotation = (token: string | null) => token !== null && token !== tokenBefore;
  void tryRefresh().then(() => {
    renewalInFlight = false;
    renewalPendingUntil = Date.now() + RENEWAL_SUPPRESS_MS;
    if (isRotation(useAuthStore.getState().token)) {
      reloadAndExtend();
      return;
    }
    let unsubscribe: (() => void) | null = null;
    const timer = setTimeout(() => unsubscribe?.(), RENEWAL_WATCH_MS);
    unsubscribe = useAuthStore.subscribe((state) => {
      if (!isRotation(state.token)) return;
      clearTimeout(timer);
      unsubscribe?.();
      reloadAndExtend();
    });
  });
}

/**
 * Re-mint tile tokens on the tab-return edge instead of after the 403 burst.
 * Tile sigs are minted on `round_expiry()` 900 s boundaries, so a tab
 * backgrounded for a few minutes routinely crosses one and every visible tile
 * 403s on resume.
 *
 * Uses the same `recover` callback as the 403 handler, so its 30 s cooldown /
 * 10 s settle window still bound the mint rate, and a 403 that slips through
 * lands inside the settle window and is reported suppressed.
 *
 * `getTokens` is read at event time so the listener registers once and still
 * sees the current token set.
 *
 * Fires on the visible edge only: MapLibre 5 drops a `setTiles` reload while the
 * TileManager is paused and a hidden tab has no rAF, so a hidden re-mint would no-op.
 *
 * Passes the `tab-return` trigger so `onRemint` reports which path recovered.
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
      // The session JWT counts too: raster/DEM tiles authenticate with it, so
      // `hasExpiringVectorToken` can't see them expire.
      const sessionExpiring = hasExpiringSession(useAuthStore.getState().expiresAt);
      if (!hasExpiringVectorToken(getTokensRef.current()) && !sessionExpiring) return;
      if (sessionExpiring) {
        // Renewing the credential isn't enough: MapLibre resumes fetches as soon as
        // the tab is visible and races the refresh, and a raster descriptor doesn't
        // change across one, so nothing retries the tiles that 401'd. Reload them
        // only once the token has actually rotated: `tryRefresh` resolves false on
        // a transient failure (offline, 429) and reloading against the same stale
        // Bearer would 401 again. `recover`'s mint collapses into this refresh (the
        // in-flight singleton in api/client.ts); if ours fails, that mint's later
        // rotation is what the store subscription below picks up.
        reloadOnTokenRotation(() => onCredentialRenewedRef.current?.());
      }
      recover('tab-return');
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => document.removeEventListener('visibilitychange', onVisibilityChange);
  }, [recover]);
}
