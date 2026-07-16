import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetchBlob, ApiError } from '@/api/client';
import { isQuicklookKnownMissing, markQuicklookMissing } from '@/lib/quicklook-cache';
import { registerBlobUrlRevocation } from '@/lib/blob-url-cache';

export interface UseQuicklookResult {
  url: string | null;
  status: 'idle' | 'loading' | 'ready' | 'missing' | 'error';
}

/**
 * useQuicklook — fetch an authenticated quicklook thumbnail and return it as
 * a blob URL.
 *
 * Solves the Bearer-JWT mismatch: browser <img src> requests do NOT carry
 * Authorization headers, so quicklooks for private datasets returned 404.
 * This hook routes every request through apiFetchBlob (which attaches the
 * Bearer token from useAuthStore automatically) and exposes the result as a
 * blob: URL suitable for use as an <img src>.
 *
 * SP-07 negative-cache reference: datasets whose file is genuinely missing on
 * disk (has_quicklook=true but storage file absent) return 404 even with a
 * valid JWT. Those are cached in quicklook-cache.ts for the session so we
 * don't re-fetch them on re-render.
 *
 * Hooks are called unconditionally and the fetch is gated with `enabled` —
 * an early return for null/known-missing ids would change the hook count on
 * the render AFTER a 404 populates the negative cache ("Rendered fewer hooks
 * than expected", crashing the consumer to its error boundary).
 *
 * Blob URL lifecycle: the blob URL is cached in React Query under the
 * quicklook key and shared across consumers. Revocation is tied to the QUERY
 * CACHE (eviction / refetch-replacement) via registerBlobUrlRevocation, NOT to
 * component unmount — revoking on unmount left the dead URL in cache and caused
 * ERR_FILE_NOT_FOUND for the next consumer. See lib/blob-url-cache.ts.
 */
export function useQuicklook(
  datasetId: string | null,
  size: number = 256,
): UseQuicklookResult {
  const queryClient = useQueryClient();
  useEffect(() => { registerBlobUrlRevocation(queryClient); }, [queryClient]);

  const knownMissing = datasetId != null && isQuicklookKnownMissing(datasetId);

  const {
    data,
    isPending,
    error,
  } = useQuery({
    queryKey: ['quicklook', datasetId, size],
    queryFn: async () => {
      const blob = await apiFetchBlob(`/datasets/${datasetId}/quicklook?size=${size}`);
      return URL.createObjectURL(blob);
    },
    enabled: datasetId != null && !knownMissing,
    staleTime: 5 * 60_000,
    gcTime: 10 * 60_000,
    retry: false,
  });

  if (datasetId == null) {
    return { url: null, status: 'idle' };
  }
  if (knownMissing) {
    return { url: null, status: 'missing' };
  }

  // Handle 404 negative-caching — idempotent, so safe to call during render
  if (error instanceof ApiError && error.status === 404) {
    markQuicklookMissing(datasetId);
    return { url: null, status: 'missing' };
  }

  // Derive status
  if (typeof data === 'string') {
    return { url: data, status: 'ready' };
  }
  if (isPending) {
    return { url: null, status: 'loading' };
  }
  if (error) {
    return { url: null, status: 'error' };
  }

  return { url: null, status: 'idle' };
}
