import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useQueryClient } from '@tanstack/react-query';
import {
  startUploadEntry,
  startLayerPreview,
  commitUploadEntry,
  commitUploadEntries,
  commitUploadFanOut,
  dismissUploadFanOutResults,
  subscribeUploadBatch,
  peekUploadBatch,
  removeUploadSessionEntry,
  clearUploadBatch,
  releaseUploadBatch,
  queuePendingUploadFiles,
  peekPendingUploadFiles,
  peekPendingUploadKind,
  clearPendingUploadFiles,
  type UploadBatchSnapshot,
  type UploadSessionEntry,
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
import { allowedTilesetExtensions, inferImportedKind, isFilePreview, stripExtension } from './utils';
import { UploadKindChoice } from './UploadKindChoice';
import { BulkReviewList } from './BulkReviewList';
import { BulkTrackingList } from './BulkTrackingList';
import type { FileEntry, BatchPhase, CommitImportRequest, UploadKind, DataKind } from '@/types/api';
import { ApiError } from '@/api/client';
import { randomId } from '@/lib/random-id';

// A .3tz holds only a tileset and a .laz only a point cloud, so the files
// choice never takes either.
const KIND_ONLY_EXTENSIONS = new Set(['.3tz', '.laz']);

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

/**
 * Derive the display error (and, for a quota rejection, the batch-level
 * banner text) for a session entry. A failed layer re-preview leaves the
 * entry in `preview` with an error and is never a quota rejection.
 */
function deriveSessionEntryError(
  se: UploadSessionEntry,
  t: TFunction<'import'>,
  onQuota: (msg: string) => void,
): string | null {
  if (se.status === 'upload-failed' || (se.status === 'commit-failed' && !se.fanOut)) {
    const quota = quotaMessage(se.error);
    if (quota) {
      onQuota(quota);
      return t('upload.quotaShort');
    }
    const fallbackKey =
      se.status === 'upload-failed'
        ? 'upload.uploadFailed'
        : se.commitVia === 'all'
          ? 'upload.bulkCommitFailed'
          : 'upload.commitFailed';
    return buildErrorDisplay(se.error, fallbackKey, t);
  }
  if (se.status === 'commit-failed' && se.fanOut) {
    const succeeded = se.fanOut.filter((r) => r.status === 'fulfilled').length;
    return succeeded === 0
      ? t('upload.multiLayerAllFailed')
      : t('upload.multiLayerPartialFailed', { succeeded, failed: se.fanOut.length - succeeded });
  }
  if (se.status === 'preview' && se.error != null) {
    return se.error instanceof ApiError ? se.error.message : t('upload.uploadFailed');
  }
  return null;
}

function toFileEntry(
  se: UploadSessionEntry,
  t: TFunction<'import'>,
  onQuota: (msg: string) => void,
): FileEntry {
  return {
    id: se.id,
    file: null,
    fileName: se.fileName,
    status: se.status === 'committed' ? 'tracking' : se.status,
    jobId: se.jobId,
    previewData: se.previewData,
    uploadKind: se.kind,
    error: deriveSessionEntryError(se, t, onQuota),
    progress: se.progress,
    submittedTitle: se.submitted?.title ?? null,
    submittedVisibility: se.submitted?.visibility ?? null,
    submittedKind: se.submitted?.kind ?? null,
    commitRequest: se.request,
  };
}

// GPKG-03 Phase 1058: per-layer result shape for the fan-out results modal.
type FanOutResult = {
  layerName: string;
  status: 'fulfilled' | 'rejected';
  error?: string;
};

function isUploadInFlight(e: { status: string }): boolean {
  return e.status === 'uploading' || e.status === 'previewing';
}

interface UploadFormProps {
  onPhaseChange?: (phase: BatchPhase) => void;
  onOutcomeChange?: (outcome: 'complete' | 'partial' | null, kinds: DataKind[]) => void;
}

export function UploadForm({ onPhaseChange, onOutcomeChange }: UploadFormProps) {
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
  // A refused commit that can be retried keeps the batch in review, even
  // alongside rows that are already tracked.
  const [awaitingRetry, setAwaitingRetry] = useState(false);
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
  const [chosenKind, setChosenKind] = useState<UploadKind | null>(null);

  const configExtensions = useMemo(
    () => uploadConfig?.allowed_extensions?.split(',').map(e => e.trim()).filter(Boolean),
    [uploadConfig?.allowed_extensions],
  );
  const tilesetExtensions = useMemo(() => allowedTilesetExtensions(configExtensions), [configExtensions]);
  const tilesetAvailable = tilesetExtensions.length > 0;
  const pointcloudAvailable = configExtensions?.some((ext) => ext.toLowerCase() === '.laz') ?? true;
  const uploadKind = (chosenKind === 'tiles3d' && !tilesetAvailable) ||
    (chosenKind === 'pointcloud' && !pointcloudAvailable) ? null : chosenKind;
  const allowedExtensions = useMemo(
    () =>
      uploadKind === 'tiles3d'
        ? tilesetExtensions
        : uploadKind === 'pointcloud'
          ? ['.laz']
        : configExtensions?.filter((ext) => !KIND_ONLY_EXTENSIONS.has(ext.toLowerCase())),
    [uploadKind, tilesetExtensions, configExtensions],
  );
  const maxSizeMb = uploadConfig ? Math.round(uploadConfig.max_file_size_bytes / (1024 * 1024)) : undefined;

  const reset = useCallback(() => {
    setPhase('idle');
    setEntries([]);
    setAutoOpenVrt(false);
    setAwaitingRetry(false);
    setQuotaNotice(null);
    setPendingFiles(null);
    // An explicit reset means the user is done with this batch; a commit
    // still in flight for it settles into nothing.
    clearUploadBatch();
    // fix(#1832): same reasoning for the config-fetch queue.
    clearPendingUploadFiles();
    // Refresh remaining_dataset_quota so "Upload More" after an import reflects
    // the new dataset count instead of the cached pre-import value (Codex P2 on
    // PR #274). invalidate matches the user-scoped key by prefix.
    queryClient.invalidateQueries({ queryKey: queryKeys.ingest.uploadConfig });
  }, [setPhase, queryClient]);

  const showBatch = useCallback((batch: UploadBatchSnapshot) => {
    setEntries(batch.entries.map((se) => toFileEntry(se, t, setQuotaNotice)));
    setFanOutResults(
      batch.fanOutResults && {
        entryId: batch.fanOutResults.entryId,
        results: batch.fanOutResults.results.map((r) => ({
          layerName: r.layerName,
          status: r.status,
          error: r.error ?? (r.status === 'rejected' ? t('upload.commitFailed') : undefined),
        })),
      },
    );
    if (batch.autoOpenVrt) setAutoOpenVrt(true);
    setAwaitingRetry(batch.awaitingRetry);
  }, [t]);

  // Adopt a batch that kept uploading, previewing or committing while this
  // form was unmounted (a tab switch away and back). Mount-only: later
  // changes arrive through the subscription below.
  useEffect(() => {
    const adopted = peekUploadBatch();
    if (adopted) {
      showBatch(adopted);
      setPhase(adopted.entries.some(isUploadInFlight) ? 'uploading' : 'reviewing');
    }
    // fix(#1832): rehydrate a drop that was still waiting on the
    // upload-config query when this form unmounted — see
    // `queuePendingUploadFiles`'s doc comment in upload-session.ts for the
    // race this closes. The flush effect below re-runs on this same mount
    // once `pendingFiles` becomes non-null here, so no separate flush call
    // is needed at this site.
    const queued = peekPendingUploadFiles();
    if (queued && queued.length > 0) {
      setPendingFiles(queued);
      setChosenKind(peekPendingUploadKind());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The session owns progress and settlement; the form mirrors it for its
  // whole lifetime, including a batch this mount started. Once the session
  // releases or clears the batch, the form keeps what it last showed.
  useEffect(() => {
    return subscribeUploadBatch(() => {
      const batch = peekUploadBatch();
      if (batch) showBatch(batch);
    });
  }, [showBatch]);

  // IMPORT-03 (Phase 1054): phase transitions were inlined inside setEntries
  // updaters, which violates React 19's "no setState during another
  // component's render" rule and fires the verbatim warning the audit
  // captured. Moving them into a single effect dep'd on `entries` runs the
  // transition AFTER React commits the entries change.
  useEffect(() => {
    if (phase === 'uploading' && entries.length > 0) {
      if (!entries.some(isUploadInFlight)) setPhase('reviewing');
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
      // fix(#2034): a partial-failure fan-out modal (real 'rejected' results) holds the reviewing phase open — the queued layers it also tracked would otherwise hide it before it's read. A full-success modal never blocks, matching prior behavior.
      const fanOutHasFailure = fanOutResults?.results.some((r) => r.status === 'rejected') ?? false;
      if (allTerminal && hasTracking && !fanOutHasFailure && !awaitingRetry) {
        setPhase('tracking');
      }
    }
  }, [entries, phase, setPhase, fanOutResults, awaitingRetry]);

  // Once the tracking view is on screen the batch has been shown, so the
  // session lets it go (see `releaseUploadBatch`).
  useEffect(() => {
    if (phase === 'tracking') releaseUploadBatch();
  }, [phase]);

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
      id: randomId(),
      file,
      fileName: file.name,
      status: 'uploading' as const,
      jobId: null,
      previewData: null,
      uploadKind,
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
      startUploadEntry(entry.id, entry.file!, presigned, uploadKind);
    }
  }, [phase, entries, t, uploadConfig?.presigned_uploads, setPhase, uploadKind]);

  // Queue drops that land mid-fetch instead of processing them against an
  // unresolved/stale quota; merge (not replace) so a second drop in the same
  // window can't swallow the first (PR #274 follow-up).
  //
  // fix(#1832): the queue itself is now module-scoped (`upload-session.ts`),
  // not just this component's state — a tab switch that unmounts the form
  // before `configFetching` settles used to discard the drop outright, since
  // nothing had reached `startUploadEntry`'s session yet for a remount to
  // adopt. `setPendingFiles` still runs too, so this mount's own render
  // reflects the queue immediately; the module copy is what a remount reads.
  const handleFilesAccepted = (files: File[]) => {
    if (phase !== 'idle') return;
    if (configFetching) {
      setPendingFiles(queuePendingUploadFiles(files, uploadKind));
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
    // fix(#1832): release the module-scoped copy in step with the local
    // one — this effect is the only consumer, so nothing else needs it
    // once the flush it is about to do below has claimed the files.
    clearPendingUploadFiles();
    const files = pendingFiles.filter((f) => {
      if (
        allowedExtensions &&
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
    if (!entry) return;
    // The session refuses a second commit for the same entry, so a double
    // click that lands before the 'committing' re-render issues only one.
    const committed = await commitUploadEntry(entryId, request, {
      title: request.title,
      visibility: request.visibility ?? 'private',
      kind: inferImportedKind(entry, request),
    });
    if (committed) toast.success(t('upload.importStarted'));
  };

  const commitAll = async (asVrt: boolean) => {
    const reviewable = entries.filter(
      (e) => e.status === 'preview' && e.jobId,
    );
    if (reviewable.length === 0) return;

    await commitUploadEntries(
      reviewable.map((entry) => {
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
        return {
          id: entry.id,
          request: layerName ? { title: name, layer_name: layerName } : { title: name },
          submission: { title: name, visibility: 'private', kind: inferImportedKind(entry) },
        };
      }),
      { autoOpenVrt: asVrt },
    );
  };

  const handleCommitAll = () => commitAll(false);
  const handleCommitAllAsVrt = () => commitAll(true);

  // The session owns the re-preview, so its result survives an unmount, and
  // it refuses an entry whose commit was already issued.
  const handleSheetChange = (entryId: string, layerName: string) => {
    const entry = entries.find((e) => e.id === entryId);
    if (!entry?.jobId) return;
    startLayerPreview(entryId, entry.jobId, layerName);
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

    const fileBase = stripExtension(entry.previewData.source_filename ?? entry.fileName) || 'Untitled';
    // Each queued layer is tracked by its own job, since the parent settles
    // 'fanned_out' with no dataset. Every layer takes the previewed layer's
    // kind: LayerPreview carries no per-layer geometry type.
    const previewedLayerKind = entry.previewData.geometry_type ? ('vector' as const) : ('table' as const);
    const results = await commitUploadFanOut(
      entryId,
      layers.map((layer) => ({
        layer_name: layer.name,
        title: `${fileBase}: ${layer.name}`,
      })),
      previewedLayerKind,
    );
    if (results?.every((r) => r.status === 'fulfilled')) {
      toast.success(t('upload.multiLayerSuccess', { count: results.length }));
    }
  };

  const closeFanOutResults = () => {
    setFanOutResults(null);
    dismissUploadFanOutResults();
  };

  const removeEntry = (entryId: string) => {
    setEntries((prev) => prev.filter((e) => e.id !== entryId));
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
              if (!open) closeFanOutResults();
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
                    onClick={closeFanOutResults}
                  >
                    {t('upload.multiLayerRetryClose')}
                  </Button>
                )}
                <Button onClick={closeFanOutResults}>{t('common:close')}</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}
      </div>
    );
  }

  if (phase === 'tracking') {
    return <BulkTrackingList entries={entries} onReset={reset} autoOpenVrt={autoOpenVrt} onOutcomeChange={onOutcomeChange} />;
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
    <div className="space-y-4">
      {/* Locked while a drop waits on the config, so it uploads as the kind it was dropped as. */}
      <UploadKindChoice
        value={uploadKind}
        onChange={setChosenKind}
        disabled={pendingFiles !== null}
        lockedHint={t('upload.kindLocked')}
        tilesetAvailable={tilesetAvailable}
        pointcloudAvailable={pointcloudAvailable}
      />
      <FileDropzone
        onFilesAccepted={handleFilesAccepted}
        allowedExtensions={configFetching ? undefined : allowedExtensions}
        maxSizeMb={configFetching ? undefined : maxSizeMb}
        remainingQuota={configFetching ? null : (uploadConfig?.remaining_dataset_quota ?? null)}
        tileset={uploadKind === 'tiles3d'}
        pointcloud={uploadKind === 'pointcloud'}
      />
    </div>
  );
}
