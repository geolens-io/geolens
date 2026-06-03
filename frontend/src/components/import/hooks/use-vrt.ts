import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
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
    queryKey: queryKeys.vrt.sources(datasetId),
    queryFn: () => listVrtSources(datasetId),
    enabled: !!datasetId,
    staleTime: 120_000,
  });
}

export function useAddVrtSource(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceDatasetId: string) => addVrtSource(datasetId, sourceDatasetId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.vrt.sources(datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(datasetId) });
      // REMED-01 (ingest-audit P2-06): adding a source triggers a VRT
      // regeneration job — invalidate the dataset-detail warnings banner
      // so it refetches the new job's warnings (staleTime: Infinity).
      qc.invalidateQueries({ queryKey: queryKeys.ingest.jobStatusByDataset(datasetId) });
    },
  });
}

export function useRemoveVrtSource(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceDatasetId: string) => removeVrtSource(datasetId, sourceDatasetId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.vrt.sources(datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(datasetId) });
      // REMED-01 (ingest-audit P2-06): see useAddVrtSource for rationale.
      qc.invalidateQueries({ queryKey: queryKeys.ingest.jobStatusByDataset(datasetId) });
    },
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

export function useRegenerateVrt(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => regenerateVrt(datasetId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.vrt.sources(datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.vrt.status(datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.vrt.generations(datasetId) });
      // REMED-01 (ingest-audit P2-06): regenerate creates a new ingest job
      // — invalidate the dataset-detail warnings banner so it refetches.
      qc.invalidateQueries({ queryKey: queryKeys.ingest.jobStatusByDataset(datasetId) });
    },
  });
}
