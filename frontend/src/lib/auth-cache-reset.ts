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
    queryClient.clear();
  });
}
