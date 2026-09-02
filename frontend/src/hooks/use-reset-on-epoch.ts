import { useEffect, useRef } from 'react';

/**
 * fix(#1761 review round 4): runs `reset()` whenever `epoch` changes after
 * mount — never on the initial render, so mounting on a page whose epoch is
 * already nonzero doesn't spuriously discard state someone is legitimately
 * resuming (the pattern this was extracted from, in SearchBar).
 *
 * Shared by every consumer that keeps identity-scoped local UI state
 * alongside a store's own reset-epoch counter: drawing-store's
 * sessionEpoch (DatasetMap's local drawing session) and search-store's
 * resetEpoch (SearchBar's typed-but-undebounced query, FilterPanel's and
 * FilterSheet's uncommitted date-range draft). Extracted so all of them
 * share one skip-on-mount implementation instead of reimplementing the
 * ref dance per consumer.
 *
 * `reset` should be memoized (`useCallback`) by the caller — it is an
 * effect dependency, so an unstable reference re-arms this every render.
 * That is harmless (the epoch guard below still short-circuits before
 * calling it), just wasteful.
 */
export function useResetOnEpoch(epoch: number, reset: () => void): void {
  const epochRef = useRef(epoch);
  useEffect(() => {
    if (epochRef.current === epoch) return;
    epochRef.current = epoch;
    reset();
  }, [epoch, reset]);
}
