import { useCallback, useRef } from 'react';

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
