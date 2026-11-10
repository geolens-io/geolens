import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { listMyGroups } from '@/api/groups';

export function useMyGroups(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.groups.mine,
    queryFn: listMyGroups,
    enabled,
    staleTime: 60_000,
  });
}
