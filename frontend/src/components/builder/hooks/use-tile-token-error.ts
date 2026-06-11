/**
 * useTileTokenError — GAP-004
 *
 * Surfaces a deduped toast.error when the builder's tile-token batch query
 * fails, mirroring the viewer's tokenError pattern (use-viewer-tokens.ts).
 *
 * Dedupe: the toast uses a stable `id` so repeated renders in the error state
 * do not stack multiple toasts. The hook tracks the previous `isError` value
 * so a new error episode (false→true transition) fires a fresh toast.
 */
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

const TOAST_ID = 'builder-token-error';

export function useTileTokenError(isError: boolean): void {
  const { t } = useTranslation('builder');
  const prevErrorRef = useRef(false);

  useEffect(() => {
    const wasError = prevErrorRef.current;
    prevErrorRef.current = isError;

    if (isError && !wasError) {
      // New error episode — fire the toast (id dedupes any concurrent calls)
      toast.error(
        t('builderMap.tokenError', {
          defaultValue: 'Failed to load tile tokens — some layers may not display.',
        }),
        { id: TOAST_ID },
      );
    }
  }, [isError, t]);
}
