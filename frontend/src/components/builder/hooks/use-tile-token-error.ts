/**
 * useTileTokenError
 *
 * Surfaces a deduped toast.error when the builder's tile-token batch query
 * fails, mirroring the viewer's tokenError pattern (use-viewer-tokens.ts).
 *
 * The toast uses a stable `id` so repeated renders in the error state don't
 * stack toasts; the hook tracks the previous `isError` so a new error episode
 * (false→true) fires a fresh one.
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
      // New error episode: fire the toast (the id dedupes concurrent calls)
      toast.error(
        t('builderMap.tokenError', {
          defaultValue: 'Failed to load tile tokens — some layers may not display.',
        }),
        { id: TOAST_ID },
      );
    }
  }, [isError, t]);
}
