import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiFetchBlob } from '@/api/client';

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
 * Blob URL lifecycle: URL.revokeObjectURL is called on unmount AND on
 * mapId change (via the useEffect cleanup on [data]) to prevent memory
 * leaks and post-redirect ERR_FILE_NOT_FOUND console errors (SF-05).
 */
export function useMapThumbnail(
  thumbnailUrl: string | null | undefined,
  version?: string | null,
): string | null {
  const thumbnailPath = withThumbnailVersion(thumbnailUrl, version);

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

  // Revoke blob URL when data changes (new mapId) or on unmount
  useEffect(() => {
    if (typeof src === 'string') {
      return () => {
        URL.revokeObjectURL(src);
      };
    }
  }, [src]);

  return src;
}
