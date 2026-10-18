import { uploadFromUrl } from './ingest';
import { useAuthStore } from '@/stores/auth-store';
import type { CommitImportResponse, UrlUploadKind, UploadResponse } from '@/types/api';

/**
 * The in-flight URL import, owned OUTSIDE React.
 *
 * The Import page unmounts the form when the tab changes, but the server keeps
 * downloading and commits a `pending` job regardless. Holding the promise at
 * module scope lets the form re-attach on mount instead of losing the job id
 * (and its staged bytes) to dead component state. Aborting on unmount would not
 * help: the server does not stop fetching when the client disconnects.
 *
 * Deliberately not a store and not persisted: module state covers a tab switch
 * inside one SPA session, and a page reload needs a server-side "my unfinished
 * imports" lookup that does not exist yet (#1712).
 *
 * INVARIANT: every phase this session owns is a PROMISE any mount can subscribe
 * to, never a flag a mount samples. With a boolean set before the commit's
 * await, a mount arriving mid-commit would enter job tracking, and if the commit
 * then failed the mounted component would never learn and would poll a job that
 * is still pending.
 *
 * Phases:
 *   - fetch   `promise`, subscribed by every mount.
 *   - commit  `commit`, subscribed by every mount.
 *   - preview not stored: it is re-derived from `jobId` on each mount and is
 *     idempotent while the job is `pending`. If it stops being safely
 *     repeatable, it needs a promise here like the other two.
 */
export interface UrlImportSession {
  /** Identifies the import so a remount can tell "mine" from a stale one. */
  key: string;
  /** What the URL was submitted as, so a remount shows the same choice. */
  kind: UrlUploadKind | null;
  status: 'pending' | 'fulfilled' | 'rejected';
  /** Set once the server answers; the whole point of this module. */
  jobId: string | null;
  error: unknown;
  promise: Promise<UploadResponse>;
  /**
   * The commit operation once issued, or null before it is. A promise, not a
   * boolean: see the INVARIANT above.
   */
  commit: Promise<CommitImportResponse> | null;
  /**
   * Whether the committed job is a raster. `JobProgress` gates the COG
   * download, add-to-map and connection actions on this, and a resumed mount
   * has no `previewData` to derive it from.
   */
  isRaster: boolean;
  /**
   * The user this import belongs to, captured when it started. Module state
   * outlives a logout/login without a page reload, so without this the next
   * identity would adopt the previous user's in-flight import and job id.
   * Null for an anonymous session, which matches no signed-in identity.
   */
  ownerId: string | null;
}

let current: UrlImportSession | null = null;

// An explicit escape, never a literal control byte: a raw NUL made ripgrep
// classify this module as binary. NUL still cannot occur in a URL or filename.
function sessionKey(url: string, filename?: string, kind?: UrlUploadKind | null): string {
  return `${url}\u0000${filename ?? ''}\u0000${kind ?? ''}`;
}

/**
 * Begin (or re-adopt) a URL import.
 *
 * The settlement handlers are attached HERE, not in the component, so they
 * run whether or not anything is still mounted — that is what keeps the job
 * id out of dead state. They also mark the promise as handled, so an
 * unmounted rejection cannot surface as an unhandled rejection.
 */
export function startUrlImport(
  url: string,
  filename?: string,
  kind?: UrlUploadKind | null,
): UrlImportSession {
  const key = sessionKey(url, filename, kind);
  if (current && current.key === key && current.status !== 'rejected') {
    return current;
  }
  const promise = uploadFromUrl(url, filename, kind);
  const session: UrlImportSession = {
    key,
    kind: kind ?? null,
    status: 'pending',
    jobId: null,
    error: null,
    promise,
    commit: null,
    isRaster: false,
    ownerId: useAuthStore.getState().user?.id ?? null,
  };
  current = session;
  promise.then(
    (res) => {
      session.status = 'fulfilled';
      session.jobId = res.job_id;
    },
    (err) => {
      session.status = 'rejected';
      session.error = err;
    },
  );
  return session;
}

/**
 * Hand the session the commit operation, so any mount can subscribe to it.
 * Called BEFORE the caller awaits, so an unmount during the await still leaves
 * something to subscribe to.
 */
export function attachUrlImportCommit(
  promise: Promise<CommitImportResponse>,
  isRaster: boolean,
): void {
  const session = current;
  if (!session) return;
  session.commit = promise;
  session.isRaster = isRaster;
  // Mark the rejection handled HERE so a failure with nothing mounted
  // cannot surface as an unhandled rejection. Subscribers still see it:
  // this attaches a second handler, it does not consume the outcome.
  promise.catch(() => {});
}

/**
 * The current session, if one exists AND belongs to the signed-in user.
 *
 * A session belonging to someone else is CLEARED rather than hidden, so it
 * cannot resurface if the original identity signs back in with a job whose
 * staging the intervening user could have touched. The auth subscription below
 * clears promptly on identity change; the two together mean a missed teardown
 * path cannot reopen the hole.
 */
export function peekUrlImport(): UrlImportSession | null {
  if (!current) return null;
  if (current.ownerId !== (useAuthStore.getState().user?.id ?? null)) {
    clearUrlImport();
    return null;
  }
  return current;
}

/**
 * Release the session when the user is done with this import — an explicit
 * reset, or starting another. Not called on commit success: the `commit`
 * promise carries the tracking phase, so the session survives into tracking.
 */
export function clearUrlImport(): void {
  current = null;
}

// Per-tab module state otherwise survives a logout and reaches whoever signs
// in next. Keyed on user IDENTITY rather than the token, so routine
// refresh-token rotation does not discard an import that is still running.
useAuthStore.subscribe((s, prev) => {
  if (s.user?.id !== prev.user?.id) {
    clearUrlImport();
  }
});
