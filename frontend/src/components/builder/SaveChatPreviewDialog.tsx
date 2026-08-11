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
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ApiError } from '@/api/client';
import { commitImport, previewFile, uploadFile } from '@/api/ingest';
import { ImportMetadataForm } from '@/components/import/ImportMetadataForm';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { truncateGraphemes } from '@/lib/text';
import type { CommitImportRequest } from '@/types/api';

/** RFC 7946: GeoJSON is WGS 84 by definition, so nothing has to detect it. */
const GEOJSON_EPSG = 4326;

/** Keeps a suggested name readable; the server's own bound is 500. */
const MAX_SUGGESTED_TITLE = 80;

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
  return `${title}.geojson`;
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

  const fileName = chatPreviewFileName(prompt, t('savePreview.fallbackTitle'));

  const handleCommit = async (metadata: CommitImportRequest) => {
    if (isCommitting) return;
    setIsCommitting(true);
    try {
      const file = new File([JSON.stringify(geojson)], fileName, {
        type: 'application/geo+json',
      });
      const { job_id } = await uploadFile(file);
      // Not skippable: preview is where a payload too large for the ingest
      // budget, or one the server cannot read, is rejected with an actionable
      // message — before a job is queued and a half-made dataset exists.
      await previewFile(job_id);
      await commitImport(job_id, metadata);
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
