import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { queryKeys } from '@/lib/query-keys';

interface UseQuicklookResult {
  src: string | null;
  isLoading: boolean;
  isError: boolean;
}

/**
 * Fetches a quicklook thumbnail for a dataset and manages blob URL lifecycle.
 * Returns null immediately for null datasetId (e.g., collections).
 *
 * Uses TanStack Query so the result is cached and benefits from React Query's
 * lifecycle. Auth token is read from the zustand store directly (outside React
 * render) since apiFetch assumes JSON responses and cannot handle blobs.
 *
 * Blob URLs are revoked when the component unmounts or the URL changes to
 * prevent memory leaks.
 */
export function useQuicklook(datasetId: string | null): UseQuicklookResult {
  const prevUrlRef = useRef<string | null>(null);

  const { data: src = null, isLoading, isError } = useQuery({
    queryKey: queryKeys.datasets.quicklook(datasetId!),
    queryFn: async () => {
      const token = useAuthStore.getState().token;
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const r = await fetch(`/api/datasets/${datasetId}/quicklook?size=256`, { headers });
      if (!r.ok) throw new Error(String(r.status));
      const blob = await r.blob();
      return URL.createObjectURL(blob);
    },
    enabled: !!datasetId,
    staleTime: 5 * 60 * 1000,
    retry: false,
    meta: { skipGlobalError: true },
  });

  // Revoke previous blob URL when it changes or on unmount
  useEffect(() => {
    if (prevUrlRef.current && prevUrlRef.current !== src) {
      URL.revokeObjectURL(prevUrlRef.current);
    }
    prevUrlRef.current = src;
    return () => {
      if (prevUrlRef.current) {
        URL.revokeObjectURL(prevUrlRef.current);
      }
    };
  }, [src]);

  return { src, isLoading, isError };
}
