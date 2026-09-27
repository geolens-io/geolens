import { uploadFile, uploadPresigned, previewFile, commitImport } from './ingest';
import { commitFanOut } from './datasets';
import { ApiError } from './client';
import { useAuthStore } from '@/stores/auth-store';
import { randomId } from '@/lib/random-id';
import type {
  CommitImportRequest,
  DataKind,
  FilePreviewResponse,
  RasterPreviewResponse,
  TilesetPreviewResponse,
  PointCloudPreviewResponse,
  UploadKind,
} from '@/types/api';

/**
 * The Upload tab's batch, owned outside React so a tab switch cannot lose it.
 *
 * The Import page mounts one tab at a time, so switching tabs unmounts
 * `UploadForm` while its requests keep running server-side. Each file's
 * upload, preview and commit settle here, into the entry `UploadForm`
 * created for that file, and a remount adopts the batch as it stands.
 *
 * Commit is tracked as `committing`, then `committed` or `commit-failed`.
 * Only a `preview` entry can be re-previewed, and only a `preview` or
 * `commit-failed` one committed, so a job is never previewed again once its
 * commit is issued, and never committed twice. Settlement writes only into
 * the batch and entry that issued it, so a promise that settles after a
 * reset, a removal or an identity change is dropped. The batch is released
 * once a form has shown its tracking view (`releaseUploadBatch`).
 *
 * Not persisted: a page reload needs a server-side lookup of unfinished
 * imports, which does not exist.
 */
export type UploadSessionEntryStatus =
  | 'uploading'
  | 'upload-failed'
  | 'previewing'
  | 'preview'
  | 'committing'
  | 'committed'
  | 'commit-failed';

/** What a committed job is tracked as. */
export interface UploadSubmission {
  title: string;
  visibility: string;
  kind: DataKind;
}

/** One layer's outcome from an "ingest all layers" commit; `error` is the
 * server's message, or null when there is none. */
export interface FanOutLayerOutcome {
  layerName: string;
  status: 'fulfilled' | 'rejected';
  error: string | null;
}

export interface UploadSessionEntry {
  id: string;
  fileName: string;
  status: UploadSessionEntryStatus;
  jobId: string | null;
  previewData: FilePreviewResponse | RasterPreviewResponse | TilesetPreviewResponse | PointCloudPreviewResponse | null;
  kind: UploadKind | null;
  error: unknown;
  /** Byte-transfer progress (0-1) during `uploading`; null once known/done. */
  progress: number | null;
  /** How the latest commit was issued; selects the failure message. */
  commitVia: 'single' | 'all' | 'fan-out' | null;
  /** Set once `committed`. */
  submitted: UploadSubmission | null;
  /** Per-layer outcome of this entry's failed fan-out commit. */
  fanOut: FanOutLayerOutcome[] | null;
}

export interface UploadBatchSnapshot {
  entries: UploadSessionEntry[];
  /** A fan-out's per-layer results, until the form dismisses them. */
  fanOutResults: { entryId: string; results: FanOutLayerOutcome[] } | null;
  /** The batch was committed with "commit all as VRT". */
  autoOpenVrt: boolean;
}

interface UploadBatchSession {
  ownerId: string | null;
  entries: Map<string, UploadSessionEntry>;
  fanOutResults: UploadBatchSnapshot['fanOutResults'];
  autoOpenVrt: boolean;
}

let current: UploadBatchSession | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const l of listeners) l();
}

/** A mounted form subscribes to re-render whenever any entry changes. */
export function subscribeUploadBatch(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function ensureSession(): UploadBatchSession {
  const ownerId = useAuthStore.getState().user?.id ?? null;
  if (!current || current.ownerId !== ownerId) {
    current = { ownerId, entries: new Map(), fanOutResults: null, autoOpenVrt: false };
  }
  return current;
}

/**
 * Begin uploading one file as part of the current batch. Both outcomes are
 * handled HERE, at module scope, so the promise this kicks off never
 * rejects — there is no unhandled-rejection surface to attach a catch to,
 * unlike `url-import-session.ts`'s single job, whose promise is also
 * awaited directly by the component and therefore must reject.
 */
export function startUploadEntry(
  id: string,
  file: File,
  presigned: boolean,
  kind: UploadKind | null = null,
): void {
  const session = ensureSession();
  const entry: UploadSessionEntry = {
    id,
    fileName: file.name,
    status: 'uploading',
    jobId: null,
    previewData: null,
    kind,
    error: null,
    progress: 0,
    commitVia: null,
    submitted: null,
    fanOut: null,
  };
  session.entries.set(id, entry);
  notify();

  const onProgress = (p: number) => {
    if (session.entries.get(id) !== entry) return; // removed/replaced meanwhile
    entry.progress = p;
    notify();
  };

  void (async () => {
    try {
      const result = presigned
        ? await uploadPresigned(file, onProgress, kind)
        : await uploadFile(file, onProgress, kind);
      entry.jobId = result.job_id;
      entry.status = 'previewing';
      entry.progress = null;
      notify();

      const preview = await previewFile(result.job_id);
      entry.previewData = preview;
      entry.status = 'preview';
      notify();
    } catch (err) {
      entry.status = 'upload-failed';
      entry.error = err;
      entry.progress = null;
      notify();
    }
  })();
}

/**
 * Re-preview an entry under another layer of a multi-layer file. The result
 * lands in the session entry, whose `previewData.layer_name` is the selected
 * layer, so a remount and a later default commit both see the new choice.
 *
 * No-op unless the entry is in `preview`: a job whose commit was issued is
 * never previewed again.
 */
export function startLayerPreview(id: string, jobId: string, layerName: string): void {
  const entry = current?.entries.get(id);
  if (entry?.status !== 'preview') return;

  entry.status = 'previewing';
  notify();

  void (async () => {
    try {
      const preview = await previewFile(jobId, layerName);
      entry.previewData = preview;
      entry.status = 'preview';
      entry.error = null;
      notify();
    } catch (err) {
      // Stays reviewable under the PREVIOUS layer's preview data (untouched
      // above) — mirrors the component's original behavior of not blanking
      // the review just because a re-preview failed.
      entry.status = 'preview';
      entry.error = err;
      notify();
    }
  })();
}

interface CommitClaim {
  jobId: string;
  /** Applies the outcome and returns true, unless the batch or entry was replaced meanwhile. */
  settle: (apply: (session: UploadBatchSession, entry: UploadSessionEntry) => void) => boolean;
}

/** Mark an entry `committing` if it can be committed. */
function claimForCommit(
  id: string,
  via: NonNullable<UploadSessionEntry['commitVia']>,
): CommitClaim | null {
  const session = current;
  const entry = session?.entries.get(id);
  if (!session || !entry?.jobId) return null;
  if (entry.status !== 'preview' && entry.status !== 'commit-failed') return null;

  entry.status = 'committing';
  entry.commitVia = via;
  entry.error = null;
  entry.fanOut = null;
  notify();

  return {
    jobId: entry.jobId,
    settle: (apply) => {
      if (current !== session || session.entries.get(id) !== entry) return false;
      apply(session, entry);
      notify();
      return true;
    },
  };
}

function commitEntry(
  id: string,
  request: CommitImportRequest,
  submission: UploadSubmission,
  via: 'single' | 'all',
): Promise<boolean> {
  const claim = claimForCommit(id, via);
  if (!claim) return Promise.resolve(false);
  return commitImport(claim.jobId, request).then(
    () =>
      claim.settle((_session, entry) => {
        entry.status = 'committed';
        entry.submitted = submission;
      }),
    (err: unknown) => {
      claim.settle((_session, entry) => {
        entry.status = 'commit-failed';
        entry.error = err;
      });
      return false;
    },
  );
}

/**
 * Commit one reviewed entry. Resolves true once this batch records the
 * commit as succeeded; never rejects.
 */
export function commitUploadEntry(
  id: string,
  request: CommitImportRequest,
  submission: UploadSubmission,
): Promise<boolean> {
  return commitEntry(id, request, submission, 'single');
}

/** Commit several reviewed entries at once ("Commit All"); never rejects. */
export async function commitUploadEntries(
  commits: { id: string; request: CommitImportRequest; submission: UploadSubmission }[],
  { autoOpenVrt = false }: { autoOpenVrt?: boolean } = {},
): Promise<void> {
  if (autoOpenVrt && current) current.autoOpenVrt = true;
  await Promise.all(commits.map((c) => commitEntry(c.id, c.request, c.submission, 'all')));
}

/**
 * Commit every layer of a multi-layer entry as its own dataset. Each queued
 * layer joins the batch as a `committed` entry tracking its own job; the
 * parent is dropped when every layer queued, and otherwise stays
 * `commit-failed` with the per-layer outcome. Resolves with that outcome
 * once this batch records it, or null; never rejects.
 */
export function commitUploadFanOut(
  id: string,
  layers: { layer_name: string; title: string }[],
  kind: DataKind,
): Promise<FanOutLayerOutcome[] | null> {
  const claim = claimForCommit(id, 'fan-out');
  if (!claim) return Promise.resolve(null);
  const titles = new Map(layers.map((l) => [l.layer_name, l.title]));

  return commitFanOut(claim.jobId, layers).then(
    (response) => {
      const results: FanOutLayerOutcome[] = response.results.map((r) => ({
        layerName: r.layer_name,
        status: r.status === 'queued' ? 'fulfilled' : 'rejected',
        error: r.error,
      }));
      const recorded = claim.settle((session, entry) => {
        if (results.every((r) => r.status === 'fulfilled')) {
          session.entries.delete(id);
        } else {
          entry.status = 'commit-failed';
          entry.fanOut = results;
        }
        for (const r of response.results) {
          if (r.status !== 'queued' || !r.new_job_id) continue;
          const title = titles.get(r.layer_name) ?? r.layer_name;
          const childId = randomId();
          session.entries.set(childId, {
            id: childId,
            fileName: title,
            status: 'committed',
            jobId: r.new_job_id,
            previewData: null,
            kind: null,
            error: null,
            progress: null,
            commitVia: 'fan-out',
            submitted: { title, visibility: 'private', kind },
            fanOut: null,
          });
        }
        session.fanOutResults = { entryId: id, results };
      });
      return recorded ? results : null;
    },
    (err: unknown) => {
      const results: FanOutLayerOutcome[] = layers.map((l) => ({
        layerName: l.layer_name,
        status: 'rejected',
        error: err instanceof ApiError ? err.message : null,
      }));
      const recorded = claim.settle((session, entry) => {
        entry.status = 'commit-failed';
        entry.error = err;
        entry.fanOut = results;
        session.fanOutResults = { entryId: id, results };
      });
      return recorded ? results : null;
    },
  );
}

/** The form closed the fan-out results dialog. */
export function dismissUploadFanOutResults(): void {
  if (!current?.fanOutResults) return;
  current.fanOutResults = null;
  notify();
}

/**
 * The current batch, if it has entries AND belongs to the signed-in user.
 *
 * A batch belonging to a different identity is CLEARED rather than merely
 * hidden, so it cannot resurface if the original identity signs back in.
 * `lib/auth-cache-reset.ts` clears it on identity change too; this check
 * covers anything that reads the batch before that runs.
 */
export function peekUploadBatch(): UploadBatchSnapshot | null {
  if (!current) return null;
  const ownerId = useAuthStore.getState().user?.id ?? null;
  if (current.ownerId !== ownerId) {
    clearUploadBatch();
    return null;
  }
  if (current.entries.size === 0) return null;
  return {
    entries: Array.from(current.entries.values()),
    fanOutResults: current.fanOutResults,
    autoOpenVrt: current.autoOpenVrt,
  };
}

/** Drop one entry the user dismissed. Clears the session once it empties. */
export function removeUploadSessionEntry(id: string): void {
  if (!current) return;
  current.entries.delete(id);
  if (current.entries.size === 0) {
    current = null;
  }
  notify();
}

/** Release the whole batch — an explicit reset, or an identity change. */
export function clearUploadBatch(): void {
  current = null;
  notify();
}

/**
 * The form has shown this batch's tracking view, which it keeps rendering
 * from its own state. Releasing here means a later visit to the tab starts
 * from an empty dropzone instead of the finished batch.
 */
export function releaseUploadBatch(): void {
  current = null;
}

/**
 * fix(#1832): files dropped while the upload-config query was still
 * fetching, held at module scope — the other half of the same #1712
 * mechanism, for a window this session did not originally cover.
 *
 * `UploadForm` cannot validate (or start) a drop against extension/size/
 * quota rules before `useUploadConfig()` settles, so `handleFilesAccepted`
 * used to queue it in a plain `useState` and a `useEffect` flushed it once
 * the query resolved. That queue lived ONLY in component state: a tab
 * switch that unmounted the form before the flush effect ran discarded the
 * drop entirely, before it ever reached `startUploadEntry` above — so
 * nothing in `current.entries` existed for a remount to adopt, and the
 * report's "empty dropzone, no batch chip" is exactly that (not a case
 * where an entry existed and got lost; one was never created).
 *
 * Mirrors `current`'s shape rather than reusing it: these files have not
 * been validated yet, so they are not upload entries and must not be
 * treated as ones (no `UploadSessionEntry`, no `notify()` to a batch
 * subscriber). A mount-time rehydration (`peekPendingUploadFiles`) is
 * enough here, unlike the entries map, because nothing needs to react to
 * this queue while unmounted — the flush itself only ever runs from a
 * mounted `UploadForm`'s effect, gated on the live `configFetching` value
 * from its own `useUploadConfig()` hook.
 */
let pendingUploadFiles: File[] | null = null;
// The upload kind chosen when the files were dropped, so a remount uploads
// them as what they were dropped as.
let pendingUploadKind: UploadKind | null = null;

/** Queue files awaiting a still-fetching upload config; merges with any
 * already queued, matching the component-state behavior this replaces
 * (a second drop in the same window must not swallow the first). */
export function queuePendingUploadFiles(files: File[], kind: UploadKind | null = null): File[] {
  pendingUploadFiles = pendingUploadFiles ? [...pendingUploadFiles, ...files] : files;
  pendingUploadKind = kind;
  return pendingUploadFiles;
}

/** The upload kind the queued files were dropped under. */
export function peekPendingUploadKind(): UploadKind | null {
  return pendingUploadKind;
}

/** The queue, if a mount left one behind. Read on mount so a remount after
 * an unmount-during-fetch resumes waiting on it instead of starting blank. */
export function peekPendingUploadFiles(): File[] | null {
  return pendingUploadFiles;
}

/** Released once the flush effect consumes the queue (success or reject —
 * matches the pre-#1832 component state, which cleared it unconditionally
 * before validating each file). */
export function clearPendingUploadFiles(): void {
  pendingUploadFiles = null;
  pendingUploadKind = null;
}
