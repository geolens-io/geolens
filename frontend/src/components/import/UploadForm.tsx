import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { uploadFile, previewFile, commitImport, uploadPresigned } from '@/api/ingest';
import { commitFanOut } from '@/api/datasets';
import { useUploadConfig } from '@/components/import/hooks/use-ingest';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { CheckCircle2, AlertCircle } from 'lucide-react';
import { FileDropzone } from './FileDropzone';
import { BulkUploadProgress } from './BulkUploadProgress';
import { inferImportedKind, isFilePreview, stripExtension } from './utils';
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

function buildErrorDisplay(err: unknown, fallbackKey: string, t: (key: string) => string): string {
  const msg = err instanceof ApiError ? err.message : t(fallbackKey);
  const hint = getErrorHint(msg, t);
  return hint ? `${msg}\n${hint}` : msg;
}

// GPKG-03 Phase 1058: concurrency-capped async pool for multi-layer fan-out.
// Runs at most `concurrency` workers in parallel; preserves result order.
async function runWithConcurrency<T, R>(
  items: T[],
  worker: (item: T) => Promise<R>,
  concurrency: number,
): Promise<PromiseSettledResult<R>[]> {
  const results: PromiseSettledResult<R>[] = new Array(items.length);
  let nextIndex = 0;
  const runners = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (true) {
      const i = nextIndex++;
      if (i >= items.length) return;
      try {
        results[i] = { status: 'fulfilled', value: await worker(items[i]) };
      } catch (err) {
        results[i] = { status: 'rejected', reason: err };
      }
    }
  });
  await Promise.all(runners);
  return results;
}

// GPKG-03 Phase 1058: per-layer result shape for the fan-out results modal.
type FanOutResult = {
  layerName: string;
  status: 'fulfilled' | 'rejected';
  error?: string;
};

interface UploadFormProps {
  onPhaseChange?: (phase: BatchPhase) => void;
}

export function UploadForm({ onPhaseChange }: UploadFormProps) {
  const { t } = useTranslation('import');
  const [phase, _setPhase] = useState<BatchPhase>('idle');
  const onPhaseChangeRef = useRef(onPhaseChange);
  onPhaseChangeRef.current = onPhaseChange;
  const setPhase = useCallback((p: BatchPhase) => {
    _setPhase(p);
    onPhaseChangeRef.current?.(p);
  }, []);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [autoOpenVrt, setAutoOpenVrt] = useState(false);
  // GPKG-03 Phase 1058: results modal state for the multi-layer fan-out
  const [fanOutResults, setFanOutResults] = useState<{
    entryId: string;
    results: FanOutResult[];
  } | null>(null);
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
  }, [setPhase]);

  // IMPORT-03 (Phase 1054): phase transitions were inlined inside setEntries
  // updaters, which violates React 19's "no setState during another
  // component's render" rule and fires the verbatim warning the audit
  // captured. Moving them into a single effect dep'd on `entries` runs the
  // transition AFTER React commits the entries change.
  useEffect(() => {
    if (phase === 'reviewing' && entries.length === 0) {
      setPhase('idle');
      return;
    }
    if (phase === 'reviewing' && entries.length > 0) {
      const allTerminal = entries.every(
        (e) =>
          e.status === 'tracking' ||
          e.status === 'upload-failed' ||
          e.status === 'commit-failed',
      );
      const hasTracking = entries.some((e) => e.status === 'tracking');
      if (allTerminal && hasTracking) {
        setPhase('tracking');
      }
    }
  }, [entries, phase, setPhase]);

  const handleFilesAccepted = async (files: File[]) => {
    if (phase !== 'idle') return;

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
          updateEntry(entry.id, {
            status: 'upload-failed',
            error: buildErrorDisplay(err, 'upload.uploadFailed', t),
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
      setEntries((prev) =>
        prev.map((e) =>
          e.id === entryId ? {
            ...e,
            status: 'tracking' as const,
            submittedTitle: request.title,
            submittedVisibility: request.visibility ?? 'private',
            submittedKind: inferImportedKind(e, request),
          } : e,
        ),
      );
      // Phase transition (reviewing → tracking) is handled by the useEffect
      // dep'd on `entries`; no inline setPhase call here (IMPORT-03).
      toast.success(t('upload.importStarted'));
    } catch (err) {
      updateEntry(entryId, { status: 'commit-failed', error: buildErrorDisplay(err, 'upload.commitFailed', t) });
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
          updateEntry(entry.id, { status: 'commit-failed', error: buildErrorDisplay(err, 'upload.bulkCommitFailed', t) });
        }
      }),
    );

    // Phase transition (reviewing → tracking) is handled by the useEffect
    // dep'd on `entries` after updateEntry calls settle (IMPORT-03).
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

  // GPKG-03 Phase 1058-04: fan-out handler — single commitFanOut call replaces
  // the N-separate-commit loop. Backend POST /ingest/commit-fan-out/{job_id}
  // dispatches one Procrastinate task per layer from a single uploaded file,
  // closing T-1058C-03 (backend previously rejected commits 2..N with 400).
  const handleIngestAllLayers = async (entryId: string) => {
    const entry = entries.find((e) => e.id === entryId);
    if (!entry?.jobId || !entry.previewData) return;
    if (!isFilePreview(entry.previewData)) return;
    const layers = entry.previewData.layers ?? [];
    if (layers.length <= 1) return;

    updateEntry(entryId, { status: 'committing' });

    const fileBase = stripExtension(entry.previewData.source_filename ?? entry.fileName) || 'Untitled';

    let results: FanOutResult[];
    try {
      // Single HTTP call — backend fans out N tasks from this one request.
      const response = await commitFanOut(
        entry.jobId,
        layers.map((layer) => ({
          layer_name: layer.name,
          title: `${fileBase}: ${layer.name}`,
        })),
      );

      results = response.results.map((r) => ({
        layerName: r.layer_name,
        status: r.status === 'queued' ? ('fulfilled' as const) : ('rejected' as const),
        error: r.error ?? undefined,
      }));
    } catch (err) {
      // Network-level failure — all layers failed.
      results = layers.map((layer) => ({
        layerName: layer.name,
        status: 'rejected' as const,
        error: err instanceof ApiError ? err.message : t('upload.commitFailed'),
      }));
    }

    const succeededCount = results.filter((r) => r.status === 'fulfilled').length;
    const failedCount = results.length - succeededCount;

    // Update entry status based on outcome.
    if (failedCount === 0) {
      updateEntry(entryId, { status: 'tracking' });
      toast.success(t('upload.multiLayerSuccess', { count: succeededCount }));
    } else if (succeededCount === 0) {
      updateEntry(entryId, {
        status: 'commit-failed',
        error: t('upload.multiLayerAllFailed'),
      });
    } else {
      updateEntry(entryId, {
        status: 'commit-failed',
        error: t('upload.multiLayerPartialFailed', { succeeded: succeededCount, failed: failedCount }),
      });
    }

    setFanOutResults({ entryId, results });
  };

  const removeEntry = (entryId: string) => {
    setEntries((prev) => prev.filter((e) => e.id !== entryId));
    // Phase transition (reviewing → idle when empty) is handled by the
    // useEffect dep'd on `entries` (IMPORT-03).
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
          onCommitAllAsVrt={handleCommitAllAsVrt}
          onRemove={removeEntry}
          onSheetChange={handleSheetChange}
          // GPKG-03 Phase 1058: wire fan-out handler
          onIngestAllLayers={handleIngestAllLayers}
          isCommitting={entries.some((e) => e.status === 'committing')}
        />
        <Button variant="outline" onClick={reset}>
          {t('upload.startOver')}
        </Button>

        {/* GPKG-03 Phase 1058: results modal shown after fan-out settles */}
        {fanOutResults && (
          <Dialog
            open
            onOpenChange={(open) => {
              if (!open) setFanOutResults(null);
            }}
          >
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t('upload.multiLayerResultsTitle')}</DialogTitle>
                <DialogDescription>
                  {t('upload.multiLayerResultsSummary', {
                    succeeded: fanOutResults.results.filter((r) => r.status === 'fulfilled').length,
                    failed: fanOutResults.results.filter((r) => r.status === 'rejected').length,
                  })}
                </DialogDescription>
              </DialogHeader>
              <ul className="space-y-1 text-sm">
                {fanOutResults.results.map((r) => (
                  <li key={r.layerName} className="flex items-center gap-2">
                    {r.status === 'fulfilled' ? (
                      <CheckCircle2 className="size-4 text-success shrink-0" />
                    ) : (
                      <AlertCircle className="size-4 text-destructive shrink-0" />
                    )}
                    <span className="font-mono text-xs">{r.layerName}</span>
                    {r.error && <span className="text-xs text-destructive">{r.error}</span>}
                  </li>
                ))}
              </ul>
              <DialogFooter>
                {fanOutResults.results.some((r) => r.status === 'rejected') && (
                  <Button
                    variant="outline"
                    onClick={() => setFanOutResults(null)}
                  >
                    {t('upload.multiLayerRetryClose')}
                  </Button>
                )}
                <Button onClick={() => setFanOutResults(null)}>{t('common:close')}</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}
      </div>
    );
  }

  if (phase === 'tracking') {
    return <BulkTrackingList entries={entries} onReset={reset} autoOpenVrt={autoOpenVrt} />;
  }

  // idle
  return (
    <FileDropzone onFilesAccepted={handleFilesAccepted} allowedExtensions={allowedExtensions} maxSizeMb={maxSizeMb} />
  );
}
