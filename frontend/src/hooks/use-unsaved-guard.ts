import { useEffect } from 'react';
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
    }
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasUnsavedChanges]);

  // Block in-app navigation
  const blocker = useBlocker(hasUnsavedChanges);

  return blocker;
}
