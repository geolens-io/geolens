import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Link as LinkIcon } from 'lucide-react';
import { ApiError } from '@/api/client';
import { previewFile, commitImport, getJobStatus, cancelJob } from '@/api/ingest';
import {
  clearUrlImport,
  attachUrlImportCommit,
  peekUrlImport,
  startUrlImport,
  type UrlImportSession,
} from '@/api/url-import-session';
import { useJobStatus, useUploadConfig } from '@/components/import/hooks/use-ingest';
import { describeFailureReason } from '@/lib/failure-reason';
import type {
  CommitImportRequest,
  UrlUploadKind,
} from '@/types/api';
import { allowedTilesetExtensions, isFilePreview, isRasterPreview, isTilesetPreview } from './utils';
import { ImportPreview } from './ImportPreview';
import { ImportMetadataForm } from './ImportMetadataForm';
import { UploadKindChoice } from './UploadKindChoice';
import { JobProgress } from './JobProgress';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

type UrlStep =
  | 'idle'
  | 'fetching'
  | 'downloading'
  | 'previewing'
  | 'resuming'
  | 'review'
  | 'committing'
  | 'tracking';

/**
 * The job statuses that are still moving.
 *
 * `JobStatusResponse.status` is pending | running | complete | failed |
 * cancelled | fanned_out. Reset has to be reachable from EVERY terminal state,
 * so the predicate names what is IN FLIGHT and treats everything else as
 * terminal. It deliberately does NOT reuse `use-ingest`'s
 * `isTerminalJobStatus`, which enumerates the terminal set and so treats an
 * unknown status as still running: right for a poll interval, wrong for an
 * escape hatch. An unknown status here fails toward offering the escape hatch.
 * A spurious "Import another" on a live job costs this tab its tracking of
 * that job (reset clears the session and the job id) while the job itself
 * runs on; a job with no way out strands the tab for the rest of the SPA
 * session.
 */
const IN_FLIGHT_JOB_STATUSES: ReadonlySet<string> = new Set(['pending', 'running']);

function isTerminalJobStatus(status: string | undefined): boolean {
  return status !== undefined && !IN_FLIGHT_JOB_STATUSES.has(status);
}

/**
 * The job itself is gone: 404 (not found / no longer visible) or 410
 * (expired/removed). Distinct from `isTerminalJobStatus`, which reads a
 * fetched job's `status` field; this reads the HTTP status of a call that
 * referenced the job.
 */
function isGoneError(err: unknown): boolean {
  return err instanceof ApiError && [404, 410].includes(err.status);
}

/**
 * Import a dataset straight from an HTTP(S) file URL.
 *
 * The URL variant of the Upload tab: the backend fetches the file
 * server-side (SSRF-validated, size-capped) into staging, and from there the
 * flow is identical to a direct upload — preview, review metadata, commit,
 * track. Single-file, single-dataset; multi-layer containers get a layer
 * picker before commit.
 */
export function UrlImportForm({ initialUrl = '' }: { initialUrl?: string }) {
  const { t } = useTranslation('import');
  const [step, setStep] = useState<UrlStep>('idle');
  const [url, setUrl] = useState(initialUrl);
  const [filename, setFilename] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<Awaited<ReturnType<typeof previewFile>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Survives a resume, where previewData does not.
  const [isRaster, setIsRaster] = useState(false);
  // Disables "Cancel and start over" during the cancel call, so a double-click
  // cannot fire two cancels.
  const [isCancelling, setIsCancelling] = useState(false);
  const [chosenKind, setChosenKind] = useState<UrlUploadKind | null>(null);
  const { data: uploadConfig } = useUploadConfig();
  const tilesetAvailable =
    allowedTilesetExtensions(uploadConfig?.allowed_extensions?.split(',').map((e) => e.trim())).length > 0;
  const kind = tilesetAvailable ? chosenKind : null;
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // The window in which a request has been issued that nothing can recall.
  // Every control below that would mutate `step`, the module session, or an
  // in-flight request is disabled on this AND refuses on it in its handler: a
  // disabled control is a fact about one rendered tree, the handler guard is
  // the invariant.
  //
  // The set is read off the RENDERED CONTROLS: `committing` is the only
  // in-flight state that renders a control, because `fetching`, `previewing`
  // and `resuming` render the spinner branch, which has none. `resuming` is
  // named anyway (the same uncancellable commit, adopted by a later mount) so
  // the predicate stays true if that branch grows a control.
  const commitInFlight = step === 'committing' || step === 'resuming';

  // Reset is available from every TERMINAL state and refuses only while an
  // uncancellable operation is in flight: clearing the session mid-commit
  // orphans a commit that then succeeds untracked.
  const reset = () => {
    if (commitInFlight) return;
    clearUrlImport();
    setStep('idle');
    setUrl('');
    setFilename('');
    setJobId(null);
    setPreviewData(null);
    setError(null);
  };

  // A preview failure does not mean the staged job is gone: a GDAL timeout or
  // transient network blip leaves it `pending`. Clearing the session there
  // would throw away the only client-side copy of its id, and resubmitting the
  // SAME url would re-download server-side (startUrlImport can't recognize the
  // stale key) and orphan the original staged job for the sweeper. Auto-clear
  // only when the job is confirmed gone or terminal: 404/410 from the failed
  // call, or a live status check that comes back terminal (failed, cancelled,
  // complete or fanned_out, e.g. an admin cancel or the stale-pending sweep).
  // Anything else keeps BOTH the session and the `jobId` state, so the idle
  // render below can offer an explicit retry or cancel, and a same-url
  // resubmit still works (`startUrlImport` reuses the fulfilled same-key
  // session and only the preview re-runs).
  const settlePreviewFailure = useCallback(async (id: string, err: unknown) => {
    let terminal = isGoneError(err);
    if (!terminal) {
      try {
        const status = await getJobStatus(id);
        terminal = isTerminalJobStatus(status.status);
      } catch (statusErr) {
        // Fail toward KEEPING the session: a status-check failure is not
        // evidence the job is gone (a 5xx, a network blip), except a 404/410
        // on the status read itself, which is.
        terminal = isGoneError(statusErr);
      }
    }
    if (!mountedRef.current) return;
    setStep('idle');
    if (terminal) {
      setJobId(null);
      clearUrlImport();
    }
  }, []);

  // The session is owned by the module, so a tab switch mid-import cannot
  // strand the job. Everything below only decides what THIS mount displays.
  const runSession = useCallback(
    async (session: UrlImportSession) => {
      setStep('fetching');
      setError(null);

      let fetchedJobId: string;
      try {
        const res = await session.promise;
        fetchedJobId = res.job_id;
      } catch (err) {
        // Only touch state if this mount is still the live one; the session
        // already recorded the outcome for whoever mounts next.
        if (!mountedRef.current) return;
        const msg = err instanceof ApiError ? err.message : t('urlImport.fetchFailed');
        setError(msg);
        setStep('idle');
        toast.error(msg);
        clearUrlImport();
        return;
      }
      if (!mountedRef.current) return;
      setJobId(fetchedJobId);
      // The POST only queues the download, so the file is not staged yet. The
      // job poll below decides when it is previewable; a resumed session lands
      // here too and its poll answers immediately.
      setStep('downloading');
    },
    [t],
  );

  // Re-run the preview for the SAME job id (no re-download, no new staged
  // file), with the same terminal check as the initial failure so a second
  // miss on a dead job still clears.
  const runPreview = useCallback(
    async (id: string) => {
      setStep('previewing');
      setError(null);
      try {
        const preview = await previewFile(id);
        if (!mountedRef.current) return;
        setPreviewData(preview);
        setStep('review');
      } catch (err) {
        if (!mountedRef.current) return;
        const msg = err instanceof ApiError ? err.message : t('urlImport.previewFailed');
        setError(msg);
        toast.error(msg);
        await settlePreviewFailure(id, err);
      }
    },
    [t, settlePreviewFailure],
  );

  const handleRetryPreview = async () => {
    if (!jobId) return;
    await runPreview(jobId);
  };

  // The explicit escape hatch from a kept preview-failed session: cancel the
  // staged job through the cancel endpoint, then release the session and reset
  // to a fresh idle form.
  //
  // A failed (or ambiguous) cancel does NOT mean the job is gone: resetting on
  // any outcome would clear the only client-side copy of a job that may still
  // be pending server-side with its staged file. Reset only when the job is
  // CONFIRMED gone: the cancel call's own 404/410, or a follow-up status check
  // that comes back gone or terminal. Any other failure (500, network blip)
  // keeps the recovery state (session, job id, both actions) and shows the
  // error instead of the job silently vanishing from the tab.
  const handleCancelAndStartOver = async () => {
    if (!jobId) return;
    setIsCancelling(true);
    try {
      await cancelJob(jobId);
      if (!mountedRef.current) return;
      reset();
      return;
    } catch (err) {
      if (!mountedRef.current) return;
      let gone = isGoneError(err);
      if (!gone) {
        try {
          const status = await getJobStatus(jobId);
          gone = isTerminalJobStatus(status.status);
        } catch (statusErr) {
          gone = isGoneError(statusErr);
        }
      }
      if (!mountedRef.current) return;
      if (gone) {
        reset();
        return;
      }
      const msg = err instanceof ApiError ? err.message : t('urlImport.cancelFailed');
      setError(msg);
      toast.error(msg);
    } finally {
      if (mountedRef.current) setIsCancelling(false);
    }
  };

  // Shares JobProgress's query key, so this is the same cached poll rather
  // than a second one. It decides which controls to offer while tracking,
  // and when the server-side download has produced a previewable job.
  const { data: trackedJob, isError: jobPollFailing } = useJobStatus(
    step === 'tracking' || step === 'downloading' ? jobId : null,
  );

  // The download's only observer. `pending` means the bytes are
  // staged; any terminal status means the worker settled it and there is
  // nothing to preview, so the tab returns to a usable idle form.
  useEffect(() => {
    if (step !== 'downloading' || !jobId || !trackedJob) return;
    if (trackedJob.status === 'pending') {
      void runPreview(jobId);
      return;
    }
    if (!isTerminalJobStatus(trackedJob.status)) return;
    // A cancel is the user's own action in this view, so returning to the
    // form IS the feedback; an error toast would report their own click back
    // to them. Every other terminal status is a failure the form must explain.
    if (trackedJob.status !== 'cancelled') {
      const msg = trackedJob.error_message
        ? describeFailureReason(
            trackedJob.error_message,
            t('common:errors.internalFailureReason'),
            trackedJob.error_code,
          )
        : t('urlImport.downloadFailed');
      setError(msg);
      toast.error(msg);
    }
    setStep('idle');
    setJobId(null);
    clearUrlImport();
  }, [step, jobId, trackedJob, runPreview, t]);

  // SUBSCRIBE to the commit rather than sampling a flag: a boolean set before
  // the await let a mount arriving mid-commit read "committed" and enter
  // tracking, and a commit that then failed flipped the flag back at module
  // scope while this component kept polling a job that was still pending and
  // previewable. Awaiting the promise removes the window: whenever the outcome
  // lands, the mounted form gets the real one.
  const runResumedCommit = useCallback(
    async (commitPromise: Promise<unknown>, committingJobId: string) => {
      setJobId(committingJobId);
      setStep('resuming');
      setError(null);
      try {
        await commitPromise;
        if (!mountedRef.current) return;
        setStep('tracking');
      } catch (err) {
        if (!mountedRef.current) return;
        // The commit failed, so the job is still `pending` and genuinely
        // previewable: rebuild review so the user can retry rather than
        // stranding them on a tracking view for a job nothing will finish.
        const msg =
          err instanceof ApiError ? err.message : t('urlImport.commitFailed');
        setError(msg);
        try {
          const preview = await previewFile(committingJobId);
          if (!mountedRef.current) return;
          setPreviewData(preview);
          setStep('review');
        } catch {
          if (!mountedRef.current) return;
          setStep('idle');
        }
      }
    },
    [t],
  );

  // Re-attach to an import that was running (or finished) while this form
  // was unmounted. Without this the job id the server returned to a dead
  // component would be unreachable until the stale-pending sweep, with its
  // staged bytes held the whole time.
  useEffect(() => {
    const session = peekUrlImport();
    if (!session) return;
    setChosenKind(session.kind);
    if (session.commit && session.jobId) {
      setIsRaster(session.isRaster);
      void runResumedCommit(session.commit, session.jobId);
      return;
    }
    void runSession(session);
    // Deliberately mount-only: re-running on every `runSession` identity
    // change would re-enter a session already being displayed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFetch = async (e: React.FormEvent) => {
    e.preventDefault();
    // A retained job id (transient preview failure) means the url/filename
    // fields are still visible next to the recovery actions; editing them and
    // submitting would start a SECOND session, replacing the module-level
    // `current` and orphaning the retained job's staged file. Retry preview /
    // Cancel and start over are the only way forward while a job is retained;
    // Cancel and start over clears jobId and re-enables submission.
    if (jobId) return;
    const trimmed = url.trim();
    if (!trimmed) return;
    await runSession(startUrlImport(trimmed, filename.trim() || undefined, kind));
  };

  const handleLayerChange = async (layerName: string) => {
    // Re-previewing mid-commit would replace `committing` with `previewing` and
    // then UNCONDITIONALLY `review`, re-enabling Start Over and the commit
    // button against a request that cannot be recalled: orphaning the queued
    // job, or offering a second commit for one already started. Same cell of
    // the lifecycle table as reset; this guards the event axis, not the state axis.
    if (!jobId || commitInFlight) return;
    setStep('previewing');
    setError(null);
    try {
      const preview = await previewFile(jobId, layerName);
      setPreviewData(preview);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t('urlImport.previewFailed');
      setError(msg);
      toast.error(msg);
    }
    setStep('review');
  };

  const handleCommit = async (metadata: CommitImportRequest) => {
    // The commit control is disabled during its own commit (ImportMetadataForm
    // gates its submit on `isCommitting`), but the handler guards too, as the
    // layer picker and reset do: the UI half only holds for the tree that
    // rendered it.
    if (!jobId || !previewData || commitInFlight) return;

    setStep('committing');
    setError(null);

    const fp = isFilePreview(previewData) ? previewData : null;
    const layerName =
      fp && (fp.layers?.length ?? 0) > 1 ? fp.layer_name : undefined;

    try {
      // Registered BEFORE the await, so an unmount mid-commit still leaves a
      // session that resumes into tracking. The `committed` flag stops a
      // remount from re-previewing a job the API would refuse with 400; clearing
      // the session here would make the tracking phase unresumable.
      const commitPromise = commitImport(
        jobId,
        layerName ? { ...metadata, layer_name: layerName } : metadata,
      );
      const raster = isRasterPreview(previewData);
      setIsRaster(raster);
      attachUrlImportCommit(commitPromise, raster);
      await commitPromise;
      if (!mountedRef.current) return;
      setStep('tracking');
      toast.success(t('urlImport.importStarted'));
    } catch (err) {
      if (!mountedRef.current) return;
      const msg = err instanceof ApiError ? err.message : t('urlImport.commitFailed');
      setError(msg);
      setStep('review');
      toast.error(msg);
    }
  };

  // The same JobProgress the rest of the import uses, so the download gets the
  // shared progress bar, step label and cancel control instead of a bespoke
  // spinner the user cannot escape.
  if (step === 'downloading' && jobId) {
    return (
      <div className="space-y-3">
        <JobProgress jobId={jobId} onReset={reset} isRasterEntry={false} />
        <p className="text-xs text-muted-foreground">
          {t('urlImport.downloadingHint')}
        </p>
        {/* While the status read itself is failing JobProgress
            offers only "Retry status", so without this the tab has no way out
            until a page reload. It CANCELS rather than resetting: a bare reset
            drops the only copy of the job id while the worker may still be
            downloading, stranding staged bytes nothing can reach. */}
        {jobPollFailing && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleCancelAndStartOver}
            disabled={isCancelling}
          >
            {isCancelling
              ? t('urlImport.cancelling')
              : t('urlImport.cancelAndStartOver')}
          </Button>
        )}
      </div>
    );
  }

  if (step === 'fetching' || step === 'previewing' || step === 'resuming') {
    const loadingLabel =
      step === 'fetching'
        ? t('urlImport.fetching')
        : step === 'resuming'
          ? t('urlImport.resuming')
          : t('urlImport.loadingPreview');
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card px-5 py-8">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="text-sm text-muted-foreground">{loadingLabel}</span>
        </div>
      </div>
    );
  }

  if ((step === 'review' || step === 'committing') && previewData) {
    const raster = isRasterPreview(previewData);
    const fp = isFilePreview(previewData) ? previewData : null;
    return (
      <div className="space-y-4">
        <ImportPreview preview={previewData} />
        {fp && (fp.layers?.length ?? 0) > 1 && (
          <div className="space-y-2">
            <Label htmlFor="url-import-layer">{t('urlImport.layerLabel')}</Label>
            <Select value={fp.layer_name} onValueChange={handleLayerChange} disabled={commitInFlight}>
              <SelectTrigger id="url-import-layer" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {fp.layers?.map((layer) => (
                  <SelectItem key={layer.name} value={layer.name}>
                    {layer.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <ImportMetadataForm
          defaultName={previewData.source_filename ?? fp?.layer_name ?? ''}
          detectedCrs={raster ? previewData.crs_epsg : (fp?.crs ?? null)}
          onCommit={handleCommit}
          isCommitting={commitInFlight}
          isRaster={raster}
          isTileset={isTilesetPreview(previewData)}
          previewData={raster ? previewData : undefined}
          previewColumns={fp?.columns}
          detectedGeometryType={fp?.geometry_type}
          detectedGeometryColumns={fp?.detected_geometry_columns}
        />
        <Button
          variant="outline"
          onClick={reset}
          disabled={commitInFlight}
        >
          {t('urlImport.startOver')}
        </Button>
      </div>
    );
  }

  if (step === 'tracking' && jobId) {
    return (
      <div className="space-y-4">
        <JobProgress jobId={jobId} onReset={reset} isRasterEntry={isRaster} />
        {/* JobProgress only offers its own start-over
            on a FAILED job, so a successful import left the tab pinned to
            that completed job with no way to run a second one. Reset has to
            be reachable from every terminal state; the failed case is
            already covered inside JobProgress and calls this same handler.
            Every OTHER terminal status, not just
            `complete` — #1709 made `cancelled` reachable (an admin can
            cancel the job from the job list) and JobProgress renders no
            action block for it, so this is the only control that can free
            the tab. `failed` stays excluded to avoid two start-overs. */}
        {isTerminalJobStatus(trackedJob?.status) &&
          trackedJob?.status !== 'failed' && (
            <Button variant="outline" onClick={reset}>
              {t('urlImport.importAnother')}
            </Button>
          )}
      </div>
    );
  }

  const urlFieldError = !jobId && error ? error : null;

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      {/* A transient preview failure keeps
          the staged job (`jobId` stays set) rather than clearing the
          session — offer an explicit retry against the SAME job (no
          re-download) and an explicit cancel, without hiding the url field
          below: resubmitting the same url still works exactly as it did
          before #1778 (startUrlImport reuses the fulfilled same-key
          session, so only the preview re-runs). */}
      {jobId && (
        <div className="mb-4 space-y-3 rounded-lg border border-border bg-surface-1 p-3.5">
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={handleRetryPreview}>
              {t('urlImport.retryPreview')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleCancelAndStartOver}
              disabled={isCancelling}
            >
              {isCancelling ? t('urlImport.cancelling') : t('urlImport.cancelAndStartOver')}
            </Button>
          </div>
        </div>
      )}
      <form onSubmit={handleFetch} className="space-y-5">
        <UploadKindChoice
          value={kind}
          onChange={(next) => setChosenKind(next === 'tiles3d' ? next : null)}
          disabled={!!jobId}
          tilesetAvailable={tilesetAvailable}
        />
        <div>
          <label className="eyebrow mb-2.5 block" htmlFor="file-url-input">
            {t('urlImport.label')}
          </label>
          <div className="flex items-stretch overflow-hidden rounded-lg border-[1.5px] border-border bg-surface-0 transition-colors focus-within:border-primary">
            <span className="flex items-center gap-1.5 border-e border-border bg-surface-2 px-3.5 font-mono text-mini uppercase tracking-wider text-muted-foreground font-medium">
              <LinkIcon className="size-3.5" />
              URL
            </span>
            <input
              id="file-url-input"
              type="url"
              aria-invalid={urlFieldError ? true : undefined}
              aria-describedby={urlFieldError ? 'file-url-error' : undefined}
              placeholder={t('urlImport.placeholder')}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={!!jobId}
              className="flex-1 bg-transparent px-3.5 py-2.5 font-mono text-sm text-foreground outline-none placeholder:text-muted-foreground/50 disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={!url.trim() || !!jobId}
              className="bg-primary px-4 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {t('urlImport.fetch')}
            </button>
          </div>
          {kind === null && (
            <div className="mt-2.5 flex flex-wrap gap-4 text-xs text-muted-foreground">
              <span>
                {t('urlImport.supported')}{' '}
                <code className="rounded-sm bg-surface-2 px-1.5 py-px font-mono text-mini text-muted-foreground">GeoParquet</code>{' '}
                <code className="rounded-sm bg-surface-2 px-1.5 py-px font-mono text-mini text-muted-foreground">FlatGeobuf</code>{' '}
                <code className="rounded-sm bg-surface-2 px-1.5 py-px font-mono text-mini text-muted-foreground">GeoJSON</code>{' '}
                <code className="rounded-sm bg-surface-2 px-1.5 py-px font-mono text-mini text-muted-foreground">GeoPackage</code>{' '}
                <code className="rounded-sm bg-surface-2 px-1.5 py-px font-mono text-mini text-muted-foreground">GeoTIFF</code>{' '}
                <code className="rounded-sm bg-surface-2 px-1.5 py-px font-mono text-mini text-muted-foreground">CSV</code>
              </span>
            </div>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="url-filename-override" className="text-xs text-muted-foreground">
            {t('urlImport.filenameLabel')}
          </Label>
          <Input
            id="url-filename-override"
            type="text"
            placeholder={t('urlImport.filenamePlaceholder')}
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            disabled={!!jobId}
            aria-describedby="url-filename-help"
            className="font-mono text-sm"
          />
          <p id="url-filename-help" className="text-xs text-muted-foreground">
            {t('urlImport.filenameHelpText')}
          </p>
        </div>

        {/* A lingering job's error already renders in the recovery panel
            above; avoid showing it twice. */}
        {urlFieldError && (
          <p id="file-url-error" role="alert" className="text-sm text-destructive">
            {urlFieldError}
          </p>
        )}
      </form>
    </div>
  );
}
