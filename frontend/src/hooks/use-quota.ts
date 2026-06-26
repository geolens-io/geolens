import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { getMyUsage } from '@/api/auth';
import { useAuth } from '@/hooks/use-auth';

/** The signed-in user's own storage + dataset quota usage. Lazy: only loaded
 *  where imported (SettingsPage), unlike useAuth which fires app-wide. */
export function useMyUsage() {
  const { user } = useAuth();
  return useQuery({
    queryKey: queryKeys.auth.usage(user?.id),
    queryFn: getMyUsage,
    enabled: !!user,
    // Usage changes on every upload/delete, so re-read it each time the user
    // opens Settings rather than serving a stale used/cap figure. Mirrors the
    // per-user remaining_dataset_quota handling in useUploadConfig
    // (components/import/hooks/use-ingest.ts).
    staleTime: 0,
    refetchOnMount: 'always',
  });
}
