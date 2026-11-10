import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetchBlob } from '@/api/client';
import { registerBlobUrlRevocation } from '@/lib/blob-url-cache';
import { queryKeys } from '@/lib/query-keys';

/**
 * Fetches an image from the API with the reader's credentials, once `enabled`,
 * and returns a blob URL for it, or `failed` when it's missing or not theirs
 * to see. The object under an image's path never changes, so the URL stays
 * cached; the query cache revokes it.
 */
export function useAssetImage(path: string | null, enabled = true): { src: string | null; failed: boolean } {
  const queryClient = useQueryClient();
  useEffect(() => {
    registerBlobUrlRevocation(queryClient);
  }, [queryClient]);
  const { data, isError } = useQuery({
    queryKey: queryKeys.stories.image(path ?? ''),
    queryFn: async ({ signal }) => URL.createObjectURL(await apiFetchBlob(path!, { signal })),
    enabled: enabled && path !== null,
    staleTime: Infinity,
    gcTime: 10 * 60_000,
    retry: false,
  });
  return { src: data ?? null, failed: isError };
}
