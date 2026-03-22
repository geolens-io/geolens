import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listVrtSources,
  addVrtSource,
  removeVrtSource,
  getVrtStatus,
  getVrtGenerations,
  regenerateVrt,
} from '@/api/vrt';

export function useVrtSources(datasetId: string) {
  return useQuery({
    queryKey: ['vrt-sources', datasetId],
    queryFn: () => listVrtSources(datasetId),
    enabled: !!datasetId,
  });
}

export function useAddVrtSource(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceDatasetId: string) => addVrtSource(datasetId, sourceDatasetId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['vrt-sources', datasetId] });
      qc.invalidateQueries({ queryKey: ['dataset', datasetId] });
    },
  });
}

export function useRemoveVrtSource(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceDatasetId: string) => removeVrtSource(datasetId, sourceDatasetId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['vrt-sources', datasetId] });
      qc.invalidateQueries({ queryKey: ['dataset', datasetId] });
    },
  });
}

export function useVrtStatus(datasetId: string, isRegenerating: boolean) {
  return useQuery({
    queryKey: ['vrt-status', datasetId],
    queryFn: () => getVrtStatus(datasetId),
    enabled: !!datasetId,
    refetchInterval: isRegenerating ? 3_000 : false,
  });
}

export function useVrtGenerations(datasetId: string, params?: { limit?: number; offset?: number }) {
  return useQuery({
    queryKey: ['vrt-generations', datasetId, params],
    queryFn: () => getVrtGenerations(datasetId, params),
    enabled: !!datasetId,
  });
}

export function useRegenerateVrt(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => regenerateVrt(datasetId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dataset', datasetId] });
      qc.invalidateQueries({ queryKey: ['vrt-sources', datasetId] });
      qc.invalidateQueries({ queryKey: ['vrt-status', datasetId] });
      qc.invalidateQueries({ queryKey: ['vrt-generations', datasetId] });
    },
  });
}
