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
 * Fetch an authenticated map thumbnail and return its cached blob URL.
 * The query cache owns URL revocation because consumers share the cached URL.
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
      // fix(#438): PERF-05 — `cache: 'reload'` intentionally bypasses the HTTP
      // cache so a thumbnail regenerated after an edit is never stale. Upgrade
      // path: version the thumbnail URL, then this can drop to `cache: 'default'`.
      const blob = await apiFetchBlob(thumbnailPath!, { cache: 'reload' });
      return URL.createObjectURL(blob);
    },
    enabled: !!thumbnailPath,
    staleTime: 60 * 1000, // 1 minute: thumbnails regenerate on re-capture
    gcTime: 10 * 60_000,
  });

  return src;
}
