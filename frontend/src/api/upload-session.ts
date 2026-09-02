import { uploadFile, uploadPresigned, previewFile } from './ingest';
import { useAuthStore } from '@/stores/auth-store';
import type { FilePreviewResponse, RasterPreviewResponse } from '@/types/api';

/**
 * fix(#1712): the in-flight upload BATCH, owned OUTSIDE React.
 *
 * Mirrors `url-import-session.ts` (#1708) for the Upload tab: the Import
 * page renders tabs conditionally, so switching tabs mid-upload unmounts
 * `UploadForm`. The upload — and the preview call chained after it — keeps
 * running server-side regardless, staging a `pending` job with real bytes,
 * so if the returned `job_id` lands in dead component state the job and its
 * staged file are unreachable until the stale-pending sweep collects them.
 * Repeated tab switches accumulate them.
 *
 * Upload tracks a BATCH of files rather than one job (#1708 is single-job),
 * so this session is list-shaped: one entry per file, keyed by the same id
 * `UploadForm` assigns each row. Progress callbacks write into the entry
 * here instead of component state, so a mounted form subscribes rather than
 * owning the XHR.
 *
 * Every entry here is pre-commit (`uploading` through `preview`/
 * `upload-failed`). Once a commit is ISSUED for an entry — success or
 * failure, `handleCommitSingle`/`handleCommitAll`/`handleIngestAllLayers` —
 * it is removed from this session (`removeUploadSessionEntry`): holding it
 * past that point would let a later remount re-preview an already-processed
 * job, which the API refuses with 400. Commit itself is not protected here;
 * only the upload+preview phase this session owns.
 *
 * Deliberately not persisted to storage — same reasoning as #1708: this
 * covers a tab switch inside one SPA session, not a page reload, which
 * needs a server-side "my unfinished imports" lookup that does not exist
 * yet (#1712).
 */
export type UploadSessionEntryStatus =
  | 'uploading'
  | 'upload-failed'
  | 'previewing'
  | 'preview';

export interface UploadSessionEntry {
  id: string;
  fileName: string;
  status: UploadSessionEntryStatus;
  jobId: string | null;
  previewData: FilePreviewResponse | RasterPreviewResponse | null;
  error: unknown;
  /** Byte-transfer progress (0-1) during `uploading`; null once known/done. */
  progress: number | null;
}

interface UploadBatchSession {
  ownerId: string | null;
  entries: Map<string, UploadSessionEntry>;
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
    current = { ownerId, entries: new Map() };
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
export function startUploadEntry(id: string, file: File, presigned: boolean): void {
  const session = ensureSession();
  const entry: UploadSessionEntry = {
    id,
    fileName: file.name,
    status: 'uploading',
    jobId: null,
    previewData: null,
    error: null,
    progress: 0,
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
        ? await uploadPresigned(file, onProgress)
        : await uploadFile(file, onProgress);
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
 * The current batch, if one exists AND belongs to the signed-in user.
 *
 * Same ownership rule as #1713 / `peekUrlImport`: a session belonging to a
 * different identity is CLEARED rather than merely hidden, so it cannot
 * resurface if the original identity signs back in having missed whatever
 * the intervening user did to its staged bytes. `lib/auth-cache-reset.ts`
 * is the primary teardown on identity change; this is the second layer, so
 * a missed subscription there cannot reopen the hole.
 */
export function peekUploadBatch(): UploadSessionEntry[] | null {
  if (!current) return null;
  const ownerId = useAuthStore.getState().user?.id ?? null;
  if (current.ownerId !== ownerId) {
    clearUploadBatch();
    return null;
  }
  return current.entries.size > 0 ? Array.from(current.entries.values()) : null;
}

/** One entry's live state, if the batch still owns it. */
export function getUploadSessionEntry(id: string): UploadSessionEntry | null {
  return current?.entries.get(id) ?? null;
}

/**
 * Drop one entry — a commit was issued for it (see the module docstring),
 * or the user dismissed it from the review list. Clears the whole session
 * once the batch empties.
 */
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
