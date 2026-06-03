import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { fetchEdition } from '@/api/edition';
import type { EditionInfo } from '@/api/edition';

const EMPTY_FEATURES: string[] = [];

export function useEdition() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.edition.info,
    queryFn: fetchEdition,
    staleTime: Infinity,
    gcTime: Infinity,
  });

  return {
    edition: data?.edition ?? 'community',
    features: data?.features ?? EMPTY_FEATURES,
    isEnterprise: data?.edition === 'enterprise',
    isLoading,
  };
}

export type { EditionInfo };
