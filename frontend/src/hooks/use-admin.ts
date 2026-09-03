import { useQuery, useQueries, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { queryKeys } from '@/lib/query-keys';
import {
  getCatalogStats,
  listUsers,
  listUserNames,
  listAdminJobs,
  listAuditLogs,
  createUser,
  updateUser,
  deactivateUser,
  resetUserPassword,
  deleteUser,
  approveUser,
  rejectUser,
  listApiKeys,
  createApiKey,
  revokeApiKey,
  getAIStatus,
  listShareTokens,
  adminRevokeShareToken,
  listAdminEmbedTokens,
  bulkRevokeEmbedTokens,
  getInfrastructure,
  getEmbeddingStats,
  triggerBackfill,
  updateSemanticSearch,
} from '@/api/admin';
import type { ApiKeyScope } from '@/types/api';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import { cancelJob, getJobStatus, retryJob } from '@/api/ingest';
import { ApiError } from '@/api/client';
import { logger } from '@/lib/logger';

export function useCatalogStats() {
  return useQuery({
    queryKey: queryKeys.admin.stats,
    queryFn: getCatalogStats,
    staleTime: 30_000,
  });
}

export function useUserList(params: {
  skip: number;
  limit: number;
  status?: string;
  search?: string;
  sort?: string;
  order?: string;
}) {
  const { skip, limit, status, search, sort, order } = params;
  return useQuery({
    queryKey: queryKeys.admin.users(skip, limit, status, search, sort, order),
    queryFn: () => listUsers({ skip, limit, status, search, sort, order }),
    placeholderData: keepPreviousData,
  });
}

export function useUserNames() {
  return useQuery({
    queryKey: queryKeys.admin.userNames,
    queryFn: listUserNames,
    staleTime: 60_000,
  });
}

export function useAuditLogs(params: {
  user_id?: string;
  action?: string;
  resource_type?: string;
  resource_id?: string;
  date_from?: string;
  date_to?: string;
  search?: string;
  skip?: number;
  limit?: number;
  sort?: string;
  order?: string;
}, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.admin.auditLogs(params),
    queryFn: () => listAuditLogs(params),
    placeholderData: keepPreviousData,
    enabled: options?.enabled,
  });
}

// Pending count (for badge)
export function usePendingCount() {
  return useQuery({
    queryKey: queryKeys.admin.pendingCount,
    queryFn: async () => {
      const result = await listUsers({ skip: 0, limit: 1, status: 'pending' });
      return result.total;
    },
    staleTime: 60_000,
  });
}

// Admin jobs
export function useAdminJobs(params: {
  status?: string;
  user_id?: string;
  search?: string;
  skip?: number;
  limit?: number;
  sort?: string;
  order?: string;
}) {
  return useQuery({
    queryKey: queryKeys.admin.jobs(params),
    queryFn: () => listAdminJobs(params),
    placeholderData: keepPreviousData,
  });
}

export function useFailedJobCount(enabled = true) {
  return useQuery({
    queryKey: queryKeys.admin.failedJobCount,
    queryFn: async () => {
      const result = await listAdminJobs({ status: 'failed', limit: 1 });
      return result.total;
    },
    staleTime: 60_000,
    enabled,
  });
}

// #347 (ADM-02): total counts for the Operations sidebar badges (Users, Published
// Maps, Audit Log). Each reads `.total` off a 1-row list query.
export function useUserCount(enabled = true) {
  return useQuery({
    queryKey: queryKeys.admin.userCount,
    queryFn: async () => (await listUsers({ skip: 0, limit: 1 })).total,
    staleTime: 60_000,
    enabled,
  });
}

export function usePublishedMapCount(enabled = true) {
  return useQuery({
    queryKey: queryKeys.admin.publishedMapCount,
    queryFn: async () => (await listShareTokens({ skip: 0, limit: 1 })).total,
    staleTime: 60_000,
    enabled,
  });
}

export function useAuditLogCount(enabled = true) {
  return useQuery({
    queryKey: queryKeys.admin.auditLogCount,
    queryFn: async () => (await listAuditLogs({ skip: 0, limit: 1 })).total,
    staleTime: 60_000,
    enabled,
  });
}

export function useRetryAdminJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => retryJob(jobId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allJobs });
    },
    onError: (err) => {
      logger.error('[useRetryAdminJob]', err);
      toast.error(i18n.t('admin:errors.retryJobFailed'));
    },
  });
}

// feat(#1677): mirror of useRetryAdminJob for the shared /jobs/{id}/cancel
// route — admin cancel reuses it the same way admin retry reuses /retry.
export function useCancelAdminJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allJobs });
    },
    onError: (err) => {
      logger.error('[useCancelAdminJob]', err);
      toast.error(i18n.t('admin:errors.cancelJobFailed'));
    },
  });
}

// User mutations
// fix(#438): UX-08 — these six succeeded silently; the house pattern is a success toast.
export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { username: string; password: string; email?: string; role: string }) =>
      createUser(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers });
      toast.success(i18n.t('admin:users.toasts.created'));
    },
    onError: () => { toast.error(i18n.t('admin:errors.createUserFailed')); },
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: { email?: string; is_active?: boolean; status?: 'active' | 'suspended' | 'deactivated'; role?: string } }) =>
      updateUser(userId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers });
      toast.success(i18n.t('admin:users.toasts.updated'));
    },
    onError: () => { toast.error(i18n.t('admin:errors.updateUserFailed')); },
  });
}

export function useDeactivateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => deactivateUser(userId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers });
      toast.success(i18n.t('admin:users.toasts.deactivated'));
    },
    // #347 (ADM-04): surface the backend reason (e.g. "Cannot deactivate the last
    // admin user" / "Cannot deactivate your own account") instead of a generic
    // "Failed to deactivate user". ApiError.message is the translated detail.
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : i18n.t('admin:users.deactivateDialog.error'));
    },
  });
}

export function useResetUserPassword() {
  return useMutation({
    mutationFn: ({ userId, password }: { userId: string; password: string }) =>
      resetUserPassword(userId, password),
    // No invalidation: a reset changes no field the user list renders.
    onSuccess: () => { toast.success(i18n.t('admin:users.toasts.passwordReset')); },
    // Same reasoning as useDeactivateUser: the backend reason is specific
    // (an identity-provider account, a policy refusal), so surface it.
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : i18n.t('admin:users.resetPasswordDialog.error'));
    },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => deleteUser(userId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers });
      toast.success(i18n.t('admin:users.toasts.deleted'));
    },
    onError: () => { toast.error(i18n.t('admin:errors.deleteUserFailed')); },
  });
}

export function useApproveUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      approveUser(userId, role),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers });
      toast.success(i18n.t('admin:users.toasts.approved'));
    },
    onError: () => { toast.error(i18n.t('admin:users.approveDialog.error')); },
  });
}

export function useRejectUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => rejectUser(userId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers });
      toast.success(i18n.t('admin:users.toasts.rejected'));
    },
    onError: () => { toast.error(i18n.t('admin:users.rejectDialog.error')); },
  });
}

// AI Status — cached across all consumers (SP-08). No idle polling: the result is
// re-fetched on staleTime expiry or via explicit invalidation (e.g. after mutating
// AI config). 60s staleTime keeps multi-consumer mounts from refetching; 5min gcTime
// keeps the cache warm across page transitions.
export function useAIStatus(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.admin.aiStatus,
    queryFn: getAIStatus,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    enabled: options?.enabled,
  });
}

// Share token hooks
export function useShareTokens(params: {
  skip?: number;
  limit?: number;
  search?: string;
  status?: string;
  sort?: string;
  order?: string;
} = {}) {
  const { skip = 0, limit = 50, search, status, sort, order } = params;
  return useQuery({
    queryKey: queryKeys.admin.shareTokens(skip, limit, search, status, sort, order),
    queryFn: () => listShareTokens({ skip, limit, search, status, sort, order }),
    placeholderData: keepPreviousData,
  });
}

export function useAdminRevokeShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tokenId: string) => adminRevokeShareToken(tokenId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allShareTokens });
      qc.invalidateQueries({ queryKey: queryKeys.admin.allEmbedTokens });
    },
    onError: () => { toast.error(i18n.t('admin:shareTokens.revokeFailed')); },
  });
}

// Embed token hooks
export function useAdminEmbedTokens(params: {
  skip?: number;
  limit?: number;
  map_id?: string;
  map_search?: string;
  creator?: string;
  status?: string;
}) {
  return useQuery({
    queryKey: queryKeys.admin.embedTokens(params),
    queryFn: () => listAdminEmbedTokens(params),
    placeholderData: keepPreviousData,
  });
}

export function useBulkRevokeEmbedTokens() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tokenIds: string[]) => bulkRevokeEmbedTokens(tokenIds),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.allEmbedTokens });
      qc.invalidateQueries({ queryKey: queryKeys.admin.allShareTokens });
    },
    onError: () => { toast.error(i18n.t('admin:embedTokens.bulkRevokeFailed')); },
  });
}

// API Key hooks
// fix(#1805 review round 3 P2): pageCount pages are fetched independently
// (one query per page, each its own cache entry via queryKeys.admin.apiKeys
// pageIndex) and flattened here, rather than accumulating into local
// component state -- a create/revoke mutation invalidates every loaded
// page's query in place, so the flattened list always reflects the latest
// data with no manual re-append/dedupe bookkeeping.
export const API_KEYS_PAGE_SIZE = 50;

export function useApiKeys(userId: string, pageCount: number = 1) {
  const queries = useQueries({
    queries: Array.from({ length: pageCount }, (_, i) => ({
      queryKey: queryKeys.admin.apiKeys(userId, i),
      queryFn: () =>
        listApiKeys(userId, { skip: i * API_KEYS_PAGE_SIZE, limit: API_KEYS_PAGE_SIZE }),
      enabled: !!userId,
    })),
  });

  const items = queries.flatMap((q) => q.data?.items ?? []);
  const total = queries[0]?.data?.total;
  const isLoading = queries.some((q) => q.isLoading);
  const hasMore = total !== undefined && total > items.length;

  return { items, total, isLoading, hasMore };
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      userId,
      name,
      scope,
    }: {
      userId: string;
      name: string;
      scope: ApiKeyScope;
    }) => createApiKey(userId, name, { scope }),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.apiKeys(variables.userId) });
    },
    onError: () => { toast.error(i18n.t('admin:apiKeys.createError')); },
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ keyId }: { keyId: string; userId: string }) =>
      revokeApiKey(keyId),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.apiKeys(variables.userId) });
    },
    onError: () => { toast.error(i18n.t('admin:apiKeys.revokeError')); },
  });
}

// Embedding stats
// Accept an enabled option so consumers can gate this manage_users probe with
// the effective capability. Without it, settings-only operators and the
// admin → logout transition frame would issue a guaranteed 401/403 request.
export function useEmbeddingStats(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.admin.embeddingStats,
    queryFn: getEmbeddingStats,
    staleTime: 30_000,
    enabled: options?.enabled,
  });
}

// Backfill embeddings
export function useBackfillEmbeddings() {
  return useMutation({
    mutationFn: (force?: boolean) => triggerBackfill(force),
    // No invalidation here, deliberately. Invalidating coverage at enqueue was
    // right while the request blocked until the work finished; since #1542 it
    // returns immediately, so refetching now would re-read the same pre-run
    // numbers and make the panel look like it had checked. The coverage
    // refresh belongs where the run actually lands — see useBackfillJobStatus.
    onError: (err) => {
      logger.error('[useBackfillEmbeddings]', err);
      // fix(#1542): a run already in flight is refused, not failed. Saying
      // "backfill failed" there would read as "your catalog is broken" for the
      // one case where the safe thing just happened.
      if (err instanceof ApiError && err.status === 409) {
        toast.warning(i18n.t('admin:errors.backfillAlreadyRunning'));
        return;
      }
      toast.error(i18n.t('admin:errors.backfillFailed'));
    },
  });
}

// fix(#1550 review P2): track the queued run rather than promising coverage
// updates on faith. The run happens on the job queue now (#1542), so the
// mutation resolves before any work has been done — the panel used to toast
// "coverage updates as it runs" and then never look again, so an operator who
// stayed on the page saw a stale coverage figure for as long as they stood
// there. This polls the one job it queued, refreshes coverage once it lands,
// and says how it went. Deliberately not a progress bar or a job list: one
// job, its terminal state, and the number the operator came here to read.
export function useBackfillJobStatus(jobId: string | null) {
  const qc = useQueryClient();
  const settledFor = useRef<string | null>(null);

  const query = useQuery({
    queryKey: queryKeys.ingest.jobStatus(jobId),
    queryFn: () => getJobStatus(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (q) => {
      // fix(#1550 review): no data is the absence of an answer, not the answer
      // that the run is over. Treating undefined as terminal meant one
      // exhausted first read — a blip while the API restarts — stopped the
      // polling permanently, and the coverage figure never updated again.
      if (!q.state.data) return 4_000;
      const status = q.state.data.status;
      return status === 'pending' || status === 'running' ? 4_000 : false;
    },
    refetchIntervalInBackground: false,
  });

  const status = query.data?.status;
  useEffect(() => {
    if (!jobId || !status) return;
    if (status === 'pending' || status === 'running') return;
    // Once per job: the query stays mounted with terminal data, so without
    // this the effect would re-toast on every unrelated re-render.
    if (settledFor.current === jobId) return;
    settledFor.current = jobId;
    qc.invalidateQueries({ queryKey: queryKeys.admin.embeddingStats });
    if (status === 'cancelled') {
      // fix(#1677): somebody cancelled this run; reporting it as a failure
      // put a red error toast in front of a user who had just asked for it
      // to stop.
      toast.info(i18n.t('admin:ai.backfillRunCancelled'));
      return;
    }
    if (status !== 'complete') {
      toast.error(i18n.t('admin:ai.backfillRunFailed'));
      return;
    }
    // fix(#1550 review): a run that finished with rejected records is not a
    // clean success. The synchronous endpoint returned counts the panel could
    // warn from; the queued one has to carry the same fact on the job status,
    // or a force regenerate that left coverage gaps reports as done.
    const failed = query.data?.rows_failed ?? 0;
    if (failed > 0) {
      toast.warning(i18n.t('admin:ai.backfillFinishedWithErrors', { errors: failed }));
      return;
    }
    toast.success(i18n.t('admin:ai.backfillFinished'));
  }, [jobId, status, query.data?.rows_failed, qc]);

  return query;
}

// Semantic search toggle
export function useUpdateSemanticSearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => updateSemanticSearch(enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.aiStatus });
      qc.invalidateQueries({ queryKey: queryKeys.settings.all });
    },
    onError: (err) => {
      logger.error('[useUpdateSemanticSearch]', err);
      toast.error(i18n.t('admin:errors.semanticSearchFailed'));
    },
  });
}

// Infrastructure
export function useInfrastructure() {
  return useQuery({
    queryKey: queryKeys.admin.infrastructure,
    queryFn: getInfrastructure,
    // 30s polling is intentional — infrastructure status is advisory, not time-critical.
    // Shorter intervals increase backend load with no UX benefit for admin dashboards.
    refetchInterval: 30_000,
  });
}
