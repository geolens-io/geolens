import { API_BASE } from '@/lib/constants';
import { translateApiErrorDetail } from '@/lib/error-map';
import { apiFetch, authenticatedRawFetch } from './client';
import type {
  AIStatusResponse,
  AdminJobListResponse,
  AdminShareTokenListResponse,
  AdminEmbedTokenListResponse,
  BulkRevokeResponse,
  BackfillResponse,
  CatalogStatsResponse,
  EmbeddingStatsResponse,
  GroupListResponse,
  GroupMemberListResponse,
  GroupResponse,
  UserListResponse,
  UserResponse,
  AuditLogListResponse,
  ApiKeyResponse,
  ApiKeyCreateResponse,
  ApiKeyScope,
  InfrastructureResponse,
} from '@/types/api';

export async function getCatalogStats(): Promise<CatalogStatsResponse> {
  return apiFetch<CatalogStatsResponse>('/admin/stats/');
}

export async function listUsers(
  params: {
    skip?: number;
    limit?: number;
    status?: string;
    role?: string;
    search?: string;
    sort?: string;
    order?: string;
  } = {},
): Promise<UserListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.status) query.set('status', params.status);
  if (params.role) query.set('role', params.role);
  if (params.search) query.set('search', params.search);
  if (params.sort) query.set('sort', params.sort);
  if (params.order) query.set('order', params.order);
  const qs = query.toString();
  return apiFetch<UserListResponse>(`/admin/users/${qs ? `?${qs}` : ''}`);
}

export async function listUserNames(): Promise<{ id: string; username: string }[]> {
  const limit = 500;
  const names: { id: string; username: string }[] = [];
  for (let skip = 0; ; skip += limit) {
    const page = await apiFetch<{ id: string; username: string }[]>(`/admin/users/names/?skip=${skip}&limit=${limit}`);
    names.push(...page);
    if (page.length < limit) return names;
  }
}

export async function listGroups(params: { skip?: number; limit?: number } = {}): Promise<GroupListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch<GroupListResponse>(`/admin/groups/${qs ? `?${qs}` : ''}`);
}

export async function createGroup(name: string): Promise<GroupResponse> {
  return apiFetch<GroupResponse>('/admin/groups/', { method: 'POST', body: JSON.stringify({ name }) });
}

export async function renameGroup(groupId: string, name: string): Promise<GroupResponse> {
  return apiFetch<GroupResponse>(`/admin/groups/${groupId}`, { method: 'PATCH', body: JSON.stringify({ name }) });
}

export async function deleteGroup(groupId: string): Promise<void> {
  await apiFetch<void>(`/admin/groups/${groupId}`, { method: 'DELETE' });
}

export async function listGroupMembers(groupId: string): Promise<{ id: string; username: string }[]> {
  const limit = 200;
  const members: { id: string; username: string }[] = [];
  for (let skip = 0; ; skip += limit) {
    const page = await apiFetch<GroupMemberListResponse>(
      `/admin/groups/${groupId}/members/?skip=${skip}&limit=${limit}`,
    );
    members.push(...page.members);
    if (members.length >= page.total || page.members.length < limit) return members;
  }
}

export async function addGroupMembers(groupId: string, userIds: string[]): Promise<GroupResponse> {
  return apiFetch<GroupResponse>(`/admin/groups/${groupId}/members/`, {
    method: 'POST',
    body: JSON.stringify({ user_ids: userIds }),
  });
}

export async function removeGroupMember(groupId: string, userId: string): Promise<void> {
  await apiFetch<void>(`/admin/groups/${groupId}/members/${userId}`, { method: 'DELETE' });
}

export async function listAdminJobs(
  params: {
    status?: string;
    user_id?: string;
    search?: string;
    skip?: number;
    limit?: number;
    sort?: string;
    order?: string;
  } = {},
): Promise<AdminJobListResponse> {
  const query = new URLSearchParams();
  if (params.status) query.set('status', params.status);
  if (params.user_id) query.set('user_id', params.user_id);
  if (params.search) query.set('search', params.search);
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.sort) query.set('sort', params.sort);
  if (params.order) query.set('order', params.order);
  const qs = query.toString();
  return apiFetch<AdminJobListResponse>(`/admin/jobs/${qs ? `?${qs}` : ''}`);
}

export async function listAuditLogs(
  params: {
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
  } = {},
): Promise<AuditLogListResponse> {
  const query = new URLSearchParams();
  if (params.user_id) query.set('user_id', params.user_id);
  if (params.action) query.set('action', params.action);
  if (params.resource_type) query.set('resource_type', params.resource_type);
  if (params.resource_id) query.set('resource_id', params.resource_id);
  if (params.date_from) query.set('date_from', params.date_from);
  if (params.date_to) query.set('date_to', params.date_to);
  if (params.search) query.set('search', params.search);
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.sort) query.set('sort', params.sort);
  if (params.order) query.set('order', params.order);
  const qs = query.toString();
  return apiFetch<AuditLogListResponse>(`/admin/audit-logs/${qs ? `?${qs}` : ''}`);
}

export async function createUser(data: {
  username: string;
  password: string;
  email?: string;
  role: string;
}): Promise<UserResponse> {
  return apiFetch<UserResponse>('/admin/users/', { method: 'POST', body: JSON.stringify(data) });
}

export async function updateUser(userId: string, data: {
  email?: string | null;
  is_active?: boolean;
  status?: 'active' | 'suspended' | 'deactivated';
  role?: string;
}): Promise<UserResponse> {
  return apiFetch<UserResponse>(`/admin/users/${encodeURIComponent(userId)}`, { method: 'PATCH', body: JSON.stringify(data) });
}

export async function deactivateUser(userId: string): Promise<UserResponse> {
  return apiFetch<UserResponse>(`/admin/users/${encodeURIComponent(userId)}/deactivate/`, { method: 'POST' });
}

/**
 * Admin-initiated password reset. The submitted value is sent once and never
 * held elsewhere on the client; the backend revokes the target's outstanding
 * sessions and API keys in the same request.
 */
export async function resetUserPassword(userId: string, password: string): Promise<UserResponse> {
  return apiFetch<UserResponse>(`/admin/users/${encodeURIComponent(userId)}/reset-password/`, {
    method: 'POST',
    body: JSON.stringify({ password }),
  });
}

export async function deleteUser(userId: string): Promise<void> {
  await apiFetch(`/admin/users/${encodeURIComponent(userId)}`, { method: 'DELETE' });
}

export async function approveUser(userId: string, role: string): Promise<UserResponse> {
  return apiFetch<UserResponse>(`/admin/users/${encodeURIComponent(userId)}/approve/`, { method: 'POST', body: JSON.stringify({ role }) });
}

export async function rejectUser(userId: string): Promise<void> {
  await apiFetch(`/admin/users/${encodeURIComponent(userId)}/reject/`, { method: 'POST' });
}

// API Key management
// skip/limit are threaded through so the caller can page: the backend defaults
// to limit=50 (max 200), so more keys than one page would otherwise be hidden
// from the only UI that revokes them.
export async function listApiKeys(
  userId: string,
  options: { skip?: number; limit?: number } = {},
): Promise<{ items: ApiKeyResponse[]; total: number }> {
  const skip = options.skip ?? 0;
  const limit = options.limit ?? 50;
  return apiFetch<{ items: ApiKeyResponse[]; total: number }>(
    `/admin/api-keys/?user_id=${encodeURIComponent(userId)}&skip=${skip}&limit=${limit}`,
  );
}

export async function createApiKey(
  userId: string,
  name: string,
  options: { scope?: ApiKeyScope; expiresAt?: string | null } = {},
): Promise<ApiKeyCreateResponse> {
  // AdminApiKeyCreateRequest accepts expires_at, as createMyApiKey does.
  return apiFetch<ApiKeyCreateResponse>('/admin/api-keys/', {
    method: 'POST',
    body: JSON.stringify({
      user_id: userId,
      name,
      scope: options.scope ?? 'full',
      ...(options.expiresAt ? { expires_at: options.expiresAt } : {}),
    }),
  });
}

export async function revokeApiKey(keyId: string): Promise<void> {
  await apiFetch(`/admin/api-keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
}

export async function listShareTokens(
  params: {
    skip?: number;
    limit?: number;
    search?: string;
    status?: string;
    sort?: string;
    order?: string;
  } = {},
): Promise<AdminShareTokenListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.search) query.set('search', params.search);
  if (params.status) query.set('status', params.status);
  if (params.sort) query.set('sort', params.sort);
  if (params.order) query.set('order', params.order);
  const qs = query.toString();
  return apiFetch<AdminShareTokenListResponse>(`/admin/share-tokens/${qs ? `?${qs}` : ''}`);
}

export async function adminRevokeShareToken(tokenId: string): Promise<void> {
  await apiFetch(`/admin/share-tokens/${encodeURIComponent(tokenId)}`, { method: 'DELETE' });
}

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

export async function getAIStatus(): Promise<AIStatusResponse> {
  return apiFetch<AIStatusResponse>('/admin/ai-status/');
}

// Live provider probe — spends real provider tokens, so only
// invoked from an explicit admin action, never on page load.
// Chat + embeddings probe sequentially at up to 15s each, so the
// backend's sanitized timeout rows can arrive after the default 30s client
// deadline — outlive the backend worst case instead of toasting a generic error.
export async function probeAIStatus(): Promise<AIStatusResponse> {
  return apiFetch<AIStatusResponse>('/admin/ai-status/?probe=true', { timeoutMs: 45_000 });
}

export async function getInfrastructure(): Promise<InfrastructureResponse> {
  return apiFetch<InfrastructureResponse>('/admin/infrastructure/');
}

export async function getEmbeddingStats(): Promise<EmbeddingStatsResponse> {
  return apiFetch<EmbeddingStatsResponse>('/admin/embedding-stats/');
}

// An all-tenant backfill queues every tenant's run inside the request, which
// grows with the fleet. Outlive the edge proxy so a slow fan-out reaches the
// page as the proxy's verdict rather than a client-side abort.
const ALL_TENANT_BACKFILL_TIMEOUT_MS = 630_000;

export async function triggerBackfill(force = false, allTenants = false): Promise<BackfillResponse> {
  const params = new URLSearchParams();
  if (force) params.set('force', 'true');
  if (allTenants) params.set('all_tenants', 'true');
  const query = params.toString();
  return apiFetch<BackfillResponse>(`/admin/backfill-embeddings/${query ? `?${query}` : ''}`, {
    method: 'POST',
    ...(allTenants ? { timeoutMs: ALL_TENANT_BACKFILL_TIMEOUT_MS } : {}),
  });
}

// Audit log export (returns blob for browser download)
export async function exportAuditLogs(
  format: 'csv' | 'json',
  filters: {
    user_id?: string;
    action?: string;
    resource_type?: string;
    resource_id?: string;
    date_from?: string;
    date_to?: string;
    search?: string;
  } = {},
): Promise<Blob> {
  const query = new URLSearchParams();
  if (filters.user_id) query.set('user_id', filters.user_id);
  if (filters.action) query.set('action', filters.action);
  if (filters.resource_type) query.set('resource_type', filters.resource_type);
  if (filters.resource_id) query.set('resource_id', filters.resource_id);
  if (filters.date_from) query.set('date_from', filters.date_from);
  if (filters.date_to) query.set('date_to', filters.date_to);
  if (filters.search) query.set('search', filters.search);
  const qs = query.toString();
  const url = `${API_BASE}/admin/audit-logs/export/${encodeURIComponent(format)}${qs ? `?${qs}` : ''}`;

  // Refresh-aware raw fetch so an export issued after a long idle refreshes the
  // JWT instead of 401-ing.
  const response = await authenticatedRawFetch(url);
  if (!response.ok) {
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail;
    } catch { /* not JSON */ }
    throw new Error(translateApiErrorDetail(detail, response.status));
  }
  return response.blob();
}

/**
 * Users CSV export. `window.open()` cannot carry the Bearer token, so this uses
 * the same refresh-aware raw fetch as the audit-log export above.
 */
export async function exportUsersCsv(): Promise<Blob> {
  const response = await authenticatedRawFetch(`${API_BASE}/admin/users/export.csv`);
  if (!response.ok) {
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail;
    } catch { /* not JSON */ }
    throw new Error(translateApiErrorDetail(detail, response.status));
  }
  return response.blob();
}
