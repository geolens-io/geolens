import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { queryKeys } from '@/lib/query-keys';

const CHECK_INTERVAL_MS = 15 * 60 * 1000;

/**
 * The server's version when it differs from this bundle's, else null. Checked
 * when the tab becomes visible and every 15 minutes while it is. A missing or
 * empty version on either side (dev builds) or a failed request yields null.
 */
export function useNewServerVersion(): string | null {
  const { data } = useQuery({
    queryKey: queryKeys.serverVersion,
    queryFn: () => apiFetch<{ version?: string | null }>('/health'),
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: CHECK_INTERVAL_MS,
    select: (d) => d?.version ?? null,
  });
  const bundle = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '';
  if (!bundle || !data || data === bundle) return null;
  return data;
}
