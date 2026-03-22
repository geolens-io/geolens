import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { getMyPermissions } from '@/api/auth';

export function usePermissions() {
  const token = useAuthStore((s) => s.token);

  const { data, isLoading } = useQuery({
    queryKey: ['auth', 'permissions'],
    queryFn: getMyPermissions,
    enabled: !!token,
    staleTime: 60_000,
  });

  const permissions = data?.permissions ?? null;

  function can(capability: string): boolean {
    if (!permissions) return false;
    return permissions[capability] === true;
  }

  return { permissions, can, isLoading };
}
