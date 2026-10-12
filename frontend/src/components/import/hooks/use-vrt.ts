import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import {
  listVrtSources,
  getVrtStatus,
  getVrtGenerations,
} from '@/api/vrt';

export function useVrtSources(datasetId: string) {
  return useQuery({
    queryKey: queryKeys.vrt.sources(datasetId),
    queryFn: () => listVrtSources(datasetId),
    enabled: !!datasetId,
    staleTime: 120_000,
  });
}

export function useVrtStatus(datasetId: string, isRegenerating: boolean) {
  return useQuery({
    queryKey: queryKeys.vrt.status(datasetId),
    queryFn: () => getVrtStatus(datasetId),
    enabled: !!datasetId,
    refetchInterval: isRegenerating ? 3_000 : false,
  });
}

export function useVrtGenerations(datasetId: string, params?: { limit?: number; offset?: number }) {
  return useQuery({
    queryKey: queryKeys.vrt.generations(datasetId, params),
    queryFn: () => getVrtGenerations(datasetId, params),
    enabled: !!datasetId,
    staleTime: 120_000,
  });
}
