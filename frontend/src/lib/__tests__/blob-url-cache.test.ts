import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { registerBlobUrlRevocation } from '@/lib/blob-url-cache';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Create a fresh QueryClient and register blob-URL revocation on it.
 * gcTime: Infinity so seeded entries are not auto-evicted between test steps.
 */
function freshClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  registerBlobUrlRevocation(qc);
  return qc;
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('registerBlobUrlRevocation', () => {
  it('Test A: revokes the blob URL when a quicklook entry is evicted', () => {
    const qc = freshClient();

    qc.setQueryData(['quicklook', 'ds-1'], 'blob:url-1');
    // Evict the entry
    qc.removeQueries({ queryKey: ['quicklook'] });

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:url-1');
  });

  it('Test B: revokes the blob URL when a map-thumbnail entry is evicted', () => {
    const qc = freshClient();

    qc.setQueryData(['map-thumbnail', 'm-1'], 'blob:thumb-1');
    // Evict the entry
    qc.removeQueries({ queryKey: ['map-thumbnail'] });

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:thumb-1');
  });

  it('Test C: does NOT revoke an active (un-evicted) entry', () => {
    const qc = freshClient();

    // Seed both "keep" and "other" entries
    qc.setQueryData(['quicklook', 'ds-keep'], 'blob:url-keep');
    qc.setQueryData(['quicklook', 'ds-other'], 'blob:url-other');

    // Evict only the "other" key
    qc.removeQueries({ queryKey: ['quicklook', 'ds-other'] });

    // The "other" URL was revoked; the live "keep" URL must NOT be revoked
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:url-other');
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:url-keep');
  });

  it('Test D: revokes the PREVIOUS url on refetch-replacement, keeps the new one', () => {
    const qc = freshClient();

    qc.setQueryData(['quicklook', 'ds-x'], 'blob:url-old');
    // Replace with a new blob URL (simulates a refetch producing a fresh blob)
    qc.setQueryData(['quicklook', 'ds-x'], 'blob:url-new');

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:url-old');
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:url-new');
  });

  it('Test E: ignores non-blob query keys', () => {
    const qc = freshClient();

    // Seed and evict a key whose root is NOT in BLOB_QUERY_KEYS
    qc.setQueryData(['datasets'], 'blob:not-ours');
    qc.removeQueries({ queryKey: ['datasets'] });

    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  });

  it('Test F (idempotency): registering twice on the same client does not double-revoke', () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
    // Register twice — WeakSet guard should prevent double-subscription
    registerBlobUrlRevocation(qc);
    registerBlobUrlRevocation(qc);

    qc.setQueryData(['quicklook', 'ds-idem'], 'blob:url-idem');
    qc.removeQueries({ queryKey: ['quicklook'] });

    // Must be called exactly once despite two registrations
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:url-idem');
  });
});
