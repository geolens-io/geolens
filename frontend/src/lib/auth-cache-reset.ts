import type { QueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { clearReportEntries } from '@/lib/report';
import { useDrawingStore } from '@/stores/drawing-store';
import { useSearchStore } from '@/stores/search-store';
import { clearUploadBatch, clearPendingUploadFiles } from '@/api/upload-session';
import { clearStacImport } from '@/api/stac-import-session';
import { removeSessionStorage } from '@/lib/storage';

/**
 * The AI chat transcript (`geolens-chat-<mapId>`, ChatPanel.tsx) and the
 * one-shot "open in builder" handoff payload (`geolens-chat-result`,
 * chat-result-handoff.ts) are sessionStorage, keyed only on the map, not on
 * identity. sessionStorage outlives logout, so a second user in the same tab
 * would see the first user's prompts, dataset names and query metadata. Same
 * choke point and rule as the stores below: identity changed, drop it. Keys are
 * collected first, then removed, because removing mid-loop shifts sessionStorage's
 * live index and skips entries.
 *
 * The enumeration (`.length`/`.key`) has no helper in lib/storage.ts, so it
 * stays raw here inside the try/catch, as a plain loop (a `.forEach` callback
 * would fall outside the try's frame). Removal goes through `removeSessionStorage`,
 * which is exception-safe on its own.
 */
function clearChatSessionStorage(): void {
  try {
    const toRemove: string[] = [];
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i);
      if (key?.startsWith('geolens-chat-')) toRemove.push(key);
    }
    for (const key of toRemove) {
      removeSessionStorage(key);
    }
  } catch {
    // Storage unavailable (private mode / disabled): nothing to clear.
  }
}

/**
 * User-scoped queries (dataset search, map search, map lists) key their caches
 * by request parameters only, so after a logout or a lower-privilege login in
 * the same tab the previous identity's cached rows could render before any
 * refetch. Rather than threading identity into every query key, clear the whole
 * cache at the one identity choke point. A token refresh keeps the same user id
 * and does not clear.
 *
 * Returns the store unsubscribe (used by tests; the app subscription lives for
 * the page lifetime).
 */
export function wireAuthCacheReset(queryClient: QueryClient): () => void {
  let lastUserId = useAuthStore.getState().user?.id ?? null;
  return useAuthStore.subscribe((state) => {
    const userId = state.user?.id ?? null;
    if (userId === lastUserId) return;
    lastUserId = userId;
    // A full clear() is refetch-bursty but kept whole: scoping which keys to drop
    // per identity is error-prone, and a missed key leaks the prior user's data.
    queryClient.clear();
    // The problem reporter's in-memory capture buffer is identity-scoped residue
    // too: it is visible to anonymous visitors, so a populated buffer after logout
    // would show (and attach to a report) the previous user's entries.
    clearReportEntries();
    // drawing-store's target dataset, selected feature (a real row's property bag)
    // and edit-dirty flag are identity-scoped residue, as is search-store's
    // typed/drawn search intent.
    //
    // Bump the session epoch BEFORE clearing so any write already in flight
    // (captured against the old epoch) is refused by drawing-store's own check,
    // whatever the next identity is; see `bumpSessionEpoch` in drawing-store.ts.
    useDrawingStore.getState().bumpSessionEpoch();
    useDrawingStore.getState().clearDrawing();
    useSearchStore.getState().clearIdentityScopedFilters();
    // See clearChatSessionStorage's doc comment above.
    clearChatSessionStorage();

    // The Upload and STAC tabs' module-scoped in-flight sessions record the user
    // id that started them and refuse adoption by a different one
    // (`peekUploadBatch`/`peekStacImport`), but only when something next tries to
    // adopt. Tearing down here closes the window between a logout/switch and
    // whatever mounts next.
    clearUploadBatch();
    clearStacImport();
    // The queue a drop sits in before the upload-config query settles is the
    // same identity-scoped residue; clear it here rather than rely on the
    // batch's ownerId check.
    clearPendingUploadFiles();
  });
}
