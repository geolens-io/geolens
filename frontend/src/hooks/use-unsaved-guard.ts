import { useCallback, useEffect } from 'react';
import { useBlocker } from 'react-router';

/**
 * Warns the user when navigating away with unsaved changes.
 * Handles both in-app navigation (useBlocker) and browser close (beforeunload).
 *
 * Returns the blocker so the caller can render a confirmation dialog.
 */
export function useUnsavedGuard(hasUnsavedChanges: boolean) {
  // Warn on browser close / tab close / refresh
  useEffect(() => {
    if (!hasUnsavedChanges) return;
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = '';
    }
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasUnsavedChanges]);

  // Block in-app navigation. Use the FUNCTION form so we only block on real
  // route (PATHNAME) changes — not hash-only navigation. DatasetPage drives its
  // tab state via the URL hash; a boolean blocker fought that hash navigation
  // and triggered react-router's "blocker on POP navigation not created by
  // @remix-run/router" warning. Pathname-based callers (e.g. the map builder)
  // are unaffected — leaving the builder route still blocks. (#13)
  const blocker = useBlocker(
    useCallback(
      ({ currentLocation, nextLocation }) =>
        hasUnsavedChanges && currentLocation.pathname !== nextLocation.pathname,
      [hasUnsavedChanges],
    ),
  );

  return blocker;
}
