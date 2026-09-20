import { useEffect, useRef } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createDatasetSync,
  createSyncCredential,
  deleteDatasetSync,
  deleteSyncCredential,
  getDatasetSync,
  listSyncCredentials,
  pauseDatasetSync,
  replaceSyncCredential,
  resumeDatasetSync,
  runDatasetSync,
  updateDatasetSync,
  type CreateSyncAutomationRequest,
  type CreateSyncCredentialRequest,
  type ReplaceSyncCredentialRequest,
  type UpdateSyncAutomationRequest,
} from '@/api/dataset-sync';
import { queryKeys } from '@/lib/query-keys';

function invalidateSyncDerivedData(queryClient: ReturnType<typeof useQueryClient>, datasetId: string) {
  queryClient.invalidateQueries({ queryKey: queryKeys.datasets.sync(datasetId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.datasets.detail(datasetId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.datasets.refreshRunsPrefix(datasetId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.datasets.versionsPrefix(datasetId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.datasets.rowsPrefix(datasetId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.datasets.maps(datasetId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.maps.columnValuesPrefix(datasetId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.maps.columnStatsPrefix(datasetId) });
}

export function useDatasetSync(datasetId: string, enabled: boolean) {
  const queryClient = useQueryClient();
  const priorOccurrenceRef = useRef<{ id: string; state: string } | null>(null);
  const query = useQuery({
    queryKey: queryKeys.datasets.sync(datasetId),
    queryFn: () => getDatasetSync(datasetId),
    enabled: enabled && !!datasetId,
    staleTime: 5_000,
    refetchOnWindowFocus: 'always',
    refetchInterval: (queryState) => queryState.state.data ? 10_000 : false,
  });

  useEffect(() => {
    const occurrence = query.data?.last_occurrence;
    if (!occurrence) return;
    const prior = priorOccurrenceRef.current;
    priorOccurrenceRef.current = { id: occurrence.id, state: occurrence.state };
    const completedAfterActive = prior?.id === occurrence.id
      && prior.state === 'claimed'
      && ['completed', 'failed', 'cancelled', 'expired'].includes(occurrence.state);
    if (completedAfterActive) invalidateSyncDerivedData(queryClient, datasetId);
  }, [datasetId, query.data?.last_occurrence, queryClient]);

  return query;
}

export function useSyncCredentials(datasetId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.datasets.syncCredentials(datasetId),
    queryFn: () => listSyncCredentials(datasetId),
    enabled: enabled && !!datasetId,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useCreateDatasetSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, request }: { datasetId: string; request: CreateSyncAutomationRequest }) =>
      createDatasetSync(datasetId, request),
    onSuccess: (_data, variables) => invalidateSyncDerivedData(queryClient, variables.datasetId),
  });
}

export function useUpdateDatasetSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, request }: { datasetId: string; request: UpdateSyncAutomationRequest }) =>
      updateDatasetSync(datasetId, request),
    onSuccess: (_data, variables) => invalidateSyncDerivedData(queryClient, variables.datasetId),
  });
}

export function useDeleteDatasetSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, revision }: { datasetId: string; revision: number }) =>
      deleteDatasetSync(datasetId, revision),
    onSuccess: (_data, variables) => invalidateSyncDerivedData(queryClient, variables.datasetId),
  });
}

export function usePauseDatasetSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, revision }: { datasetId: string; revision: number }) =>
      pauseDatasetSync(datasetId, revision),
    onSuccess: (_data, variables) => invalidateSyncDerivedData(queryClient, variables.datasetId),
  });
}

export function useResumeDatasetSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, revision }: { datasetId: string; revision: number }) =>
      resumeDatasetSync(datasetId, revision),
    onSuccess: (_data, variables) => invalidateSyncDerivedData(queryClient, variables.datasetId),
  });
}

export function useRunDatasetSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, revision }: { datasetId: string; revision?: number }) =>
      runDatasetSync(datasetId, revision),
    onSuccess: (_data, variables) => invalidateSyncDerivedData(queryClient, variables.datasetId),
  });
}

export function useCreateSyncCredential() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateSyncCredentialRequest) => createSyncCredential(request),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.datasets.syncCredentialsPrefix }),
  });
}

export function useReplaceSyncCredential() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ credentialId, request }: { credentialId: string; request: ReplaceSyncCredentialRequest }) =>
      replaceSyncCredential(credentialId, request),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.datasets.syncCredentialsPrefix }),
  });
}

export function useDeleteSyncCredential() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentialId: string) => deleteSyncCredential(credentialId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.datasets.syncCredentialsPrefix }),
  });
}
