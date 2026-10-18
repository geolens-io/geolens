import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { useAuthStore } from '@/stores/auth-store';
import { getMyPermissions } from '@/api/auth';
import type { Capability } from '@/lib/capabilities';

export function usePermissions() {
  const token = useAuthStore((s) => s.token);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.auth.permissions,
    queryFn: getMyPermissions,
    enabled: !!token,
    staleTime: 60_000,
  });

  const permissions = data?.permissions ?? null;

  // Literal union mirroring backend ALL_CAPABILITIES, so typos fail at compile time.
  function can(capability: Capability): boolean {
    if (!permissions) return false;
    return permissions[capability] === true;
  }

  return { permissions, can, isLoading };
}
