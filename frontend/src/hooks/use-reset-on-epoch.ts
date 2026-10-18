import { useEffect, useRef } from 'react';

/**
 * Runs `reset()` whenever `epoch` changes after mount, never on the initial
 * render, so mounting on a page whose epoch is already nonzero doesn't discard
 * state someone is legitimately resuming.
 *
 * Shared by every consumer that keeps identity-scoped local UI state alongside a
 * store's reset-epoch counter: drawing-store's sessionEpoch (DatasetMap's local
 * drawing session) and search-store's resetEpoch (SearchBar's undebounced query,
 * FilterPanel's and FilterSheet's uncommitted date-range draft).
 *
 * `reset` should be memoized by the caller: it is an effect dependency, so an
 * unstable reference re-arms the effect every render (harmless, since the epoch
 * guard short-circuits, but wasteful).
 */
export function useResetOnEpoch(epoch: number, reset: () => void): void {
  const epochRef = useRef(epoch);
  useEffect(() => {
    if (epochRef.current === epoch) return;
    epochRef.current = epoch;
    reset();
  }, [epoch, reset]);
}
