import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import {
  listVrtSources,
  getVrtStatus,
  getVrtGenerations,
  regenerateVrt,
} from '@/api/vrt';
import type { VrtGenerationListResponse } from '@/types/api';

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

const IN_PROGRESS_GENERATION = new Set(['pending', 'running']);

function newestInProgress(data: VrtGenerationListResponse | undefined): boolean {
  const newest = data?.generations[0];
  return !!newest && IN_PROGRESS_GENERATION.has(newest.status);
}

export function useVrtGenerations(datasetId: string, params?: { limit?: number; offset?: number }) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.vrt.generations(datasetId, params),
    queryFn: () => getVrtGenerations(datasetId, params),
    enabled: !!datasetId,
    staleTime: 120_000,
    // A cached in-progress row must not outlive the rebuild it described.
    refetchOnMount: 'always',
    refetchInterval: (q) => (newestInProgress(q.state.data) ? 3_000 : false),
  });

  // Member health can change when a rebuild ends.
  const wasInProgress = useRef(false);
  const inProgress = newestInProgress(query.data);
  useEffect(() => {
    if (wasInProgress.current && !inProgress && datasetId) {
      qc.invalidateQueries({ queryKey: queryKeys.vrt.sources(datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.vrt.status(datasetId) });
    }
    wasInProgress.current = inProgress;
  }, [qc, datasetId, inProgress]);

  return query;
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
