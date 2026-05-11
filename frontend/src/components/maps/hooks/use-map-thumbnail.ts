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

  return src;
}
