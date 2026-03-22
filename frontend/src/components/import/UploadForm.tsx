import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { uploadFile, previewFile, commitImport, uploadPresigned } from '@/api/ingest';
import { useUploadConfig } from '@/hooks/use-ingest';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { FileDropzone } from './FileDropzone';
import { BulkUploadProgress } from './BulkUploadProgress';
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

function stripExtension(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot > 0 ? filename.slice(0, dot) : filename;
}

export function UploadForm() {
  const { t } = useTranslation('import');
  const [phase, setPhase] = useState<BatchPhase>('idle');
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const { data: uploadConfig } = useUploadConfig();

  const updateEntry = useCallback((id: string, patch: Partial<FileEntry>) => {
    setEntries((prev) =>
      prev.map((e) => (e.id === id ? { ...e, ...patch } : e)),
    );
  }, []);

  const reset = useCallback(() => {
    setPhase('idle');
    setEntries([]);
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
          e.id === entryId ? { ...e, status: 'tracking' as const } : e,
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
          updateEntry(entry.id, { status: 'tracking' });
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
      <div className="space-y-4">
        <BulkReviewList
          entries={entries}
          onCommitSingle={handleCommitSingle}
          onCommitAll={handleCommitAll}
          onRemove={removeEntry}
          onSheetChange={handleSheetChange}
          isCommitting={entries.some((e) => e.status === 'committing')}
        />
        <Button variant="outline" onClick={reset}>
          {t('upload.startOver')}
        </Button>
      </div>
    );
  }

  if (phase === 'tracking') {
    return <BulkTrackingList entries={entries} onReset={reset} />;
  }

  // idle
  return (
    <div className="space-y-4">
      <FileDropzone onFilesAccepted={handleFilesAccepted} />
    </div>
  );
}
