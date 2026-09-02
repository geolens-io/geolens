import { importStacItems } from './stac';
import { useAuthStore } from '@/stores/auth-store';
import type {
  StacCollectionSummary,
  StacConnectResponse,
  StacImportItem,
  StacImportResponse,
  StacItemSummary,
} from '@/types/api';

/**
 * fix(#1712): the in-flight STAC import, owned OUTSIDE React.
 *
 * SCOPE NOTE, checked against the code rather than assumed from the issue:
 * #1712 describes this tab's strand risk by analogy with the Service tab,
 * as `previewServiceLayer`'s `job_id`. That call does not exist on this
 * path — `StacImportForm` never imports `previewServiceLayer` (grep
 * confirms it), and `api/stac.ts` has no job-based step at all. The
 * connect/collections/search calls here are read-only and safe to simply
 * re-run on remount. `importStacItems` (`POST /services/stac/import`) is
 * the one call that mutates, and it creates datasets SYNCHRONOUSLY,
 * returning their outcome in the response body — no job id, nothing
 * `pending` for the stale-job sweep to collect. So an unmount mid-import
 * loses the created/skipped/error counts and the per-item results, but the
 * datasets it created are real and stay discoverable in the catalog — the
 * "papercut, not a leak" shape #1712 gives `RegisterForm`, which this call
 * turns out to share once its actual shape is checked instead of assumed.
 *
 * This session still protects the response, because losing the confirmation
 * view is a real (if milder) regression and the fix is the same shape as
 * the other tabs. Single-entry, matching `url-import-session.ts`: one STAC
 * import request covers the whole selected batch of items, not one entry
 * per item.
 *
 * fix(codex #1763 r3): also carries the search CONTEXT (catalog, selected
 * collection, search results, selected item ids) the way the Upload
 * session already carries the selected layer in `previewData` — an
 * adopted result used to restore only `importResult`, so the "Back to
 * Results" button on the done screen (which sets `step` back to `items`)
 * rendered nothing: the `items` branch guards on `selectedCollection` and
 * `catalogInfo`, both null on a fresh mount, so it fell through to the
 * empty URL form. Captured at the moment the import starts, since that is
 * the last point every one of those values is still known.
 *
 * Deliberately not persisted — same reasoning as #1708/#1712 generally.
 */
export interface StacImportContext {
  catalogInfo: StacConnectResponse;
  selectedCollection: StacCollectionSummary;
  searchResult: { items: StacItemSummary[]; matched: number | null };
  selectedItemIds: string[];
}

export interface StacImportSession {
  key: string;
  status: 'pending' | 'fulfilled' | 'rejected';
  result: StacImportResponse | null;
  error: unknown;
  promise: Promise<StacImportResponse>;
  ownerId: string | null;
  context: StacImportContext;
}

let current: StacImportSession | null = null;

// fix(codex #1763 r1): a literal control byte was here as the key
// separator, copied by analogy from url-import-session.ts's escaped
// constant without actually escaping it. A raw control byte makes ripgrep
// report this file as binary (verified: grep silently returns nothing for
// symbols that are present) and makes git treat the diff as binary, so the
// module drops out of repository-wide search and ordinary review tooling.
// A plain space is enough here: a STAC catalog URL cannot contain one
// unescaped, so the separator cannot collide with content on either side
// of it.
function sessionKey(url: string, items: StacImportItem[]): string {
  return `${url} ${items.map((i) => i.id).join(',')}`;
}

/**
 * Begin (or re-adopt) a STAC import. The settlement handlers are attached
 * HERE, not in the component, so they run whether or not anything is still
 * mounted, and mark the promise handled so an unmounted failure cannot
 * surface as an unhandled rejection.
 */
export function startStacImport(
  url: string,
  items: StacImportItem[],
  context: StacImportContext,
  visibility?: string,
): StacImportSession {
  const key = sessionKey(url, items);
  if (current && current.key === key && current.status === 'pending') {
    return current;
  }
  const promise = importStacItems(url, items, visibility);
  const session: StacImportSession = {
    key,
    status: 'pending',
    result: null,
    error: null,
    promise,
    ownerId: useAuthStore.getState().user?.id ?? null,
    context,
  };
  current = session;
  promise.then(
    (res) => {
      session.status = 'fulfilled';
      session.result = res;
    },
    (err) => {
      session.status = 'rejected';
      session.error = err;
    },
  );
  promise.catch(() => {});
  return session;
}

/**
 * The current session, if one exists AND belongs to the signed-in user.
 * Same ownership rule as #1713 / `peekUrlImport`: a session belonging to a
 * different identity is CLEARED rather than merely hidden.
 */
export function peekStacImport(): StacImportSession | null {
  if (!current) return null;
  if (current.ownerId !== (useAuthStore.getState().user?.id ?? null)) {
    clearStacImport();
    return null;
  }
  return current;
}

/** Release the session — an explicit reset, a settled adoption, or an
 * identity change. There is no reason to hold this past its one response. */
export function clearStacImport(): void {
  current = null;
}
