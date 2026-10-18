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
 * The connect/collections/search calls are read-only and safe to re-run on
 * remount. `importStacItems` (`POST /services/stac/import`) creates datasets
 * SYNCHRONOUSLY and returns the outcome in the response body, so no job is left
 * `pending` for the stale-job sweep. An unmount mid-import loses the
 * created/skipped/error counts and per-item results, but the datasets stay in
 * the catalog; this session protects that response.
 *
 * Single-entry, like `url-import-session.ts`: one request covers the whole
 * selected batch.
 *
 * It also carries the search CONTEXT (catalog, collections, selected
 * collection, results, selected item ids). Adopting only `importResult` would
 * leave "Back to Results" rendering the empty URL form, since the `items` branch
 * guards on `selectedCollection` and `catalogInfo`, both null on a fresh mount.
 * Captured when the import starts, the last point every value is still known.
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
// A plain space separates the parts: a STAC catalog URL cannot contain one
// unescaped, so the separator cannot collide with content. (A raw control byte
// would make ripgrep and git treat this file as binary.)
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
 * The current session, if one exists AND belongs to the signed-in user. A
 * session belonging to a different identity is CLEARED rather than hidden.
 */
export function peekStacImport(): StacImportSession | null {
  if (!current) return null;
  if (current.ownerId !== (useAuthStore.getState().user?.id ?? null)) {
    clearStacImport();
    return null;
  }
  return current;
}

/** Release the session: an explicit reset, a settled adoption, or an identity change. */
export function clearStacImport(): void {
  current = null;
}
