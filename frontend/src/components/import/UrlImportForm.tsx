import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Link as LinkIcon } from 'lucide-react';
import { ApiError } from '@/api/client';
import { previewFile, commitImport } from '@/api/ingest';
import {
  clearUrlImport,
  markUrlImportCommitting,
  peekUrlImport,
  startUrlImport,
  type UrlImportSession,
} from '@/api/url-import-session';
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
  | 'review'
  | 'committing'
  | 'tracking';

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
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const reset = () => {
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
    if (session.committed && session.jobId) {
      // Past preview: the ingest is already queued server-side, so hand
      // straight to JobProgress, which polls the job and is therefore
      // correct however long this form was unmounted.
      setJobId(session.jobId);
      setStep('tracking');
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
    if (!jobId) return;
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
    if (!jobId || !previewData) return;

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
      markUrlImportCommitting(commitPromise);
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
  if (step === 'fetching' || step === 'previewing') {
    const loadingLabel =
      step === 'fetching' ? t('urlImport.fetching') : t('urlImport.loadingPreview');
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
              className="w-full rounded-md border border-border bg-surface-0 px-3 py-2 text-sm"
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
          isCommitting={step === 'committing'}
          isRaster={raster}
          previewData={raster ? previewData : undefined}
          previewColumns={fp?.columns}
          detectedGeometryType={fp?.geometry_type}
          detectedGeometryColumns={fp?.detected_geometry_columns}
        />
        <Button variant="outline" onClick={reset}>
          {t('urlImport.startOver')}
        </Button>
      </div>
    );
  }

  // ── Job tracking ──
  if (step === 'tracking' && jobId) {
    return <JobProgress jobId={jobId} onReset={reset} isRasterEntry={previewData ? isRasterPreview(previewData) : false} />;
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
