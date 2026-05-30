import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetchBlob } from '@/api/client';
import { registerBlobUrlRevocation } from '@/lib/blob-url-cache';

function withThumbnailVersion(
  thumbnailUrl: string | null | undefined,
  version: string | null | undefined,
): string | null {
  if (!thumbnailUrl) return null;
  if (!version) return thumbnailUrl;

  const separator = thumbnailUrl.includes('?') ? '&' : '?';
  return `${thumbnailUrl}${separator}v=${encodeURIComponent(version)}`;
}

/**
 * useMapThumbnail — fetch an authenticated map thumbnail and return it as a
 * blob URL.
 *
 * Routes the request through apiFetchBlob (which attaches the Bearer token
 * from useAuthStore automatically) so authed thumbnails work as <img src>.
 *
 * Blob URL lifecycle: the blob URL is cached in React Query under the
 * thumbnail key and shared across all consumers. Revocation is tied to the
 * QUERY CACHE (eviction / refetch-replacement) via registerBlobUrlRevocation,
 * NOT to component unmount — revoking on unmount left the dead URL in cache and
 * caused ERR_FILE_NOT_FOUND for the next consumer (list↔grid toggle, back-nav,
 * StrictMode remount). See SF-05 history and lib/blob-url-cache.ts.
 */
export function useMapThumbnail(
  thumbnailUrl: string | null | undefined,
  version?: string | null,
): string | null {
  const thumbnailPath = withThumbnailVersion(thumbnailUrl, version);
  const queryClient = useQueryClient();
  useEffect(() => { registerBlobUrlRevocation(queryClient); }, [queryClient]);

  const { data: src = null } = useQuery({
    queryKey: ['map-thumbnail', thumbnailUrl, version],
    queryFn: async () => {
      const blob = await apiFetchBlob(thumbnailPath!, { cache: 'reload' });
      return URL.createObjectURL(blob);
    },
    enabled: !!thumbnailPath,
    staleTime: 60 * 1000, // 1 minute: thumbnails regenerate on re-capture
    gcTime: 10 * 60_000,
  });

  return src;
}
