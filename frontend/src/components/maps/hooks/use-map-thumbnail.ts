import { useQuery } from '@tanstack/react-query';
import { apiFetchBlob } from '@/api/client';

export function useMapThumbnail(thumbnailUrl: string | null | undefined): string | null {
  const { data: src = null } = useQuery({
    queryKey: ['map-thumbnail', thumbnailUrl],
    queryFn: async () => {
      const blob = await apiFetchBlob(thumbnailUrl!);
      return URL.createObjectURL(blob);
    },
    enabled: !!thumbnailUrl,
    staleTime: 60 * 1000, // 1 minute: thumbnails regenerate on re-capture
    gcTime: 10 * 60_000,
  });

  return src;
}
