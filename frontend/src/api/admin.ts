import { API_BASE } from '@/lib/constants';
import { useAuthStore } from '@/stores/auth-store';
import { apiFetch } from './client';
import type {
  AIStatusResponse,
  AdminJobListResponse,
  AdminShareTokenListResponse,
  AdminEmbedTokenListResponse,
  BulkRevokeResponse,
  BackfillResponse,
  CatalogStatsResponse,
  EmbeddingStatsResponse,
  UserListResponse,
  UserResponse,
  AuditLogListResponse,
  ApiKeyResponse,
  ApiKeyCreateResponse,
  InfrastructureResponse,
} from '@/types/api';

export async function getCatalogStats(): Promise<CatalogStatsResponse> {
  return apiFetch<CatalogStatsResponse>('/admin/stats/');
}

export async function listUsers(
  params: { skip?: number; limit?: number; status?: string; search?: string } = {},
): Promise<UserListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.status) query.set('status', params.status);
  if (params.search) query.set('search', params.search);
  const qs = query.toString();
  return apiFetch<UserListResponse>(`/admin/users/${qs ? `?${qs}` : ''}`);
}

export async function listUserNames(): Promise<{ id: string; username: string }[]> {
  return apiFetch<{ id: string; username: string }[]>('/admin/users/names/');
}

export async function listAdminJobs(
  params: { status?: string; user_id?: string; search?: string; skip?: number; limit?: number } = {},
): Promise<AdminJobListResponse> {
  const query = new URLSearchParams();
  if (params.status) query.set('status', params.status);
  if (params.user_id) query.set('user_id', params.user_id);
  if (params.search) query.set('search', params.search);
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch<AdminJobListResponse>(`/admin/jobs/${qs ? `?${qs}` : ''}`);
}

export async function listAuditLogs(
  params: {
    user_id?: string;
    action?: string;
    date_from?: string;
    date_to?: string;
    search?: string;
    skip?: number;
    limit?: number;
  } = {},
): Promise<AuditLogListResponse> {
  const query = new URLSearchParams();
  if (params.user_id) query.set('user_id', params.user_id);
  if (params.action) query.set('action', params.action);
  if (params.date_from) query.set('date_from', params.date_from);
  if (params.date_to) query.set('date_to', params.date_to);
  if (params.search) query.set('search', params.search);
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch<AuditLogListResponse>(`/admin/audit-logs/${qs ? `?${qs}` : ''}`);
}

// User CRUD
export async function createUser(data: {
  username: string;
  password: string;
  email?: string;
  role: string;
}): Promise<UserResponse> {
  return apiFetch<UserResponse>('/admin/users/', { method: 'POST', body: JSON.stringify(data) });
}

export async function updateUser(userId: string, data: {
  email?: string;
  is_active?: boolean;
  role?: string;
}): Promise<UserResponse> {
  return apiFetch<UserResponse>(`/admin/users/${userId}`, { method: 'PATCH', body: JSON.stringify(data) });
}

export async function deactivateUser(userId: string): Promise<UserResponse> {
  return apiFetch<UserResponse>(`/admin/users/${userId}/deactivate`, { method: 'POST' });
}

export async function deleteUser(userId: string): Promise<void> {
  await apiFetch(`/admin/users/${userId}`, { method: 'DELETE' });
}

export async function approveUser(userId: string, role: string): Promise<UserResponse> {
  return apiFetch<UserResponse>(`/admin/users/${userId}/approve`, { method: 'POST', body: JSON.stringify({ role }) });
}

export async function rejectUser(userId: string): Promise<void> {
  await apiFetch(`/admin/users/${userId}/reject`, { method: 'POST' });
}

// API Key management
export async function listApiKeys(userId: string): Promise<ApiKeyResponse[]> {
  const data = await apiFetch<{ items: ApiKeyResponse[]; total: number }>(`/admin/api-keys/?user_id=${userId}`);
  return data.items;
}

export async function createApiKey(userId: string, name: string): Promise<ApiKeyCreateResponse> {
  return apiFetch<ApiKeyCreateResponse>('/admin/api-keys/', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, name }),
  });
}

export async function revokeApiKey(keyId: string): Promise<void> {
  await apiFetch(`/admin/api-keys/${keyId}`, { method: 'DELETE' });
}

// Share tokens
export async function listShareTokens(
  params: { skip?: number; limit?: number; search?: string; status?: string } = {},
): Promise<AdminShareTokenListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.search) query.set('search', params.search);
  if (params.status) query.set('status', params.status);
  const qs = query.toString();
  return apiFetch<AdminShareTokenListResponse>(`/admin/share-tokens/${qs ? `?${qs}` : ''}`);
}

export async function adminRevokeShareToken(tokenId: string): Promise<void> {
  await apiFetch(`/admin/share-tokens/${tokenId}`, { method: 'DELETE' });
}

// Embed tokens
export async function listAdminEmbedTokens(
  params: { skip?: number; limit?: number; map_id?: string; map_search?: string; creator?: string; status?: string } = {},
): Promise<AdminEmbedTokenListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.map_id) query.set('map_id', params.map_id);
  if (params.map_search) query.set('map_search', params.map_search);
  if (params.creator) query.set('creator', params.creator);
  if (params.status) query.set('status', params.status);
  const qs = query.toString();
  return apiFetch<AdminEmbedTokenListResponse>(`/admin/embed-tokens/${qs ? `?${qs}` : ''}`);
}

export async function bulkRevokeEmbedTokens(tokenIds: string[]): Promise<BulkRevokeResponse> {
  return apiFetch<BulkRevokeResponse>('/admin/embed-tokens/bulk-revoke/', {
    method: 'POST',
    body: JSON.stringify({ token_ids: tokenIds }),
  });
}

// AI Status
export async function getAIStatus(): Promise<AIStatusResponse> {
  return apiFetch<AIStatusResponse>('/admin/ai-status/');
}

// Infrastructure
export async function getInfrastructure(): Promise<InfrastructureResponse> {
  return apiFetch<InfrastructureResponse>('/admin/infrastructure/');
}

// Embedding stats
export async function getEmbeddingStats(): Promise<EmbeddingStatsResponse> {
  return apiFetch<EmbeddingStatsResponse>('/admin/embedding-stats/');
}

// Backfill embeddings
export async function triggerBackfill(force = false): Promise<BackfillResponse> {
  const url = force ? '/admin/backfill-embeddings/?force=true' : '/admin/backfill-embeddings/';
  return apiFetch<BackfillResponse>(url, {
    method: 'POST',
  });
}

// Semantic search toggle (uses unified settings endpoint)
export async function updateSemanticSearch(enabled: boolean): Promise<void> {
  return apiFetch<void>('/settings/', {
    method: 'PUT',
    body: JSON.stringify({ settings: { semantic_search_enabled: enabled } }),
  });
}

// Audit log export (returns blob for browser download)
export async function exportAuditLogs(
  format: 'csv' | 'json',
  filters: {
    action?: string;
    date_from?: string;
    date_to?: string;
    search?: string;
  } = {},
): Promise<Blob> {
  const query = new URLSearchParams();
  if (filters.action) query.set('action', filters.action);
  if (filters.date_from) query.set('date_from', filters.date_from);
  if (filters.date_to) query.set('date_to', filters.date_to);
  if (filters.search) query.set('search', filters.search);
  const qs = query.toString();
  const url = `${API_BASE}/admin/audit-logs/export/${format}${qs ? `?${qs}` : ''}`;

  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(url, { headers });
  if (!response.ok) {
    throw new Error(`Export failed: ${response.statusText}`);
  }
  return response.blob();
}
