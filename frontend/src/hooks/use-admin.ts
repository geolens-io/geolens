import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
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
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import { retryJob } from '@/api/ingest';
import { logger } from '@/lib/logger';

export function useCatalogStats() {
  return useQuery({
    queryKey: queryKeys.admin.stats,
    queryFn: getCatalogStats,
    staleTime: 30_000,
  });
}

export function useUserList(skip: number, limit: number, status?: string, search?: string) {
  return useQuery({
    queryKey: queryKeys.admin.users(skip, limit, status, search),
    queryFn: () => listUsers({ skip, limit, status, search }),
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
  action?: string;
  date_from?: string;
  date_to?: string;
  search?: string;
  skip?: number;
  limit?: number;
}) {
  return useQuery({
    queryKey: queryKeys.admin.auditLogs(params),
    queryFn: () => listAuditLogs(params),
    placeholderData: keepPreviousData,
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
}) {
  return useQuery({
    queryKey: queryKeys.admin.jobs(params),
    queryFn: () => listAdminJobs(params),
    placeholderData: keepPreviousData,
  });
}

export function useFailedJobCount() {
  return useQuery({
    queryKey: queryKeys.admin.failedJobCount,
    queryFn: async () => {
      const result = await listAdminJobs({ status: 'failed', limit: 1 });
      return result.total;
    },
    staleTime: 60_000,
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

// User mutations
export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { username: string; password: string; email?: string; role: string }) =>
      createUser(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers }); },
    onError: () => { toast.error(i18n.t('admin:errors.createUserFailed')); },
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: { email?: string; is_active?: boolean; role?: string } }) =>
      updateUser(userId, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers }); },
    onError: () => { toast.error(i18n.t('admin:errors.updateUserFailed')); },
  });
}

export function useDeactivateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => deactivateUser(userId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers }); },
    onError: () => { toast.error(i18n.t('admin:users.deactivateDialog.error')); },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => deleteUser(userId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers }); },
    onError: () => { toast.error(i18n.t('admin:errors.deleteUserFailed')); },
  });
}

export function useApproveUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      approveUser(userId, role),
    onSuccess: () => { qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers }); },
    onError: () => { toast.error(i18n.t('admin:users.approveDialog.error')); },
  });
}

export function useRejectUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => rejectUser(userId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: queryKeys.admin.allUsers }); },
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
export function useShareTokens(skip = 0, limit = 50, search?: string, status?: string) {
  return useQuery({
    queryKey: queryKeys.admin.shareTokens(skip, limit, search, status),
    queryFn: () => listShareTokens({ skip, limit, search, status }),
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
export function useApiKeys(userId: string) {
  return useQuery({
    queryKey: queryKeys.admin.apiKeys(userId),
    queryFn: () => listApiKeys(userId),
    enabled: !!userId,
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, name }: { userId: string; name: string }) =>
      createApiKey(userId, name),
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
// CR-03/WR-04 (Phase 1050-rev): accept the same options shape as
// useAIStatus so consumers can gate the admin probe with
// `{ enabled: !!token && isAdmin }`. Without the gate, anonymous and
// non-admin authed pages (including the admin → logout transition frame)
// fire GET /admin/embedding-stats/ → 401, defeating SF-06.
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
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (force?: boolean) => triggerBackfill(force),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.embeddingStats });
    },
    onError: (err) => {
      logger.error('[useBackfillEmbeddings]', err);
      toast.error(i18n.t('admin:errors.backfillFailed'));
    },
  });
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
