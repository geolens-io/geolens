import type { QueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { clearReportEntries } from '@/lib/report';
import { useDrawingStore } from '@/stores/drawing-store';
import { useSearchStore } from '@/stores/search-store';
import { clearUploadBatch, clearPendingUploadFiles } from '@/api/upload-session';
import { clearStacImport } from '@/api/stac-import-session';
import { removeSessionStorage } from '@/lib/storage';

/**
 * fix(#1850): the AI chat transcript (`geolens-chat-<mapId>`, ChatPanel.tsx)
 * and the one-shot "open in builder" handoff payload (`geolens-chat-result`,
 * chat-result-handoff.ts) are sessionStorage, keyed only on the map — not on
 * identity. sessionStorage outlives logout, so a second user signing in in
 * the same tab sees the first user's prompts, dataset names and query
 * metadata. Same choke point, same rule as the stores below: identity
 * changed, drop it. Collecting keys first, then removing, because removing
 * mid-loop shifts sessionStorage's live index and skips entries.
 *
 * fix(#1536 gate): the enumeration (`.length`/`.key`) has no helper in
 * lib/storage.ts, so it stays raw here, guarded by the try/catch below —
 * kept as a plain loop rather than `.forEach`, which would cross a function
 * boundary and fall outside the try's frame. The removal itself goes
 * through `removeSessionStorage`, which is already exception-safe on its
 * own.
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
    // storage unavailable (private mode / disabled) — nothing to clear.
  }
}

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
    // fix(#1663 review P1): the problem reporter's in-memory capture buffer is
    // the same kind of identity-scoped residue. With the reporter visible to
    // anonymous visitors, a logout that leaves the buffer populated would show
    // the previous user's captured entries (and attach them to a report) in
    // the now-anonymous tab. Same choke point, same rule: identity changed,
    // drop everything captured under the old one.
    clearReportEntries();
    // fix(#1713): drawing-store's target dataset, selected feature (a real
    // row's property bag) and edit-dirty flag are the same identity-scoped
    // residue, plus the milder case of search-store's typed/drawn search
    // intent. Same choke point, same rule: identity changed, drop everything
    // adopted or entered under the old one.
    //
    // fix(#1761 review P1): bump the session epoch BEFORE clearing, so any
    // write already in flight (captured against the old epoch) is refused
    // by drawing-store's own check even if it lands between these two
    // calls or after them, no matter what the next identity turns out to
    // be — see drawing-store.ts's `bumpSessionEpoch` doc comment.
    useDrawingStore.getState().bumpSessionEpoch();
    useDrawingStore.getState().clearDrawing();
    useSearchStore.getState().clearIdentityScopedFilters();
    // fix(#1850): see clearChatSessionStorage's doc comment above.
    clearChatSessionStorage();

    // fix(#1712): the Upload and STAC tabs' module-scoped in-flight
    // sessions are the same kind of identity-scoped residue — each records
    // the user id that started it and refuses adoption by a different one
    // (`peekUploadBatch`/`peekStacImport`), but that check only runs when
    // something next tries to adopt. Tearing down here, at the one identity
    // choke point, closes the window between a logout/switch and whatever
    // mounts next, rather than leaving it to be caught lazily.
    clearUploadBatch();
    clearStacImport();
    // fix(#1832): the queue a drop sits in before the upload-config query
    // settles is the same identity-scoped residue as the batch above, and
    // deserves the same choke point rather than only the ownerId check the
    // batch's own peek already does.
    clearPendingUploadFiles();
  });
}
