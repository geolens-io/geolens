import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/**
 * Lightweight Suspense fallback for lazy-loaded editor scenes and dialogs.
 * Used inside LayerEditorPanel flyout and BuilderDialogs — lighter than the
 * full-page LoadingState since the surrounding chrome is already visible.
 *
 * UI-SPEC PERF-05: centered Loader2 spinner, role="status".
 * fix(#394) UX-06: aria-label is localized (was hardcoded English).
 */
export function SceneSpinnerFallback() {
  const { t } = useTranslation('builder');
  return (
    <div
      role="status"
      aria-label={t('a11y.loadingPanel', { defaultValue: 'Loading panel' })}
      className="flex items-center justify-center p-8"
    >
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  );
}
