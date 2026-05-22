import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiFetchBlob, ApiError } from '@/api/client';
import { isQuicklookKnownMissing, markQuicklookMissing } from '@/lib/quicklook-cache';

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
 * Blob URL lifecycle: URL.revokeObjectURL is called on unmount AND on
 * datasetId change (via the useEffect cleanup on [data]) to prevent memory
 * leaks.
 */
export function useQuicklook(
  datasetId: string | null,
  size: number = 256,
): UseQuicklookResult {
  // Short-circuit: no dataset — idle
  if (datasetId == null) {
    return { url: null, status: 'idle' };
  }

  // Short-circuit: already known missing for this session — don't fetch
  if (isQuicklookKnownMissing(datasetId)) {
    return { url: null, status: 'missing' };
  }

  // eslint-disable-next-line react-hooks/rules-of-hooks -- early return only happens when hooks aren't needed (datasetId is null or missing)
  return useQuicklookQuery(datasetId, size);
}

// Separated inner hook so the early-return pattern above doesn't violate React
// hooks exhaustive-deps lint; all conditional logic happens before any hook calls.
function useQuicklookQuery(datasetId: string, size: number): UseQuicklookResult {
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
    enabled: true,
    staleTime: 5 * 60_000,
    gcTime: 10 * 60_000,
    retry: false,
  });

  // Revoke blob URL when data changes (new dataset) or on unmount
  useEffect(() => {
    if (typeof data === 'string') {
      return () => {
        URL.revokeObjectURL(data);
      };
    }
  }, [data]);

  // Handle 404 negative-caching — must happen after hooks, but before return
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
