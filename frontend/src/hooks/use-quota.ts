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
    staleTime: 60 * 1000, // 1 min — usage changes on upload/delete
  });
}
