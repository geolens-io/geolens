import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import {
  listVrtSources,
  getVrtStatus,
  getVrtGenerations,
  regenerateVrt,
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

function invalidateVrt(qc: ReturnType<typeof useQueryClient>, datasetId: string) {
  qc.invalidateQueries({ queryKey: queryKeys.vrt.sources(datasetId) });
  qc.invalidateQueries({ queryKey: queryKeys.vrt.status(datasetId) });
  qc.invalidateQueries({ queryKey: queryKeys.vrt.generationsAll(datasetId) });
}

export function useRegenerateVrt(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => regenerateVrt(datasetId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(datasetId) });
      invalidateVrt(qc, datasetId);
    },
  });
}

/** Refetches the VRT's sources, status and history once a rebuild ends. */
export function useRefreshVrtWhenRebuilt(datasetId: string, isRegenerating: boolean) {
  const qc = useQueryClient();
  const wasRegenerating = useRef(isRegenerating);
  useEffect(() => {
    if (wasRegenerating.current && !isRegenerating && datasetId) invalidateVrt(qc, datasetId);
    wasRegenerating.current = isRegenerating;
  }, [qc, datasetId, isRegenerating]);
}
