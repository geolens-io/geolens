import { useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, CircleDashed, HardDriveUpload } from 'lucide-react';
import { uploadFile, previewFile, commitImport, uploadPresigned } from '@/api/ingest';
import { useUploadConfig } from '@/components/import/hooks/use-ingest';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { FileDropzone } from './FileDropzone';
import { BulkUploadProgress } from './BulkUploadProgress';
import { inferImportedKind, stripExtension } from './utils';
import { BulkReviewList } from './BulkReviewList';
import { BulkTrackingList } from './BulkTrackingList';
import type { FileEntry, BatchPhase, CommitImportRequest } from '@/types/api';
import { ApiError } from '@/api/client';


function getErrorHint(errorMsg: string, t: (key: string) => string): string | null {
  const lower = errorMsg.toLowerCase();
  if (lower.includes('crs') || lower.includes('projection') || lower.includes('srid')) {
    return t('upload.hintCrs');
  }
  if (lower.includes('encoding') || lower.includes('charset') || lower.includes('utf')) {
    return t('upload.hintEncoding');
  }
  if (lower.includes('geometry') || lower.includes('geometr')) {
    return t('upload.hintGeometry');
  }
  if (lower.includes('empty') || lower.includes('no features') || lower.includes('no records')) {
    return t('upload.hintEmpty');
  }
  return null;
}

function UploadWorkspaceSidebar({
  phase,
  entries,
  allowedExtensions,
  maxSizeMb,
}: {
  phase: Extract<BatchPhase, 'idle' | 'reviewing'>;
  entries: FileEntry[];
  allowedExtensions?: string[];
  maxSizeMb?: number;
}) {
  const { t } = useTranslation('import');

  const readyCount = entries.filter((entry) => entry.status === 'preview').length;
  const failedCount = entries.filter((entry) => entry.status === 'upload-failed' || entry.status === 'commit-failed').length;
  const extensionPreview = allowedExtensions?.slice(0, 8).join(', ');

  return (
    <div className="space-y-4" data-testid="import-upload-sidebar">
      <Card className="border-border/50 bg-background/95 shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {t('upload.workspaceTitle', { defaultValue: 'Ingest workflow' })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex items-start gap-3">
            <HardDriveUpload className="mt-0.5 size-4 text-primary" />
            <div>
              <p className="font-medium">{t('tabs.upload')}</p>
              <p className="text-muted-foreground">
                {t('upload.workflowUpload', { defaultValue: 'Drop one or more files to create a batch.' })}
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <CircleDashed className="mt-0.5 size-4 text-muted-foreground" />
            <div>
              <p className="font-medium">{t('upload.reviewTitle', { defaultValue: 'Review detection' })}</p>
              <p className="text-muted-foreground">
                {t('upload.workflowReview', { defaultValue: 'Confirm geometry, sheets, and import defaults before the jobs begin.' })}
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 size-4 text-success" />
            <div>
              <p className="font-medium">{t('bulk.importProgress')}</p>
              <p className="text-muted-foreground">
                {t('upload.workflowTrack', { defaultValue: 'Track ingest completion and open datasets as soon as they are ready.' })}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/50 bg-muted/10 shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {phase === 'idle'
              ? t('upload.beforeYouUpload', { defaultValue: 'Before you upload' })
              : t('upload.batchSummary', { defaultValue: 'Batch summary' })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          {phase === 'idle' ? (
            <>
              <p>
                {t('upload.idleHint', {
                  defaultValue: 'Use Upload File for local datasets GeoLens should ingest and manage directly.',
                })}
              </p>
              {extensionPreview ? (
                <p>
                  {t('upload.supportedFormats', {
                    defaultValue: 'Supported formats: {{formats}}',
                    formats: extensionPreview,
                  })}
                </p>
              ) : null}
              {maxSizeMb ? (
                <p>
                  {t('upload.maxFileSize', {
                    defaultValue: 'Maximum file size: {{size}} MB',
                    size: maxSizeMb,
                  })}
                </p>
              ) : null}
              <p>
                {t('upload.idleSecondaryHint', {
                  defaultValue: 'Use Register Table for existing database tables, or Service URL for remote services you do not want to upload.',
                })}
              </p>
            </>
          ) : (
            <>
              <p>
                {t('upload.batchFiles', {
                  defaultValue: '{{count}} files currently in this batch.',
                  count: entries.length,
                })}
              </p>
              <p>
                {t('upload.batchReady', {
                  defaultValue: '{{count}} files are ready to import.',
                  count: readyCount,
                })}
              </p>
              <p>
                {t('upload.batchNeedsAttention', {
                  defaultValue: '{{count}} files need attention before they can continue.',
                  count: failedCount,
                })}
              </p>
              <p>
                {t('upload.reviewHint', {
                  defaultValue: 'Use the batch actions to apply defaults quickly, then start the ingest jobs once the previews look correct.',
                })}
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function UploadForm() {
  const { t } = useTranslation('import');
  const [phase, setPhase] = useState<BatchPhase>('idle');
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [autoOpenVrt, setAutoOpenVrt] = useState(false);
  const { data: uploadConfig } = useUploadConfig();

  const allowedExtensions = useMemo(
    () => uploadConfig?.allowed_extensions?.split(',').map(e => e.trim()).filter(Boolean),
    [uploadConfig?.allowed_extensions],
  );
  const maxSizeMb = uploadConfig ? Math.round(uploadConfig.max_file_size_bytes / (1024 * 1024)) : undefined;

  const updateEntry = useCallback((id: string, patch: Partial<FileEntry>) => {
    setEntries((prev) =>
      prev.map((e) => (e.id === id ? { ...e, ...patch } : e)),
    );
  }, []);

  const reset = useCallback(() => {
    setPhase('idle');
    setEntries([]);
    setAutoOpenVrt(false);
  }, []);

  const handleFilesAccepted = async (files: File[]) => {
    // Duplicate detection against existing entries
    const existing = new Set(
      entries.map((e) => `${e.fileName}|${e.file?.size ?? ''}|${e.file?.lastModified ?? ''}`),
    );
    const unique = files.filter((f) => {
      const key = `${f.name}|${f.size}|${f.lastModified}`;
      if (existing.has(key)) {
        toast.warning(t('upload.duplicateSkipped', { name: f.name }));
        return false;
      }
      existing.add(key);
      return true;
    });

    if (unique.length === 0) return;

    const newEntries: FileEntry[] = unique.map((file) => ({
      id: crypto.randomUUID(),
      file,
      fileName: file.name,
      status: 'uploading' as const,
      jobId: null,
      previewData: null,
      error: null,
      submittedTitle: null,
      submittedVisibility: null,
      submittedKind: null,
    }));

    setEntries(newEntries);
    setPhase('uploading');

    await Promise.allSettled(
      newEntries.map(async (entry) => {
        try {
          const result = uploadConfig?.presigned_uploads
            ? await uploadPresigned(entry.file!)
            : await uploadFile(entry.file!);
          updateEntry(entry.id, { jobId: result.job_id, status: 'previewing' });

          const preview = await previewFile(result.job_id);
          updateEntry(entry.id, {
            previewData: preview,
            status: 'preview',
            file: null,
          });
        } catch (err) {
          const msg =
            err instanceof ApiError ? err.message : t('upload.uploadFailed');
          const hint = getErrorHint(msg, t);
          const errorDisplay = hint ? `${msg}\n${hint}` : msg;
          updateEntry(entry.id, {
            status: 'upload-failed',
            error: errorDisplay,
            file: null,
          });
        }
      }),
    );

    setPhase('reviewing');
  };

  const handleCommitSingle = async (
    entryId: string,
    request: CommitImportRequest,
  ) => {
    const entry = entries.find((e) => e.id === entryId);
    if (!entry?.jobId) return;

    updateEntry(entryId, { status: 'committing' });

    try {
      await commitImport(entry.jobId, request);
      setEntries((prev) => {
        const updated = prev.map((e) =>
          e.id === entryId ? {
            ...e,
            status: 'tracking' as const,
            submittedTitle: request.title,
            submittedVisibility: request.visibility ?? 'private',
            submittedKind: inferImportedKind(e, request),
          } : e,
        );
        const allDone = updated.every(
          (e) =>
            e.status === 'tracking' ||
            e.status === 'upload-failed' ||
            e.status === 'commit-failed',
        );
        if (allDone) setPhase('tracking');
        return updated;
      });
      toast.success(t('upload.importStarted'));
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : t('upload.commitFailed');
      const hint = getErrorHint(msg, t);
      const errorDisplay = hint ? `${msg}\n${hint}` : msg;
      updateEntry(entryId, { status: 'commit-failed', error: errorDisplay });
    }
  };

  const handleCommitAll = async () => {
    const reviewable = entries.filter(
      (e) => e.status === 'preview' && e.jobId,
    );
    if (reviewable.length === 0) return;

    // Mark all as committing
    setEntries((prev) =>
      prev.map((e) =>
        e.status === 'preview' && e.jobId
          ? { ...e, status: 'committing' as const }
          : e,
      ),
    );

    await Promise.allSettled(
      reviewable.map(async (entry) => {
        try {
          const name =
            stripExtension(
              entry.previewData?.source_filename ?? entry.fileName,
            ) || 'Untitled';
          await commitImport(entry.jobId!, { title: name });
          updateEntry(entry.id, {
            status: 'tracking',
            submittedTitle: name,
            submittedVisibility: 'private',
            submittedKind: inferImportedKind(entry),
          });
        } catch (err) {
          const msg =
            err instanceof ApiError ? err.message : t('upload.bulkCommitFailed');
          const hint = getErrorHint(msg, t);
          const errorDisplay = hint ? `${msg}\n${hint}` : msg;
          updateEntry(entry.id, { status: 'commit-failed', error: errorDisplay });
        }
      }),
    );

    setPhase('tracking');
  };

  const handleCommitAllAsVrt = async () => {
    setAutoOpenVrt(true);
    await handleCommitAll();
  };

  const handleSheetChange = async (entryId: string, layerName: string) => {
    const entry = entries.find((e) => e.id === entryId);
    if (!entry?.jobId) return;

    updateEntry(entryId, { status: 'previewing' });
    try {
      const preview = await previewFile(entry.jobId, layerName);
      updateEntry(entryId, { previewData: preview, status: 'preview' });
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : t('upload.uploadFailed');
      updateEntry(entryId, { status: 'preview', error: msg });
    }
  };

  const removeEntry = (entryId: string) => {
    setEntries((prev) => {
      const updated = prev.filter((e) => e.id !== entryId);
      if (updated.length === 0) setPhase('idle');
      return updated;
    });
  };

  if (phase === 'uploading') {
    return <BulkUploadProgress entries={entries} />;
  }

  if (phase === 'reviewing') {
    return (
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="space-y-4 min-w-0">
          <BulkReviewList
            entries={entries}
            onCommitSingle={handleCommitSingle}
            onCommitAll={handleCommitAll}
            onCommitAllAsVrt={handleCommitAllAsVrt}
            onRemove={removeEntry}
            onSheetChange={handleSheetChange}
            isCommitting={entries.some((e) => e.status === 'committing')}
          />
          <Button variant="outline" onClick={reset}>
            {t('upload.startOver')}
          </Button>
        </div>
        <UploadWorkspaceSidebar
          phase="reviewing"
          entries={entries}
          allowedExtensions={allowedExtensions}
          maxSizeMb={maxSizeMb}
        />
      </div>
    );
  }

  if (phase === 'tracking') {
    return <BulkTrackingList entries={entries} onReset={reset} autoOpenVrt={autoOpenVrt} />;
  }

  // idle
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_18rem]">
      <div className="space-y-4 min-w-0">
        <FileDropzone onFilesAccepted={handleFilesAccepted} allowedExtensions={allowedExtensions} maxSizeMb={maxSizeMb} />
      </div>
      <UploadWorkspaceSidebar
        phase="idle"
        entries={entries}
        allowedExtensions={allowedExtensions}
        maxSizeMb={maxSizeMb}
      />
    </div>
  );
}
