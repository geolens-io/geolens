import { useMutation, useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { uploadFile, registerTable, getJobStatus, previewFile, commitImport, retryJob, probeService, previewServiceLayer, discoverTables, bulkRegisterTables, getUploadConfig, createVrt } from '@/api/ingest';
import type { CommitImportRequest, ServicePreviewRequest, BulkRegisterRequest, VrtCreateRequest } from '@/types/api';

export function useUploadFile() {
  return useMutation({
    mutationFn: uploadFile,
  });
}

export function useRegisterTable() {
  return useMutation({
    mutationFn: registerTable,
  });
}

export function useJobStatus(jobId: string | null) {
  return useQuery({
    queryKey: queryKeys.ingest.jobStatus(jobId),
    queryFn: () => getJobStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === 'complete' || status === 'failed') return false;
      return 2000;
    },
  });
}

export function usePreviewFile() {
  return useMutation({
    mutationFn: (jobId: string) => previewFile(jobId),
  });
}

export function useCommitImport() {
  return useMutation({
    mutationFn: ({ jobId, request }: { jobId: string; request: CommitImportRequest }) =>
      commitImport(jobId, request),
  });
}

export function useRetryJob() {
  return useMutation({
    mutationFn: retryJob,
  });
}

export function useProbeService() {
  return useMutation({
    mutationFn: ({ url, token }: { url: string; token?: string }) =>
      probeService(url, token),
  });
}

export function usePreviewServiceLayer() {
  return useMutation({
    mutationFn: (request: ServicePreviewRequest) => previewServiceLayer(request),
  });
}

export function useDiscoverTables() {
  return useQuery({
    queryKey: queryKeys.ingest.discoverTables,
    queryFn: discoverTables,
  });
}

export function useBulkRegister() {
  return useMutation({
    mutationFn: (request: BulkRegisterRequest) => bulkRegisterTables(request),
  });
}

export function useUploadConfig() {
  return useQuery({
    queryKey: queryKeys.ingest.uploadConfig,
    queryFn: getUploadConfig,
    staleTime: 300_000, // 5 minutes -- storage provider changes rarely
  });
}

export function useCreateVrt() {
  return useMutation({
    mutationFn: (request: VrtCreateRequest) => createVrt(request),
  });
}
