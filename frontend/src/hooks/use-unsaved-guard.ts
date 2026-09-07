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

  // Block in-app navigation. The FUNCTION form blocks on PATHNAME changes
  // only, so DatasetPage's hash-driven tabs stay navigable with edits pending
  // while leaving the builder route still blocks (#13, #1991).
  const blocker = useBlocker(
    useCallback(
      ({ currentLocation, nextLocation }) =>
        hasUnsavedChanges && currentLocation.pathname !== nextLocation.pathname,
      [hasUnsavedChanges],
    ),
  );

  return blocker;
}
