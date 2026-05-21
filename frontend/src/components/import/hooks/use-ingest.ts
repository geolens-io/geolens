import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { uploadFile, getJobStatus, getJobStatusByDataset, retryJob, discoverTables, bulkRegisterTables, getUploadConfig, createVrt } from '@/api/ingest';
import { ApiError, apiFetch } from '@/api/client';
import type { BulkRegisterRequest, VrtCreateRequest, SearchResponse } from '@/types/api';

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
    staleTime: 2000,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      // 'fanned_out' is terminal — the parent never transitions again; children
      // (with their own job IDs) carry forward progress. See SMOKE-v1013-F1.
      if (status === 'complete' || status === 'failed' || status === 'fanned_out') return false;
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
    staleTime: 30_000,
  });
}

/**
 * For IMPORT-05: distinguish 'all registered' (success framing) from
 * 'no tables exist' (absence framing) in the Register Table empty state.
 *
 * Cheap GET with limit=1 — backend returns numberMatched in the response.
 * Only fires when enabled === true (i.e. tables.length === 0 and not loading).
 */
export function useDatasetCountHint(enabled: boolean) {
  return useQuery({
    queryKey: ['datasets', 'count-hint'],
    queryFn: async () => {
      const data = await apiFetch<SearchResponse>('/search/datasets/?limit=1');
      return data.numberMatched ?? 0;
    },
    enabled,
    staleTime: 60_000,
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
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (request: VrtCreateRequest) => createVrt(request),
    // REMED-01 (ingest-audit P2-06): VrtCreateResponse exposes `job_id`
    // only (no `dataset_id` — the VRT dataset row is created later as
    // part of the ingest job). Invalidate the jobStatus cache for the
    // new job so any subscribed UI (e.g., the polling job-status
    // banner via useJobStatus) refetches immediately rather than
    // waiting for the next 2s interval.
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: queryKeys.ingest.jobStatus(data.job_id) });
    },
  });
}
