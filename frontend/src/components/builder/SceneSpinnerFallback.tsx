import { Loader2 } from 'lucide-react';

/**
 * Lightweight Suspense fallback for lazy-loaded editor scenes and dialogs.
 * Used inside LayerEditorPanel flyout and BuilderDialogs — lighter than the
 * full-page LoadingState since the surrounding chrome is already visible.
 *
 * UI-SPEC PERF-05: centered Loader2 spinner, role="status", aria-label="Loading panel"
 */
export function SceneSpinnerFallback() {
  return (
    <div
      role="status"
      aria-label="Loading panel"
      className="flex items-center justify-center p-8"
    >
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  );
}
