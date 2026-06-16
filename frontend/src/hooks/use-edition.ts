import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { fetchEdition } from '@/api/edition';
import type { EditionInfo } from '@/api/edition';

const EMPTY_FEATURES: string[] = [];

// IN-01 (Phase 1212): bounded staleTime so a tenancy_mode change (e.g. rolling
// upgrade from single_tenant → multi_tenant) propagates to existing clients
// within 5 minutes without requiring a hard reload.  gcTime stays longer so
// the data survives short navigations while still being refetched periodically.
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
  };
}

export type { EditionInfo };
