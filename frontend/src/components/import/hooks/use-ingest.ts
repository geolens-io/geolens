import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { uploadFile, getJobStatus, getJobStatusByDataset, retryJob, cancelJob, discoverTables, bulkRegisterTables, getUploadConfig, createVrt } from '@/api/ingest';
import { ApiError, apiFetch } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';
import type { BulkRegisterRequest, VrtCreateRequest, SearchResponse } from '@/types/api';

export function useUploadFile() {
  return useMutation({
    // Wrap so TanStack's injected 2nd arg (context) isn't passed as onProgress.
    mutationFn: (file: File) => uploadFile(file),
  });
}

/**
 * Job statuses a job never transitions out of, so polling must stop.
 *
 * 'fanned_out' is terminal because the parent never transitions again; its
 * children (with their own job IDs) carry forward progress. See SMOKE-v1013-F1.
 *
 * fix(#1556): 'cancelled' joined the set, and the set became a named function
 * rather than an inline condition. This is a DENYLIST — anything missing from
 * it polls /jobs/{id} every 2s for the life of the tab — so it has to be
 * exhaustive over the status enum, and the one place that decides is easier to
 * keep exhaustive than a condition inside a query option. An abandoned
 * presigned upload now settles 'cancelled' instead of 'failed', which is
 * exactly the status that was missing.
 */
export function isTerminalJobStatus(status: string | undefined): boolean {
  return (
    status === 'complete' ||
    status === 'failed' ||
    status === 'fanned_out' ||
    status === 'cancelled'
  );
}

export function useJobStatus(jobId: string | null) {
  // fix(#762): AnalysisJobWatcher mounts in RootLayout with a persist-backed
  // job id, so without this gate a stale tracked job made an anonymous
  // visitor on a public page fire an authenticated-only poll — whose 401
  // logged them out. Sibling useDatasetJobStatus gates identically; once a
  // token appears the poll resumes and the watcher resolves the stale job.
  const hasToken = useAuthStore((s) => !!s.token);
  return useQuery({
    queryKey: queryKeys.ingest.jobStatus(jobId),
    queryFn: () => getJobStatus(jobId!),
    enabled: !!jobId && hasToken,
    staleTime: 2000,
    // fix(#1778): a 401/403/404 on the status read is definitive (gone or no
    // longer ours), matching AnalysisJobWatcher's `gone` check — stop polling
    // rather than hammering the endpoint every 2s for the life of the tab.
    refetchInterval: (query) => {
      if (isTerminalJobStatus(query.state.data?.status)) return false;
      const error = query.state.error;
      if (error instanceof ApiError && [401, 403, 404].includes(error.status)) return false;
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
  const hasToken = useAuthStore((s) => !!s.token);

  return useQuery({
    queryKey: queryKeys.ingest.jobStatusByDataset(datasetId),
    queryFn: () => getJobStatusByDataset(datasetId!),
    enabled: !!datasetId && hasToken,
    // The ingest job's warning metadata is immutable once the dataset
    // exists, so cache forever and hold it in memory across tab switches.
    // PERF-2: Infinity staleTime avoids refetch-on-mount; gcTime keeps
    // 404 ("no job") responses in cache so repeat navigations don't
    // re-hit the endpoint.
    staleTime: Infinity,
    gcTime: 30 * 60 * 1000,
    // Don't retry on 404 — that's the "no job" case, not a transient failure.
    // Don't retry on 401 — anonymous public dataset pages should not emit
    // repeated protected-job endpoint failures if auth state changes mid-load.
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      if (error instanceof ApiError && error.status === 401) return false;
      return failureCount < 2;
    },
  });
}

/**
 * fix(#438): DATA-01 — retrying used to leave the cached status on 'failed'.
 * `useJobStatus`'s `refetchInterval` treats 'failed' as terminal and returns
 * false, so polling never restarted: the job re-ran on the worker while the UI
 * sat frozen on "failed" forever. Invalidating the job's status query forces a
 * refetch, the fresh 'pending' status re-arms the interval, and progress
 * resumes.
 */
export function useRetryJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: retryJob,
    onSuccess: (_data, jobId) => {
      qc.invalidateQueries({ queryKey: queryKeys.ingest.jobStatus(jobId) });
    },
  });
}

// fix(#1778): #1709 granted job-creator cancel server-side but shipped no
// caller for it on the import surfaces the creator actually uses (JobProgress
// terminates every import path) — only the admin job list and the refresh-run
// history reached /jobs/{id}/cancel. Same shape as useCancelAdminJob
// (hooks/use-admin.ts), scoped to the ingest job-status query import owns.
export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: (_data, jobId) => {
      qc.invalidateQueries({ queryKey: queryKeys.ingest.jobStatus(jobId) });
    },
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

/**
 * fix(#438): DATA-07 — newly registered datasets were missing from the catalog
 * for up to 30s (the `search` staleTime) because nothing invalidated after the
 * register call.
 */
export function useBulkRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (request: BulkRegisterRequest) => bulkRegisterTables(request),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.all });
      qc.invalidateQueries({ queryKey: queryKeys.search.all });
      qc.invalidateQueries({ queryKey: queryKeys.ingest.discoverTables });
    },
  });
}

export function useUploadConfig() {
  // The payload carries per-user `remaining_dataset_quota`, which changes on any
  // import or delete — so it is NOT static config and must not be cached like
  // it. (Codex P2 on PR #274)
  //   - key scoped by user id: a stale per-user value can't leak across an
  //     account switch (logout only clears auth.me).
  //   - staleTime 0 + refetchOnMount 'always': returning to Import after a
  //     delete/import elsewhere re-reads the live count (a same-mount "Upload
  //     More" is additionally handled by invalidate-on-reset in UploadForm).
  const userId = useAuthStore((s) => s.user?.id);
  return useQuery({
    queryKey: [...queryKeys.ingest.uploadConfig, userId ?? 'anon'],
    queryFn: getUploadConfig,
    staleTime: 0,
    refetchOnMount: 'always',
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
