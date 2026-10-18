import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { fetchEdition } from '@/api/edition';

const EMPTY_FEATURES: string[] = [];

// Bounded staleTime so a tenancy_mode change (e.g. rolling upgrade to
// multi_tenant) reaches existing clients within 5 minutes without a hard reload.
const EDITION_STALE_MS = 5 * 60 * 1000; // 5 minutes

export function useEdition() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.edition.info,
    queryFn: fetchEdition,
    staleTime: EDITION_STALE_MS,
    gcTime: Infinity,
  });

  return {
    edition: data?.edition ?? 'community',
    features: data?.features ?? EMPTY_FEATURES,
    isEnterprise: data?.edition === 'enterprise',
    isMultiTenant: data?.tenancy_mode === 'multi_tenant',
    isLoading,
    // True once the edition endpoint has answered (a response without
    // tenancy_mode IS a resolved single-tenant deployment). Consumers that must
    // not guess the tenancy mode (useSettingsAdmin) fail closed on this.
    isResolved: data !== undefined,
  };
}
