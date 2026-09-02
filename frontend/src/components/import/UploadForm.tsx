import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { previewFile, commitImport } from '@/api/ingest';
import { commitFanOut } from '@/api/datasets';
import {
  startUploadEntry,
  subscribeUploadBatch,
  peekUploadBatch,
  getUploadSessionEntry,
  removeUploadSessionEntry,
  clearUploadBatch,
} from '@/api/upload-session';
import { useUploadConfig } from '@/components/import/hooks/use-ingest';
import { queryKeys } from '@/lib/query-keys';
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
import { FileDropzone, effectiveBatchLimit } from './FileDropzone';
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

// Quota (422) errors are identical across every file in a batch — surface them
// once as a banner instead of repeating the same red line on each row.
function quotaMessage(err: unknown): string | null {
  return err instanceof ApiError && err.message.startsWith('Dataset quota exceeded')
    ? err.message
    : null;
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
  const queryClient = useQueryClient();
  const [phase, _setPhase] = useState<BatchPhase>('idle');
  const onPhaseChangeRef = useRef(onPhaseChange);
  onPhaseChangeRef.current = onPhaseChange;
  const setPhase = useCallback((p: BatchPhase) => {
    _setPhase(p);
    onPhaseChangeRef.current?.(p);
  }, []);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [autoOpenVrt, setAutoOpenVrt] = useState(false);
  // Batch-level quota notice (the "X of Y datasets used" detail), shown once.
  const [quotaNotice, setQuotaNotice] = useState<string | null>(null);
  // GPKG-03 Phase 1058: results modal state for the multi-layer fan-out
  const [fanOutResults, setFanOutResults] = useState<{
    entryId: string;
    results: FanOutResult[];
  } | null>(null);
  // Files dropped while the quota query is still fetching (initial load OR the
  // refetch-on-mount refresh) are held here and processed once it settles.
  // Disabling the dropzone during that window (the previous design) made
  // react-dropzone silently swallow drops with no feedback and no same-page
  // recovery (PR #274 follow-up).
  const [pendingFiles, setPendingFiles] = useState<File[] | null>(null);
  // isFetching (not just isPending) so drops during the refetchOnMount
  // background refresh are also deferred — otherwise the cached-but-stale
  // quota would briefly apply on remount before the live GET lands (Codex P2
  // on PR #274).
  const { data: uploadConfig, isFetching: configFetching } = useUploadConfig();

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
    setQuotaNotice(null);
    setPendingFiles(null);
    // fix(#1712): release the batch session along with local state — an
    // explicit reset means the user is done with this batch, not switching
    // tabs mid-flight.
    clearUploadBatch();
    // Refresh remaining_dataset_quota so "Upload More" after an import reflects
    // the new dataset count instead of the cached pre-import value (Codex P2 on
    // PR #274). invalidate matches the user-scoped key by prefix.
    queryClient.invalidateQueries({ queryKey: queryKeys.ingest.uploadConfig });
  }, [setPhase, queryClient]);

  // fix(#1712): re-attach to a batch that was uploading (or already done
  // previewing) while this form was unmounted — a tab switch away and back.
  // Without this, the job ids the server returned to a dead component would
  // be unreachable, plus their staged bytes, until the stale-pending sweep
  // collected them. Mount-only: a later session start is driven by drops,
  // not by this effect re-running.
  useEffect(() => {
    const adopted = peekUploadBatch();
    if (!adopted || adopted.length === 0) return;
    setEntries(
      adopted.map((se) => {
        let error: string | null = null;
        if (se.status === 'upload-failed') {
          const quota = quotaMessage(se.error);
          if (quota) {
            setQuotaNotice(quota);
            error = t('upload.quotaShort');
          } else {
            error = buildErrorDisplay(se.error, 'upload.uploadFailed', t);
          }
        }
        return {
          id: se.id,
          file: null,
          fileName: se.fileName,
          status: se.status,
          jobId: se.jobId,
          previewData: se.previewData,
          error,
          progress: se.progress,
          submittedTitle: null,
          submittedVisibility: null,
          submittedKind: null,
        };
      }),
    );
    setPhase(
      adopted.every((se) => se.status === 'preview' || se.status === 'upload-failed')
        ? 'reviewing'
        : 'uploading',
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // fix(#1712): the session, not the XHR, owns progress and settlement — a
  // mounted form subscribes and mirrors instead of holding either in its
  // own closures. Runs for the component's whole lifetime, not just while a
  // batch is active, so it also picks up a batch this mount ITSELF started.
  useEffect(() => {
    return subscribeUploadBatch(() => {
      setEntries((prev) =>
        prev.map((e) => {
          const se = getUploadSessionEntry(e.id);
          if (!se) return e;
          if (
            se.status === e.status &&
            se.jobId === e.jobId &&
            se.previewData === e.previewData &&
            se.progress === e.progress
          ) {
            return e;
          }
          let displayError: string | null = null;
          if (se.status === 'upload-failed') {
            const quota = quotaMessage(se.error);
            if (quota) {
              setQuotaNotice(quota);
              displayError = t('upload.quotaShort');
            } else {
              displayError = buildErrorDisplay(se.error, 'upload.uploadFailed', t);
            }
          }
          return {
            ...e,
            status: se.status,
            jobId: se.jobId,
            previewData: se.previewData,
            progress: se.progress,
            error: displayError,
            file: se.status === 'uploading' ? e.file : null,
          };
        }),
      );
    });
  }, [t]);

  // IMPORT-03 (Phase 1054): phase transitions were inlined inside setEntries
  // updaters, which violates React 19's "no setState during another
  // component's render" rule and fires the verbatim warning the audit
  // captured. Moving them into a single effect dep'd on `entries` runs the
  // transition AFTER React commits the entries change.
  useEffect(() => {
    // fix(#1712): the uploading -> reviewing edge used to be driven by
    // `processFiles`'s own `await Promise.allSettled(...)`. That still works
    // while the form stays mounted, but a batch adopted (or continuing) via
    // the session above settles through notifications instead, with nothing
    // local left awaiting it — so this effect drives the same edge from
    // `entries` the way the other two already do.
    if (phase === 'uploading' && entries.length > 0) {
      const allTerminal = entries.every(
        (e) => e.status === 'preview' || e.status === 'upload-failed',
      );
      if (allTerminal) setPhase('reviewing');
      return;
    }
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

  const processFiles = useCallback(async (files: File[]) => {
    if (phase !== 'idle') return;
    setQuotaNotice(null);

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
      progress: 0,
      submittedTitle: null,
      submittedVisibility: null,
      submittedKind: null,
    }));

    setEntries(newEntries);
    setPhase('uploading');

    // fix(#1712): the upload+preview work for each entry now runs at module
    // scope (`upload-session.ts`), not in this closure — so it keeps running,
    // and its outcome stays reachable, if this form unmounts before it
    // settles. The subscription effect above mirrors updates back into
    // `entries` (and the one just below flips the phase once every entry in
    // the batch is terminal), so nothing here awaits the batch directly.
    const presigned = !!uploadConfig?.presigned_uploads;
    for (const entry of newEntries) {
      startUploadEntry(entry.id, entry.file!, presigned);
    }
  }, [phase, entries, t, uploadConfig?.presigned_uploads, setPhase]);

  // Queue drops that land mid-fetch instead of processing them against an
  // unresolved/stale quota; merge (not replace) so a second drop in the same
  // window can't swallow the first (PR #274 follow-up).
  const handleFilesAccepted = (files: File[]) => {
    if (phase !== 'idle') return;
    if (configFetching) {
      setPendingFiles((prev) => (prev ? [...prev, ...files] : files));
      return;
    }
    void processFiles(files);
  };

  // Flush queued drops once the quota query settles, re-applying every gate
  // the dropzone validated against nothing (or stale values) during the fetch
  // window: extension and per-file size are re-checked per file with the same
  // rejection toast react-dropzone shows (Codex P2 round 2 on PR #432), then
  // the batch cap with the fresh quota. Over-cap batches are trimmed to the
  // cap and the overflow rejected per file, matching react-dropzone v19's
  // maxFiles behavior (v19 accepts files up to the limit instead of
  // rejecting the batch wholesale).
  useEffect(() => {
    if (configFetching || !pendingFiles || phase !== 'idle') return;
    setPendingFiles(null);
    const files = pendingFiles.filter((f) => {
      if (
        allowedExtensions?.length &&
        !allowedExtensions.some((ext) => f.name.toLowerCase().endsWith(ext.toLowerCase()))
      ) {
        toast.error(t('dropzone.fileRejected', { filename: f.name, reason: t('dropzone.unsupportedType') }));
        return false;
      }
      if (maxSizeMb != null && f.size > maxSizeMb * 1024 * 1024) {
        toast.error(t('dropzone.fileRejected', { filename: f.name, reason: t('dropzone.sizeLimitDynamic', { size: maxSizeMb }) }));
        return false;
      }
      return true;
    });
    if (files.length === 0) return;
    const limit = effectiveBatchLimit(uploadConfig?.remaining_dataset_quota ?? null);
    for (const f of files.slice(limit)) {
      toast.error(t('dropzone.fileRejected', { filename: f.name, reason: t('dropzone.batchLimit', { max: limit }) }));
    }
    void processFiles(files.slice(0, limit));
    // processFiles is recreated per render; the pendingFiles/configFetching
    // guards make re-runs no-ops, so listing it is safe.
  }, [configFetching, pendingFiles, phase, uploadConfig?.remaining_dataset_quota, allowedExtensions, maxSizeMb, processFiles, t]);

  const handleCommitSingle = async (
    entryId: string,
    request: CommitImportRequest,
  ) => {
    const entry = entries.find((e) => e.id === entryId);
    if (!entry?.jobId) return;

    updateEntry(entryId, { status: 'committing' });
    // fix(#1712): a commit is being issued for this entry — the batch
    // session's job is done (see its module docstring). Holding it past
    // this point would let a later remount re-preview an already-processed
    // job, which the API refuses with 400.
    removeUploadSessionEntry(entryId);

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
      const quota = quotaMessage(err);
      if (quota) setQuotaNotice(quota);
      updateEntry(entryId, {
        status: 'commit-failed',
        error: quota ? t('upload.quotaShort') : buildErrorDisplay(err, 'upload.commitFailed', t),
      });
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
    // fix(#1712): see handleCommitSingle — every entry being committed
    // leaves the batch session now, not once its commit settles.
    for (const entry of reviewable) {
      removeUploadSessionEntry(entry.id);
    }

    await Promise.allSettled(
      reviewable.map(async (entry) => {
        try {
          const name =
            stripExtension(
              entry.previewData?.source_filename ?? entry.fileName,
            ) || 'Untitled';
          // fix(#1685): multi-layer files must carry the layer selected in the
          // review picker into the default-import path too — omitting it left
          // the backend defaulting to the first layer regardless of what the
          // user picked, silently importing a different layer than shown.
          const fp = entry.previewData && isFilePreview(entry.previewData) ? entry.previewData : null;
          const layerName = fp?.layers && fp.layers.length > 1 ? fp.layer_name : undefined;
          await commitImport(entry.jobId!, layerName ? { title: name, layer_name: layerName } : { title: name });
          updateEntry(entry.id, {
            status: 'tracking',
            submittedTitle: name,
            submittedVisibility: 'private',
            submittedKind: inferImportedKind(entry),
          });
        } catch (err) {
          const quota = quotaMessage(err);
          if (quota) setQuotaNotice(quota);
          updateEntry(entry.id, {
            status: 'commit-failed',
            error: quota ? t('upload.quotaShort') : buildErrorDisplay(err, 'upload.bulkCommitFailed', t),
          });
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
    // fix(#1778): mirrors UrlImportForm.tsx's handleLayerChange guard
    // (#1708 r24): re-previewing mid-commit drove the entry back to
    // 'preview' unconditionally, which re-enabled the commit button
    // against a request already in flight for the same job.
    if (entry.status === 'committing' || entry.status === 'tracking') return;

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
    // fix(#1712): see handleCommitSingle — the fan-out commit is a commit.
    removeUploadSessionEntry(entryId);

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
    // fix(#1712): the user dismissed this row — nothing left to adopt it.
    removeUploadSessionEntry(entryId);
    // Phase transition (reviewing → idle when empty) is handled by the
    // useEffect dep'd on `entries` (IMPORT-03).
  };

  const quotaBanner = quotaNotice ? (
    <div className="flex items-start gap-2.5 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
      <AlertCircle className="mt-0.5 size-4 shrink-0" />
      <div>
        <p className="font-medium">{t('upload.quotaBannerTitle')}</p>
        <p className="mt-0.5 text-destructive">{quotaNotice}</p>
        <p className="mt-0.5 text-xs text-destructive">{t('upload.quotaBannerHint')}</p>
      </div>
    </div>
  ) : null;

  if (phase === 'uploading') {
    return (
      <div className="space-y-4">
        {quotaBanner}
        <BulkUploadProgress entries={entries} />
      </div>
    );
  }

  if (phase === 'reviewing') {
    return (
      <div className="space-y-4">
        {quotaBanner}
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

  // idle. The dropzone stays enabled while the quota query fetches — disabling
  // it made react-dropzone silently swallow drops (PR #274 follow-up). Drops in
  // that window queue in pendingFiles and flush with the fresh quota, so we
  // still never *act* on an unresolved/stale quota (Codex P2 on PR #274). Once
  // a fetch settles, success carries the live remaining quota; an error
  // degrades to permissive — consistent with allowedExtensions/maxSizeMb.
  // While fetching, every config-derived gate is permissive (quota null,
  // extensions/size undefined): react-dropzone enforces accept/maxSize/maxFiles
  // at drop time, so cached stale values would reject files the fresh config
  // allows before they could queue — the flush validates all three against the
  // settled config instead (Codex P2 rounds 1-3 on PR #432).
  return (
    <FileDropzone
      onFilesAccepted={handleFilesAccepted}
      allowedExtensions={configFetching ? undefined : allowedExtensions}
      maxSizeMb={configFetching ? undefined : maxSizeMb}
      remainingQuota={configFetching ? null : (uploadConfig?.remaining_dataset_quota ?? null)}
    />
  );
}
