import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { queryKeys } from '@/lib/query-keys';

const CHECK_INTERVAL_MS = 15 * 60 * 1000;
// /health runs real probes and is rate limited, so a refocus within a minute
// of the last check reuses it.
const STALE_MS = 60 * 1000;

// npm writes 1.4.0-rc.1 where Python metadata (PEP 440) writes 1.4.0rc1.
function normalizeVersion(v: string): string {
  return v
    .trim()
    .toLowerCase()
    .replace(/[-._]?(alpha|beta|a|b|rc)[-._]?(\d)/, (_m, tag: string, d: string) => {
      const t = tag === 'alpha' ? 'a' : tag === 'beta' ? 'b' : tag;
      return `${t}${d}`;
    });
}

/**
 * The server's version when it differs from this bundle's, else null. Checked
 * when the tab becomes visible and every 15 minutes while it is. A missing or
 * empty version on either side (dev builds) or a failed request yields null.
 */
export function useNewServerVersion(): string | null {
  const { data } = useQuery({
    queryKey: queryKeys.serverVersion,
    // A failure resolves to unknown so it is cached for the stale window and
    // replaces an earlier answer instead of leaving a stale banner up.
    queryFn: async () => {
      try {
        const body = await apiFetch<{ version?: string | null }>('/health');
        return body?.version ?? null;
      } catch {
        return null;
      }
    },
    staleTime: STALE_MS,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: CHECK_INTERVAL_MS,
  });
  const bundle = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '';
  if (!bundle || !data || normalizeVersion(data) === normalizeVersion(bundle)) return null;
  return data;
}
