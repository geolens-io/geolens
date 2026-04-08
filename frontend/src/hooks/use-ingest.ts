import { useMutation, useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { uploadFile, getJobStatus, retryJob, discoverTables, bulkRegisterTables, getUploadConfig, createVrt } from '@/api/ingest';
import type { BulkRegisterRequest, VrtCreateRequest } from '@/types/api';

export function useUploadFile() {
  return useMutation({
    mutationFn: uploadFile,
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

export function useRetryJob() {
  return useMutation({
    mutationFn: retryJob,
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
