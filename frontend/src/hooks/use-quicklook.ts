import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { queryKeys } from '@/lib/query-keys';

interface UseQuicklookResult {
  src: string | null;
  isLoading: boolean;
}

/**
 * Fetches a quicklook thumbnail for a dataset as a data URL.
 * Returns null immediately for null datasetId (e.g., collections,
 * tables, or datasets without stored quicklooks).
 *
 * Uses TanStack Query so the result is cached. Auth token is read from the
 * zustand store directly (outside React render) since apiFetch assumes JSON.
 *
 * Uses base64 data URLs instead of blob URLs to avoid revocation race
 * conditions with React concurrent rendering.
 */
export function useQuicklook(datasetId: string | null): UseQuicklookResult {
  const { data: src = null, isLoading } = useQuery({
    queryKey: queryKeys.datasets.quicklook(datasetId!),
    queryFn: async () => {
      const token = useAuthStore.getState().token;
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const r = await fetch(`/api/datasets/${datasetId}/quicklook?size=256`, { headers });
      if (!r.ok) throw new Error(String(r.status));
      const blob = await r.blob();
      return new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result as string);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    },
    enabled: !!datasetId,
    staleTime: 5 * 60 * 1000,
    retry: false,
    meta: { skipGlobalError: true },
  });

  return { src, isLoading };
}
