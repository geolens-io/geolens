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
  const queryClient = useQueryClient();
  useEffect(() => { registerBlobUrlRevocation(queryClient); }, [queryClient]);

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
