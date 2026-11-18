import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import {
  listVrtSources,
  getVrtStatus,
  getVrtGenerations,
  regenerateVrt,
  isDatasetBusy,
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

  // A rebuild seen in the history may not be in the cached dataset detail
  // (raster status, tile URL), and member health can change when one ends.
  const newest = query.data?.generations[0];
  const newestId = newest?.id;
  const inProgress = newestInProgress(query.data);
  const wasInProgress = useRef(false);
  const lastNewestId = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!datasetId) return;
    const changed = lastNewestId.current !== undefined && newestId !== lastNewestId.current;
    if (inProgress || changed) {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(datasetId) });
    }
    if (wasInProgress.current && !inProgress) {
      qc.invalidateQueries({ queryKey: queryKeys.vrt.sources(datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.vrt.status(datasetId) });
    }
    wasInProgress.current = inProgress;
    lastNewestId.current = newestId;
  }, [qc, datasetId, inProgress, newestId]);

  return query;
}

function invalidateVrt(qc: ReturnType<typeof useQueryClient>, datasetId: string) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(datasetId) }),
    qc.invalidateQueries({ queryKey: queryKeys.vrt.sources(datasetId) }),
    qc.invalidateQueries({ queryKey: queryKeys.vrt.status(datasetId) }),
    qc.invalidateQueries({ queryKey: queryKeys.vrt.generationsAll(datasetId) }),
  ]);
}

export function useRegenerateVrt(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => regenerateVrt(datasetId),
    // Returning the promise keeps the mutation pending, and the button disabled, until the refetches land.
    onSuccess: async () => {
      // A history read already in flight predates the rebuild; restart it.
      await qc.cancelQueries({ queryKey: queryKeys.vrt.generationsAll(datasetId) });
      await invalidateVrt(qc, datasetId);
    },
    // Someone else started the rebuild: pick it up so the page shows it.
    onError: (err) => {
      if (isDatasetBusy(err)) return invalidateVrt(qc, datasetId);
    },
  });
}
