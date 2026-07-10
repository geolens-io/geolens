/**
 * fix(#438): ARC-04 — request-contract tests for the admin api layer.
 *
 * `admin` is the audit's weakest-covered, highest-silent-risk domain (off the
 * main user path, so a wrong URL/method regresses invisibly). These pin the
 * exact endpoint, HTTP method, and body each function issues — the URL/method
 * axis that the ARC-02 openapi type guard does NOT cover. A renamed route or a
 * flipped verb fails here instead of in production.
 */
import { API_BASE } from '@/lib/constants';
import * as admin from '@/api/admin';
import { apiFetch, authenticatedRawFetch } from '@/api/client';

// vitest hoists vi.mock above the imports above, so admin.ts binds these mocks.
vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(() => Promise.resolve({ items: [], total: 0 })),
  authenticatedRawFetch: vi.fn(() =>
    Promise.resolve({ ok: true, statusText: 'OK', blob: () => Promise.resolve(new Blob(['x'])) }),
  ),
}));

const mockApiFetch = vi.mocked(apiFetch);
const mockRawFetch = vi.mocked(authenticatedRawFetch);

beforeEach(() => {
  mockApiFetch.mockClear();
  mockRawFetch.mockClear();
});

/** URL passed to apiFetch on the single most recent call. */
function calledUrl() {
  return mockApiFetch.mock.calls[0]?.[0];
}
function calledInit() {
  return mockApiFetch.mock.calls[0]?.[1];
}

describe('admin api request contracts', () => {
  it('listUsers builds the query string and hits /admin/users/', async () => {
    await admin.listUsers({ skip: 10, limit: 25, status: 'pending', search: 'ann' });
    expect(calledUrl()).toBe('/admin/users/?skip=10&limit=25&status=pending&search=ann');
    expect(calledInit()).toBeUndefined();
  });

  it('listUsers omits the query string when no params are given', async () => {
    await admin.listUsers();
    expect(calledUrl()).toBe('/admin/users/');
  });

  it('createUser POSTs the user body to /admin/users/', async () => {
    await admin.createUser({ username: 'ann', password: 'pw', role: 'viewer' });
    expect(calledUrl()).toBe('/admin/users/');
    expect(calledInit()?.method).toBe('POST');
    expect(JSON.parse(calledInit()?.body as string)).toEqual({ username: 'ann', password: 'pw', role: 'viewer' });
  });

  it('updateUser PATCHes /admin/users/{id}', async () => {
    await admin.updateUser('u1', { role: 'editor' });
    expect(calledUrl()).toBe('/admin/users/u1');
    expect(calledInit()?.method).toBe('PATCH');
    expect(JSON.parse(calledInit()?.body as string)).toEqual({ role: 'editor' });
  });

  it('deleteUser DELETEs /admin/users/{id}', async () => {
    await admin.deleteUser('u1');
    expect(calledUrl()).toBe('/admin/users/u1');
    expect(calledInit()?.method).toBe('DELETE');
  });

  it('approveUser POSTs the role to the approve subresource', async () => {
    await admin.approveUser('u1', 'editor');
    expect(calledUrl()).toBe('/admin/users/u1/approve/');
    expect(calledInit()?.method).toBe('POST');
    expect(JSON.parse(calledInit()?.body as string)).toEqual({ role: 'editor' });
  });

  it('deactivateUser POSTs the deactivate subresource with no body', async () => {
    await admin.deactivateUser('u1');
    expect(calledUrl()).toBe('/admin/users/u1/deactivate/');
    expect(calledInit()?.method).toBe('POST');
    expect(calledInit()?.body).toBeUndefined();
  });

  it('createApiKey POSTs user_id + name to /admin/api-keys/', async () => {
    await admin.createApiKey('u1', 'ci-key');
    expect(calledUrl()).toBe('/admin/api-keys/');
    expect(calledInit()?.method).toBe('POST');
    expect(JSON.parse(calledInit()?.body as string)).toEqual({ user_id: 'u1', name: 'ci-key' });
  });

  it('bulkRevokeEmbedTokens POSTs token_ids to the bulk-revoke endpoint', async () => {
    await admin.bulkRevokeEmbedTokens(['a', 'b']);
    expect(calledUrl()).toBe('/admin/embed-tokens/bulk-revoke/');
    expect(calledInit()?.method).toBe('POST');
    expect(JSON.parse(calledInit()?.body as string)).toEqual({ token_ids: ['a', 'b'] });
  });

  it('triggerBackfill toggles the force query param', async () => {
    await admin.triggerBackfill(false);
    expect(calledUrl()).toBe('/admin/backfill-embeddings/');
    mockApiFetch.mockClear();
    await admin.triggerBackfill(true);
    expect(calledUrl()).toBe('/admin/backfill-embeddings/?force=true');
  });

  it('updateSemanticSearch PUTs the settings envelope to /settings/', async () => {
    await admin.updateSemanticSearch(true);
    expect(calledUrl()).toBe('/settings/');
    expect(calledInit()?.method).toBe('PUT');
    expect(JSON.parse(calledInit()?.body as string)).toEqual({ settings: { semantic_search_enabled: true } });
  });

  it('exportUsersCsv uses the refresh-aware raw fetch against the absolute export URL (UX-01)', async () => {
    await admin.exportUsersCsv();
    expect(mockRawFetch).toHaveBeenCalledWith(`${API_BASE}/admin/users/export.csv`);
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it('exportAuditLogs builds the format path + filter query on the raw fetch', async () => {
    await admin.exportAuditLogs('csv', { action: 'login', search: 'ann' });
    expect(mockRawFetch).toHaveBeenCalledWith(`${API_BASE}/admin/audit-logs/export/csv?action=login&search=ann`);
  });
});
