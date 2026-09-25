import { uploadFromUrl } from './ingest';
import { useAuthStore } from '@/stores/auth-store';
import type { CommitImportResponse, UploadKind, UploadResponse } from '@/types/api';

/**
 * fix(#1708 codex r19): the in-flight URL import, owned OUTSIDE React.
 *
 * The Import page renders its tabs conditionally (`activeTab === 'url' &&
 * <UrlImportForm />`), so switching tabs mid-import unmounts the form. The
 * request keeps running — the server is downloading, and will stage the
 * file and commit a `pending` job regardless — but the job id used to land
 * in dead component state. That left a job the user could not reach, plus
 * its staged bytes, until the stale-pending sweep collected it; repeated
 * switches accumulated them.
 *
 * Aborting on unmount does not fix that: the server does not stop fetching
 * when the client disconnects, so an abort strands exactly the same job. So
 * the promise and its settlement live here instead, at module scope, and
 * the form re-attaches on mount. A remount resumes the same import rather
 * than starting a second one.
 *
 * Deliberately not a store and not persisted: the reported failure is a tab
 * switch inside one SPA session, module state covers exactly that, and a
 * page reload cannot be recovered from anyway without a server-side
 * "my unfinished imports" lookup that does not exist yet (#1712).
 *
 * INVARIANT (fix #1708 codex r21) — every phase this session owns is
 * represented by a PROMISE that any mount can subscribe to, never by a
 * flag a mount samples. Outcomes are delivered to whatever is mounted when
 * they resolve, and captured here when nothing is.
 *
 * The distinction is not stylistic. r20 recorded the commit as a boolean
 * set before its await, so a mount arriving mid-commit sampled "committed"
 * and entered job tracking; if the commit then failed, the module flipped
 * the flag back but the mounted component never learned, and it polled a
 * job that was still pending and previewable. A promise has no such
 * window: subscribing mid-flight yields the real outcome whenever it
 * arrives.
 *
 * Phase by phase:
 *   - fetch  — `promise`, subscribed by every mount (r19).
 *   - commit — `commit`, subscribed by every mount (r21).
 *   - preview — deliberately NOT stored. It is re-derived from `jobId` on
 *     each mount and is idempotent while the job is `pending`, so it has
 *     the same property by construction: nothing is sampled, and there is
 *     no window in which stored state can disagree with the truth. If
 *     preview ever stops being safely repeatable, it needs a promise here
 *     like the other two.
 */
export interface UrlImportSession {
  /** Identifies the import so a remount can tell "mine" from a stale one. */
  key: string;
  /** What the URL was submitted as, so a remount shows the same choice. */
  kind: UploadKind | null;
  status: 'pending' | 'fulfilled' | 'rejected';
  /** Set once the server answers; the whole point of this module. */
  jobId: string | null;
  error: unknown;
  promise: Promise<UploadResponse>;
  /**
   * The commit operation once issued, or null before it is.
   *
   * fix(#1708 codex r21): a promise, not a boolean. A mount that arrives
   * while this is in flight subscribes and learns the real outcome —
   * success moves to tracking, failure returns to review with the job
   * still previewable. See the INVARIANT above for why the r20 boolean
   * could not express that.
   */
  commit: Promise<CommitImportResponse> | null;
  /**
   * Whether the committed job is a raster.
   *
   * fix(#1708 codex r22): the session's contract is "everything required to
   * resume the UI", and the job id alone did not meet it. `JobProgress`
   * gates the COG download, add-to-map and connection actions on this, and
   * a resumed mount has no `previewData` to derive it from — so a completed
   * raster import came back missing exactly the actions that make it
   * useful. Anything else the tracking view needs to render correctly
   * belongs here for the same reason.
   */
  isRaster: boolean;
  /**
   * The user this import belongs to, captured when it started.
   *
   * fix(#1708 codex r23): module state lives for the lifetime of the SPA,
   * so a logout followed by a login WITHOUT a page reload left this session
   * alive and the next identity was auto-attached to the previous user's
   * in-flight import and job id — preview 403s at best, and at worst a
   * second identity adopting a job that is not theirs. Same family as the
   * unmount work (state outliving the thing it belongs to), but across an
   * identity boundary.
   *
   * Null for an anonymous session, which therefore also fails to match any
   * signed-in identity.
   */
  ownerId: string | null;
}

let current: UrlImportSession | null = null;

// fix(#1708 codex r24): an explicit escape, never a literal control byte.
// The separator WAS a raw NUL here. It renders as a space in every viewer,
// and it made ripgrep classify this module as binary -- so an `rg` sweep
// over it returned nothing at all for patterns that are present, which is
// how an enumeration convention gets a false clean. Same delimiter and the
// same keys: NUL still cannot occur in a URL or a filename.
function sessionKey(url: string, filename?: string, kind?: UploadKind | null): string {
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
  kind?: UploadKind | null,
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
 *
 * fix(#1708 codex r21): stored as the promise itself rather than a flag,
 * so a mount arriving mid-commit resolves to the true outcome instead of
 * sampling an intention. Called BEFORE the caller awaits, so an unmount
 * during the await still leaves something to subscribe to.
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
 * fix(#1708 codex r23): the ownership check lives here, at the one place
 * anything adopts a session, so it is a structural guarantee rather than a
 * promise that every teardown path fires. A session belonging to someone
 * else is CLEARED rather than merely hidden — leaving it would let it
 * resurface if the original identity signed back in, still carrying a job
 * whose staging the intervening user could have touched.
 *
 * The auth subscription below is the second half: it clears promptly on
 * identity change rather than waiting for the next mount. Either alone
 * would close the reported hole; both together mean a missed teardown path
 * cannot reopen it.
 */
export function peekUrlImport(): UrlImportSession | null {
  if (!current) return null;
  if (current.ownerId !== (useAuthStore.getState().user?.id ?? null)) {
    clearUrlImport();
    return null;
  }
  return current;
}

/*
 * fix(#1708 codex r24): `urlImportIsUncancellable()` was removed here.
 *
 * It was written for the r22 reset guard, never imported, and it could not
 * have served that guard correctly: `commit != null` means "a commit was
 * ever ISSUED", which stays true through job tracking, where reset must
 * work. The session cannot tell an in-flight commit from a settled one —
 * only the component's `step` distinguishes them, so `step` is the single
 * source of truth for "an uncancellable request is pending". An exported
 * predicate whose name promised otherwise was a trap for the next reader
 * closing the next cell of the lifecycle table.
 */

/**
 * Release the session when the user is done with this import — an explicit
 * reset, or starting another.
 *
 * fix(#1708 codex r20): deliberately NOT called on commit success any more.
 * r19 cleared it there, which is exactly what made the tracking phase
 * unresumable: the job was running, the user had nothing to look at, and
 * the id was gone. The `commit` promise now carries that phase instead, so
 * the session survives into tracking and is released when the flow ends.
 */
export function clearUrlImport(): void {
  current = null;
}

// fix(#1708 codex r23): same teardown the analysis form store uses
// (stores/analysis-form-store.ts), for the same reason its comment gives —
// per-tab module state otherwise survives a logout and reaches whoever signs
// in next. Keyed on user IDENTITY rather than the token, so routine
// refresh-token rotation does not discard an import that is still running.
useAuthStore.subscribe((s, prev) => {
  if (s.user?.id !== prev.user?.id) {
    clearUrlImport();
  }
});
