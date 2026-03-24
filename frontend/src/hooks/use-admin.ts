import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import {
  getCatalogStats,
  listUsers,
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
import { retryJob } from '@/api/ingest';

export function useCatalogStats() {
  return useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: getCatalogStats,
    staleTime: 30_000,
  });
}

export function useUserList(skip: number, limit: number, status?: string, search?: string) {
  return useQuery({
    queryKey: ['admin', 'users', skip, limit, status, search],
    queryFn: () => listUsers({ skip, limit, status, search }),
    placeholderData: keepPreviousData,
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
    queryKey: ['admin', 'audit-logs', params],
    queryFn: () => listAuditLogs(params),
    placeholderData: keepPreviousData,
  });
}

// Pending count (for badge)
export function usePendingCount() {
  return useQuery({
    queryKey: ['admin', 'users', 'pending-count'],
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
    queryKey: ['admin', 'jobs', params],
    queryFn: () => listAdminJobs(params),
    placeholderData: keepPreviousData,
  });
}

export function useFailedJobCount() {
  return useQuery({
    queryKey: ['admin', 'jobs', 'failed-count'],
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
      qc.invalidateQueries({ queryKey: ['admin', 'jobs'] });
    },
  });
}

// User mutations
export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { username: string; password: string; email?: string; role: string }) =>
      createUser(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'users'] }); },
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: { email?: string; is_active?: boolean; role?: string } }) =>
      updateUser(userId, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'users'] }); },
  });
}

export function useDeactivateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => deactivateUser(userId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'users'] }); },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => deleteUser(userId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'users'] }); },
  });
}

export function useApproveUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      approveUser(userId, role),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'users'] }); },
  });
}

export function useRejectUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => rejectUser(userId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'users'] }); },
  });
}

// AI Status
export function useAIStatus() {
  return useQuery({
    queryKey: ['admin', 'ai-status'],
    queryFn: getAIStatus,
    staleTime: 30_000,
  });
}

// Share token hooks
export function useShareTokens(skip = 0, limit = 50, search?: string, status?: string) {
  return useQuery({
    queryKey: ['admin', 'share-tokens', skip, limit, search, status],
    queryFn: () => listShareTokens({ skip, limit, search, status }),
    placeholderData: keepPreviousData,
  });
}

export function useAdminRevokeShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tokenId: string) => adminRevokeShareToken(tokenId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'share-tokens'] });
    },
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
    queryKey: ['admin', 'embed-tokens', params],
    queryFn: () => listAdminEmbedTokens(params),
    placeholderData: keepPreviousData,
  });
}

export function useBulkRevokeEmbedTokens() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tokenIds: string[]) => bulkRevokeEmbedTokens(tokenIds),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'embed-tokens'] });
    },
  });
}

// API Key hooks
export function useApiKeys(userId: string) {
  return useQuery({
    queryKey: ['admin', 'api-keys', userId],
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
      qc.invalidateQueries({ queryKey: ['admin', 'api-keys', variables.userId] });
    },
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ keyId }: { keyId: string; userId: string }) =>
      revokeApiKey(keyId),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['admin', 'api-keys', variables.userId] });
    },
  });
}

// Embedding stats
export function useEmbeddingStats() {
  return useQuery({
    queryKey: ['admin', 'embedding-stats'],
    queryFn: getEmbeddingStats,
    staleTime: 30_000,
  });
}

// Backfill embeddings
export function useBackfillEmbeddings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (force?: boolean) => triggerBackfill(force),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'embedding-stats'] });
    },
  });
}

// Semantic search toggle
export function useUpdateSemanticSearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => updateSemanticSearch(enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'ai-status'] });
      qc.invalidateQueries({ queryKey: ['settings'] });
    },
  });
}

// Infrastructure
export function useInfrastructure() {
  return useQuery({
    queryKey: ['admin', 'infrastructure'],
    queryFn: getInfrastructure,
    refetchInterval: 30_000,
  });
}
