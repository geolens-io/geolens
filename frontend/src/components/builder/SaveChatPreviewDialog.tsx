// feat(#1241): "Save as dataset…" for a plain chat query preview.
//
// The preview's whole FeatureCollection is already on the client (it is what
// the map overlay draws), so persisting it needs no new endpoint: wrap it in a
// File and push it through the same upload → preview → commit path the import
// page uses, reusing that page's metadata form so naming, description, and
// visibility behave identically wherever a dataset is created.
//
// This is a SNAPSHOT — a saved answer, frozen at save time, not a live query.
// The dialog says so, because the resulting dataset is indistinguishable from
// any other once it lands.
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ApiError } from '@/api/client';
import { commitImport, getJobStatus, previewFile, uploadFile } from '@/api/ingest';
import { ImportMetadataForm } from '@/components/import/ImportMetadataForm';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { splitGraphemes, truncateGraphemes } from '@/lib/text';
import type { CommitImportRequest } from '@/types/api';

/** RFC 7946: GeoJSON is WGS 84 by definition, so nothing has to detect it. */
const GEOJSON_EPSG = 4326;

/** Keeps a suggested name readable; the server's own bound is 500. */
const MAX_SUGGESTED_TITLE = 80;

const GEOJSON_EXT = '.geojson';

/**
 * feat(#1241 codex r5): the byte budget for the name the file is UPLOADED
 * under. Graphemes are the wrong unit for a filesystem: 80 emoji plus the
 * extension is 328 bytes, and local staging writes
 * `<job-uuid>_<basename>` into a directory entry Linux caps at 255 bytes, so a
 * multibyte prompt that passes the grapheme cap fails the upload with
 * ENAMETOOLONG (a 500). 120 leaves room for the uuid prefix and then some.
 */
const MAX_UPLOAD_NAME_BYTES = 120;

/** ASCII, so it always fits, for the case where not one grapheme does. */
const FALLBACK_UPLOAD_BASE = 'chat-result';

/**
 * The chat prompt, shaped into the name of the file we are about to upload.
 *
 * Returns a FILE name, not a title, because that is what `defaultName` means
 * at every other ImportMetadataForm call site — the form strips the extension
 * to seed its title field, so a prompt carrying its own dots ("buildings over
 * 3.5m") survives the round trip intact.
 */
export function chatPreviewFileName(prompt: string | undefined, fallbackTitle: string): string {
  const collapsed = (prompt ?? '')
    // Path separators have no business in a catalog entry's source filename.
    // The backend strips them too (`safe_upload_basename`) — doing it here
    // keeps the name the user is shown identical to the one that gets stored.
    // Newlines need no special case: the whitespace collapse below folds them.
    .replace(/[\\/]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const title = truncateGraphemes(collapsed, MAX_SUGGESTED_TITLE, '').trim() || fallbackTitle;
  return `${title}${GEOJSON_EXT}`;
}

/**
 * The same name, bounded by UTF-8 BYTES so it can be a filesystem entry.
 *
 * Kept separate from the name above deliberately: that one only ever reaches
 * the metadata form, where it becomes the suggested dataset title and no byte
 * limit applies. Trimming happens by grapheme, so a multibyte name loses whole
 * characters rather than splitting one down the middle.
 */
export function chatPreviewUploadName(fileName: string): string {
  const encoder = new TextEncoder();
  if (encoder.encode(fileName).length <= MAX_UPLOAD_NAME_BYTES) return fileName;

  const base = fileName.slice(0, -GEOJSON_EXT.length);
  let kept = '';
  for (const grapheme of splitGraphemes(base)) {
    const next = kept + grapheme;
    if (encoder.encode(`${next}${GEOJSON_EXT}`).length > MAX_UPLOAD_NAME_BYTES) break;
    kept = next;
  }
  return `${kept.trim() || FALLBACK_UPLOAD_BASE}${GEOJSON_EXT}`;
}

/**
 * feat(#1241 codex r3/r4): what became of a job whose commit we already sent.
 *
 * The backend refuses a repeat commit with 400 for EVERY non-pending status,
 * and those statuses do not mean the same thing. A commit that queued the
 * import leaves the job for the worker to claim (`running`, then `complete`).
 * A commit whose dispatch failed leaves it `failed` with its staged file
 * already deleted (`queue_ingest_job`'s orphan guard, which also returns 503),
 * so nothing on that job can ever succeed. Reading the 400 alone would call
 * both of them success.
 */
async function stagedJobOutcome(jobId: string): Promise<'queued' | 'dead' | 'unknown'> {
  try {
    const job = await getJobStatus(jobId);
    if (job.status === 'running' || job.status === 'complete') return 'queued';
    if (job.status === 'failed' || job.status === 'cancelled') return 'dead';
    // `pending` contradicts the 400 that sent us here (a race), and no other
    // status belongs to this flow. Claim nothing.
    return 'unknown';
  } catch {
    return 'unknown';
  }
}

interface SaveChatPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The previewed result, complete — callers must not offer this for a
   *  server-truncated preview (see `previewSaveMode`). */
  geojson: GeoJSON.FeatureCollection;
  /** The prompt that produced the preview, used to suggest a name. */
  prompt?: string;
}

export function SaveChatPreviewDialog({
  open,
  onOpenChange,
  geojson,
  prompt,
}: SaveChatPreviewDialogProps) {
  const { t } = useTranslation('builder');
  const [isCommitting, setIsCommitting] = useState(false);
  // feat(#1241 codex r2): the staged job survives a failed attempt, so a retry
  // resumes the chain instead of restarting it. Re-uploading would leave the
  // first job staged with nothing pointing at it, and worse: if a commit was
  // accepted and only its response was lost, a fresh job would queue a second
  // dataset from the same answer. Resuming puts that retry back on the job the
  // server already has, where the outcome is one dataset either way.
  const stagedRef = useRef<{
    jobId: string;
    previewed: boolean;
    /** Whether a commit for this job has already been sent (landed or not). */
    committed: boolean;
  } | null>(null);

  const fileName = chatPreviewFileName(prompt, t('savePreview.fallbackTitle'));

  const handleCommit = async (metadata: CommitImportRequest) => {
    if (isCommitting) return;
    setIsCommitting(true);
    try {
      if (!stagedRef.current) {
        const file = new File([JSON.stringify(geojson)], chatPreviewUploadName(fileName), {
          type: 'application/geo+json',
        });
        const { job_id } = await uploadFile(file);
        stagedRef.current = { jobId: job_id, previewed: false, committed: false };
      }
      const staged = stagedRef.current;
      if (!staged.previewed) {
        // Not skippable: preview is where a payload too large for the ingest
        // budget, or one the server cannot read, is rejected with an
        // actionable message, before a job is queued and a half-made dataset
        // exists. Recorded so a retry after a commit failure does not re-run
        // it (the job is already validated).
        await previewFile(staged.jobId);
        staged.previewed = true;
      }
      const isRecommit = staged.committed;
      staged.committed = true;
      try {
        await commitImport(staged.jobId, metadata);
      } catch (err) {
        // feat(#1241 codex r3): a commit whose response was lost still queued
        // the import, and the backend then refuses the repeat with 400 "Job
        // already processed" — forever, so the dialog could never close over a
        // dataset the server already had. Only ever on a RE-commit: a 400 on
        // the first attempt is a real rejection.
        //
        // Sending the second commit at all is safe. The worker claims a job
        // with one conditional UPDATE (pending -> running, fenced on
        // attempt_id, backend/app/platform/jobs/heartbeat.py), so if the
        // repeat is accepted instead of refused — the response was lost before
        // the worker picked the job up — the redundant task finds the row
        // claimed and no-ops. One dataset either way.
        if (!isRecommit || !(err instanceof ApiError) || err.status !== 400) throw err;
        // feat(#1241 codex r4): but that 400 covers every non-pending status,
        // including the job a failed dispatch marked `failed` (503 on the
        // first attempt, staged file already deleted). Ask what actually
        // happened rather than reading success into the refusal.
        const outcome = await stagedJobOutcome(staged.jobId);
        if (outcome !== 'queued') {
          // A dead job can never produce a dataset and its staged file is
          // gone, so stop resuming it: the next submit starts a fresh upload.
          if (outcome === 'dead') stagedRef.current = null;
          throw err;
        }
      }
      toast.success(t('savePreview.started'));
      onOpenChange(false);
    } catch (err) {
      // ApiError messages are already localized at the client boundary
      // (translateApiErrorDetail); anything else gets the generic sentence.
      toast.error(err instanceof ApiError ? err.message : t('savePreview.failed'));
    } finally {
      setIsCommitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // A commit is one request chain with no cancel — closing under it
        // would orphan the staged upload with the user believing they stopped.
        if (isCommitting && !next) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('savePreview.title')}</DialogTitle>
          <DialogDescription>{t('savePreview.description')}</DialogDescription>
        </DialogHeader>
        <ImportMetadataForm
          defaultName={fileName}
          detectedCrs={GEOJSON_EPSG}
          onCommit={(metadata) => void handleCommit(metadata)}
          isCommitting={isCommitting}
        />
      </DialogContent>
    </Dialog>
  );
}
