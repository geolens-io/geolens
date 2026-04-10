import { useMutation, useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { uploadFile, getJobStatus, getJobStatusByDataset, retryJob, discoverTables, bulkRegisterTables, getUploadConfig, createVrt } from '@/api/ingest';
import { ApiError } from '@/api/client';
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

/**
 * Fetch the most recent ingest job for a dataset (S3 completion).
 *
 * Powers the persistent warnings banner on DatasetPage. A 404 from the
 * backend just means the dataset was registered from an existing table
 * (no ingest job) — treat it as "no warnings" rather than an error.
 */
export function useDatasetJobStatus(datasetId: string | null) {
  return useQuery({
    queryKey: queryKeys.ingest.jobStatusByDataset(datasetId),
    queryFn: () => getJobStatusByDataset(datasetId!),
    enabled: !!datasetId,
    // The ingest job's warning metadata is immutable once the dataset
    // exists, so cache forever and hold it in memory across tab switches.
    // PERF-2: Infinity staleTime avoids refetch-on-mount; gcTime keeps
    // 404 ("no job") responses in cache so repeat navigations don't
    // re-hit the endpoint.
    staleTime: Infinity,
    gcTime: 30 * 60 * 1000,
    // Don't retry on 404 — that's the "no job" case, not a transient failure.
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failureCount < 2;
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
