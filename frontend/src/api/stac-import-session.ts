import { importStacItems } from './stac';
import { useAuthStore } from '@/stores/auth-store';
import type {
  StacCollectionSummary,
  StacConnectResponse,
  StacImportItem,
  StacImportResponse,
  StacItemSummary,
  StacNextPage,
  StacSearchRequest,
} from '@/types/api';

/**
 * The in-flight STAC import, owned OUTSIDE React.
 *
 * Unlike the Service tab, this path has no job id to strand: `StacImportForm`
 * never calls `previewServiceLayer`, and `api/stac.ts` has no job-based step.
 * The connect/collections/search calls are read-only and safe to re-run on
 * remount. `importStacItems` (`POST /services/stac/import`) is the one call
 * that mutates, and it creates datasets SYNCHRONOUSLY, returning their outcome
 * in the response body, so nothing is left `pending` for the stale-job sweep to
 * collect. An unmount mid-import loses the created/skipped/error counts and the
 * per-item results, but the datasets it created are real and stay discoverable
 * in the catalog.
 *
 * This session protects the response, because losing the confirmation view is a
 * real (if milder) loss. Single-entry, matching `url-import-session.ts`: one
 * STAC import request covers the whole selected batch of items, not one entry
 * per item.
 *
 * It also carries the search CONTEXT (catalog, collections list, selected
 * collection, search results, selected item ids) the way the Upload session
 * carries the selected layer in `previewData`. Adopting only `importResult`
 * would leave "Back to Results" on the done screen (which sets `step` back to
 * `items`) rendering nothing: the `items` branch guards on `selectedCollection`
 * and `catalogInfo`, both null on a fresh mount, so it would fall through to
 * the empty URL form, and a missing `collections` would render an empty
 * breadcrumb list. Captured at the moment the import starts, since that is the
 * last point every one of these values is still known.
 *
 * Deliberately not persisted.
 */
export interface StacImportContext {
  catalogInfo: StacConnectResponse;
  collections: StacCollectionSummary[];
  selectedCollection: StacCollectionSummary;
  searchResult: { items: StacItemSummary[]; matched: number | null };
  selectedItemIds: string[];
  // The item-search state, so a reattached form shows the same filters and
  // can still load the next page.
  // Held in this module's memory only, like the rest of the context, so
  // Load more and Apply filters after a reattach reach a protected catalog.
  credential: {
    method: 'none' | 'bearer' | 'basic' | 'header';
    token: string;
    basicUsername: string;
    basicPassword: string;
    headerName: string;
    headerValue: string;
  };
  search: {
    startDate: string;
    endDate: string;
    bboxText: string;
    maxCloud: string;
    cloudCoverSeen: boolean;
    appliedFilters: Pick<
      StacSearchRequest,
      'bbox' | 'datetime_range' | 'max_cloud_cover' | 'cloud_cover_mode'
    >;
    nextPage: StacNextPage | null;
  };
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

// A literal control byte was here as the key
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
  catalogAuthRequired?: boolean,
): StacImportSession {
  const key = sessionKey(url, items);
  if (current && current.key === key && current.status === 'pending') {
    return current;
  }
  const promise = importStacItems(url, items, visibility, catalogAuthRequired);
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
