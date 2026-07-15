import { useCallback, useMemo } from 'react';
import { useDropzone, type FileRejection } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Upload } from 'lucide-react';
import { cn } from '@/lib/utils';
import { buildAcceptMap, deriveFormatBadges } from '@/lib/file-utils';
import { FormatPill, kindFromExtension } from './TypeTag';
import type { DataKind } from '@/types/api';

/** Client-side batch guard. Real caps (per-file size, dataset quota) are server-enforced. */
const MAX_BATCH_FILES = 25;

/**
 * Batch cap = the smaller of the UX limit and remaining quota. Floor at 1
 * (not 0 — react-dropzone treats maxFiles:0 as unlimited) so an at-cap user
 * can still drop one file and get the explicit server quota error + banner.
 * Shared with UploadForm's queued-drop flush (PR #274 follow-up) so both
 * enforce the same limit.
 */
export function effectiveBatchLimit(remainingQuota: number | null | undefined): number {
  return remainingQuota != null
    ? Math.min(MAX_BATCH_FILES, Math.max(1, remainingQuota))
    : MAX_BATCH_FILES;
}

interface FileDropzoneProps {
  onFilesAccepted: (files: File[]) => void;
  allowedExtensions?: string[];
  maxSizeMb?: number;
  /** Remaining per-user dataset quota; null = unlimited. Caps the batch so the
   *  UI never offers more files than the user can actually create. */
  remainingQuota?: number | null;
}

/** Group deduped extensions by data kind for the format pills */
function groupByKind(extensions: string[]): { kind: DataKind; ext: string }[] {
  const deduped = deriveFormatBadges(extensions);
  const order: DataKind[] = ['vector', 'raster', 'table'];
  const groups = new Map<DataKind, string[]>();

  for (const ext of deduped) {
    const kind = kindFromExtension(ext);
    if (!groups.has(kind)) groups.set(kind, []);
    groups.get(kind)!.push(ext);
  }

  const result: { kind: DataKind; ext: string }[] = [];
  for (const kind of order) {
    for (const ext of groups.get(kind) ?? []) {
      result.push({ kind, ext });
    }
  }
  return result;
}

export function FileDropzone({ onFilesAccepted, allowedExtensions, maxSizeMb, remainingQuota }: FileDropzoneProps) {
  const { t } = useTranslation('import');

  // ponytail: client-side UX guard only; the cap is enforced server-side at
  // upload. Atomic batch enforcement is a deferred worker-side concern.
  const effectiveMaxFiles = effectiveBatchLimit(remainingQuota);

  const accept = useMemo(() => {
    if (!allowedExtensions || allowedExtensions.length === 0) return undefined;
    return buildAcceptMap(allowedExtensions);
  }, [allowedExtensions]);

  const formatPills = useMemo(() => {
    if (!allowedExtensions || allowedExtensions.length === 0) return [];
    return groupByKind(allowedExtensions);
  }, [allowedExtensions]);

  const onDropRejected = useCallback((rejections: FileRejection[]) => {
    for (const { file, errors } of rejections) {
      const reason = errors.map((e) => e.message).join(', ');
      toast.error(t('dropzone.fileRejected', { filename: file.name, reason }));
    }
  }, [t]);

  const { getRootProps, getInputProps, isDragActive, isDragReject } =
    useDropzone({
      accept,
      maxFiles: effectiveMaxFiles,
      maxSize: maxSizeMb ? maxSizeMb * 1024 * 1024 : undefined,
      multiple: true,
      onDrop: (accepted) => {
        if (accepted.length > 0) onFilesAccepted(accepted);
      },
      onDropRejected,
    });

  return (
    <div
      {...getRootProps()}
      className={cn(
        'relative cursor-pointer rounded-2xl border-[1.5px] border-dashed px-8 py-14 text-center transition-[transform,background-color,border-color] duration-200 ease-out',
        'bg-card',
        isDragReject && 'border-destructive bg-destructive/10 scale-[1.005]',
        isDragActive && !isDragReject && 'border-primary bg-primary/5 scale-[1.005]',
        !isDragActive && !isDragReject && 'border-muted-foreground/30 hover:border-muted-foreground/50',
      )}
    >
      <input {...getInputProps({ 'aria-label': t('dropzone.ariaLabel') })} />

      {/* Glyph */}
      <div className="relative mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-border bg-surface-0 text-primary">
        <Upload className="size-7" strokeWidth={1.8} />
        {/* Dashed outer ring */}
        <span
          className="absolute -inset-1.5 rounded-[20px] border border-dashed border-primary/40 pointer-events-none"
          aria-hidden="true"
        />
      </div>

      <h3
        className={cn(
          'mb-1.5 text-lg font-medium tracking-tight',
          isDragReject && 'text-destructive',
          isDragActive && !isDragReject && 'text-primary',
        )}
      >
        {isDragReject
          ? t('dropzone.unsupportedType')
          : isDragActive
            ? t('dropzone.dropHere')
            : <>
                {t('dropzone.instructions', { defaultValue: 'Drop files here, or' })}{' '}
                <span className="font-semibold text-primary">{t('dropzone.browse', { defaultValue: 'browse' })}</span>{' '}
                {t('dropzone.toUpload', { defaultValue: 'to upload' })}
              </>}
      </h3>

      <p className="mb-5 text-xs text-muted-foreground">
        {t('dropzone.subtext', {
          max: effectiveMaxFiles,
          defaultValue: 'GeoLens will detect geometry, CRS, and schema before committing to the catalog. Batches up to {{max}} files.',
        })}
      </p>

      {/* Format pills */}
      {formatPills.length > 0 && (
        <div className="mb-3 flex flex-wrap justify-center gap-1.5">
          {formatPills.map(({ kind, ext }) => (
            <FormatPill key={ext} kind={kind} ext={ext} />
          ))}
        </div>
      )}

      <p className="eyebrow">
        {maxSizeMb != null
          ? t('dropzone.sizeLimitDynamic', { size: maxSizeMb, defaultValue: `Max ${maxSizeMb} MB per file` })
          : t('dropzone.sizeLimit')}{' '}
        · {t('dropzone.batchLimit', { max: effectiveMaxFiles, defaultValue: 'Up to {{max}} files per batch' })}
      </p>
    </div>
  );
}
