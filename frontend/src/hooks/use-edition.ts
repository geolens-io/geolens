import { useQuery } from '@tanstack/react-query';
import { fetchEdition } from '@/api/edition';
import type { EditionInfo } from '@/api/edition';

export function useEdition() {
  const { data, isLoading } = useQuery({
    queryKey: ['edition'],
    queryFn: fetchEdition,
    staleTime: Infinity,
    gcTime: Infinity,
  });

  return {
    edition: data?.edition ?? 'community',
    features: data?.features ?? [],
    isEnterprise: data?.edition === 'enterprise',
    isLoading,
  };
}

export type { EditionInfo };
