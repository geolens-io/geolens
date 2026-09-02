import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Link as LinkIcon } from 'lucide-react';
import { ApiError } from '@/api/client';
import { previewFile, commitImport } from '@/api/ingest';
import {
  clearUrlImport,
  attachUrlImportCommit,
  peekUrlImport,
  startUrlImport,
  type UrlImportSession,
} from '@/api/url-import-session';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import type {
  CommitImportRequest,
  FilePreviewResponse,
  RasterPreviewResponse,
} from '@/types/api';
import { isFilePreview, isRasterPreview } from './utils';
import { ImportPreview } from './ImportPreview';
import { ImportMetadataForm } from './ImportMetadataForm';
import { JobProgress } from './JobProgress';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

type UrlStep =
  | 'idle'
  | 'fetching'
  | 'previewing'
  | 'resuming'
  | 'review'
  | 'committing'
  | 'tracking';

/**
 * fix(#1708 codex r25): the job statuses that are still moving.
 *
 * `JobStatusResponse.status` is pending | running | complete | failed |
 * cancelled | fanned_out. Reset has to be reachable from EVERY terminal
 * state (the r22 invariant), and r22 satisfied that by listing the terminal
 * statuses that existed then — so when #1709 made `cancelled` reachable for
 * an import job, a cancelled URL import pinned this tab to a finished job
 * with no way to start another. Neither PR could see it alone: #1709's
 * terminal-status sweep ran before this component existed on main.
 *
 * So the predicate names what is IN FLIGHT and treats everything else as
 * terminal. An unknown or newly added status then fails toward offering the
 * escape hatch, which is the safe direction — a spurious "Import another"
 * on a live job is a cosmetic bug, a job with no way out is the one that
 * strands the tab for the rest of the SPA session.
 */
const IN_FLIGHT_JOB_STATUSES: ReadonlySet<string> = new Set(['pending', 'running']);

function isTerminalJobStatus(status: string | undefined): boolean {
  return status !== undefined && !IN_FLIGHT_JOB_STATUSES.has(status);
}

/**
 * feat(#1705): import a dataset straight from an HTTP(S) file URL.
 *
 * The URL variant of the Upload tab: the backend fetches the file
 * server-side (SSRF-validated, size-capped) into staging, and from there the
 * flow is identical to a direct upload — preview, review metadata, commit,
 * track. Single-file, single-dataset; multi-layer containers get a layer
 * picker before commit.
 */
export function UrlImportForm() {
  const { t } = useTranslation('import');
  const [step, setStep] = useState<UrlStep>('idle');
  const [url, setUrl] = useState('');
  const [filename, setFilename] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<
    FilePreviewResponse | RasterPreviewResponse | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  // fix(#1708 codex r22): survives a resume, where previewData does not.
  const [isRaster, setIsRaster] = useState(false);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // fix(#1708 codex r24): the window in which a request has been issued that
  // nothing can recall. Every control below that would mutate `step`, the
  // module session, or an in-flight request is disabled on this AND refuses
  // on it in its handler — a disabled control is a fact about one rendered
  // tree, the handler guard is the invariant.
  //
  // The set is read off the RENDERED CONTROLS rather than off a list of
  // remembered events, which is what makes it complete: `committing` is the
  // only in-flight state that renders a control at all, because `fetching`,
  // `previewing` and `resuming` all render the spinner branch, which has
  // none. `resuming` is named here anyway — it is the same uncancellable
  // commit, adopted by a later mount — so the predicate stays true if that
  // branch ever grows a control.
  const commitInFlight = step === 'committing' || step === 'resuming';

  // fix(#1708 codex r22): reset is available from every TERMINAL state and
  // refuses only while an uncancellable operation is in flight — clearing
  // the session mid-commit orphans a commit that then succeeds untracked.
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

  // fix(#1708 codex r19): the session is owned by the module, so a tab
  // switch mid-import cannot strand the job. Everything below only decides
  // what THIS mount displays.
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

      setStep('previewing');
      try {
        const preview = await previewFile(fetchedJobId);
        if (!mountedRef.current) return;
        setPreviewData(preview);
        setStep('review');
      } catch (err) {
        if (!mountedRef.current) return;
        const msg = err instanceof ApiError ? err.message : t('urlImport.previewFailed');
        setError(msg);
        setStep('idle');
        toast.error(msg);
        // fix(#1778): the fetch-failure branch above already releases the
        // session; without this, `idle` renders no Start Over control, so a
        // later mount's peekUrlImport() re-adopts this dead job and replays
        // the same failing preview POST every time the URL tab is revisited.
        clearUrlImport();
      }
    },
    [t],
  );

  // Shares JobProgress's query key, so this is the same cached poll rather
  // than a second one. Only used to decide which controls to offer.
  const { data: trackedJob } = useJobStatus(step === 'tracking' ? jobId : null);

  // fix(#1708 codex r21): SUBSCRIBE to the commit rather than sampling a
  // flag. r20 stored a boolean set before the await, so a mount arriving
  // mid-commit read "committed" and entered tracking; a commit that then
  // failed flipped the flag back at module scope while this component kept
  // polling a job that was still pending and previewable. Awaiting the
  // promise removes the window entirely — whenever the outcome lands, the
  // mounted form gets the real one.
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
    const trimmed = url.trim();
    if (!trimmed) return;
    await runSession(startUrlImport(trimmed, filename.trim() || undefined));
  };

  const handleLayerChange = async (layerName: string) => {
    // fix(#1708 codex r24): re-previewing mid-commit replaced `committing`
    // with `previewing` and then UNCONDITIONALLY with `review`, which
    // re-enabled Start Over and the commit button against a request that
    // cannot be recalled — orphaning the queued job, or offering a second
    // commit for one already started. Same cell of the r22 table as reset;
    // the event axis, not the state axis, was what that round missed.
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
    // fix(#1708 codex r24): the commit control was disabled during its own
    // commit (ImportMetadataForm gates its submit on `isCommitting`) but the
    // handler took anything it was given. Same belt-and-braces the layer
    // picker and reset now have, for the same reason: the UI half only holds
    // for the tree that rendered it.
    if (!jobId || !previewData || commitInFlight) return;

    setStep('committing');
    setError(null);

    const fp = isFilePreview(previewData) ? previewData : null;
    const layerName =
      fp && (fp.layers?.length ?? 0) > 1 ? fp.layer_name : undefined;

    try {
      // fix(#1708 codex r20): registered BEFORE the await, so an unmount
      // mid-commit still leaves a session that resumes into tracking. The
      // `committed` flag is what stops a remount from re-previewing a job
      // the API would refuse with 400 — clearing the session here (r19)
      // is what made the tracking phase unresumable in the first place.
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

  // ── Loading states ──
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
        {step === 'fetching' && (
          // fix(#1708 codex r2): the request legitimately stays open for the
          // whole server-side download (bounded at 8 minutes, inside the
          // edge proxy's deadline) — say so instead of looking hung.
          <p className="text-xs text-muted-foreground">
            {t('urlImport.fetchingHint')}
          </p>
        )}
      </div>
    );
  }

  // ── Review and commit ──
  if ((step === 'review' || step === 'committing') && previewData) {
    const raster = isRasterPreview(previewData);
    const fp = isFilePreview(previewData) ? previewData : null;
    return (
      <div className="space-y-4">
        <ImportPreview preview={previewData} />
        {fp && (fp.layers?.length ?? 0) > 1 && (
          <div className="space-y-2">
            <Label htmlFor="url-import-layer">{t('urlImport.layerLabel')}</Label>
            <select
              id="url-import-layer"
              value={fp.layer_name}
              onChange={(e) => handleLayerChange(e.target.value)}
              disabled={commitInFlight}
              className="w-full rounded-md border border-border bg-surface-0 px-3 py-2 text-sm disabled:opacity-60"
            >
              {fp.layers?.map((layer) => (
                <option key={layer.name} value={layer.name}>
                  {layer.name}
                </option>
              ))}
            </select>
          </div>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <ImportMetadataForm
          defaultName={previewData.source_filename ?? fp?.layer_name ?? ''}
          detectedCrs={raster ? previewData.crs_epsg : (fp?.crs ?? null)}
          onCommit={handleCommit}
          isCommitting={commitInFlight}
          isRaster={raster}
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

  // ── Job tracking ──
  if (step === 'tracking' && jobId) {
    return (
      <div className="space-y-4">
        <JobProgress jobId={jobId} onReset={reset} isRasterEntry={isRaster} />
        {/* fix(#1708 codex r22): JobProgress only offers its own start-over
            on a FAILED job, so a successful import left the tab pinned to
            that completed job with no way to run a second one. Reset has to
            be reachable from every terminal state; the failed case is
            already covered inside JobProgress and calls this same handler.
            fix(#1708 codex r25): every OTHER terminal status, not just
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

  // ── Idle — URL input form ──
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <form onSubmit={handleFetch} className="space-y-5">
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
              placeholder={t('urlImport.placeholder')}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="flex-1 bg-transparent px-3.5 py-2.5 font-mono text-sm text-foreground outline-none placeholder:text-muted-foreground/50"
            />
            <button
              type="submit"
              disabled={!url.trim()}
              className="bg-primary px-4 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {t('urlImport.fetch')}
            </button>
          </div>
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
            className="font-mono text-sm"
          />
          <p className="text-xs text-muted-foreground">{t('urlImport.filenameHelpText')}</p>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}
      </form>
    </div>
  );
}
