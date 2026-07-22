import { useCallback, useRef } from 'react';

// fix(#621): one re-mint per cooldown window bounds the retry loop — MapLibre
// can fire dozens of tile errors per pan, and a mint that just failed will not
// succeed milliseconds later.
const REMINT_COOLDOWN_MS = 30_000;

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
 * Returns true when a re-mint was kicked off (recovery in progress — suppress
 * per-surface error UI); false while in cooldown (a recent re-mint didn't
 * cure the error — fall through to existing error UI).
 */
export function useTileAuthRecovery(remint: () => void) {
  const lastAttemptRef = useRef(0);
  return useCallback((): boolean => {
    const now = Date.now();
    if (now - lastAttemptRef.current < REMINT_COOLDOWN_MS) return false;
    lastAttemptRef.current = now;
    remint();
    return true;
  }, [remint]);
}
