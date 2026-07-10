import type { QueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';

/**
 * fix(#430 codex r6): user-scoped queries (dataset search, map search, map
 * lists) key their caches by request parameters only, so after a logout — or a
 * lower-privilege login in the same tab — the previous identity's cached rows
 * could render before any refetch. Rather than threading auth identity into
 * every query key, clear the whole cache at the one identity choke point.
 * A token refresh keeps the same user id and does NOT clear.
 *
 * Returns the store unsubscribe (used by tests; the app subscription lives
 * for the page lifetime).
 */
export function wireAuthCacheReset(queryClient: QueryClient): () => void {
  let lastUserId = useAuthStore.getState().user?.id ?? null;
  return useAuthStore.subscribe((state) => {
    const userId = state.user?.id ?? null;
    if (userId === lastUserId) return;
    lastUserId = userId;
    // fix(#438): DATA-10 — a full clear() on every identity change is safe but
    // refetch-bursty. Kept whole because scoping which keys to drop per identity
    // is error-prone (a missed key leaks the prior user's data); revisit only if
    // the refetch burst is measured to matter.
    queryClient.clear();
  });
}
