import { useState, useEffect, useRef, useMemo } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useQueries } from '@tanstack/react-query';
import { ArrowRight, CheckCircle2, Layers } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { JobProgress } from './JobProgress';
import { VrtCreateDialog } from './VrtCreateDialog';
import { TypeTag } from './TypeTag';
import { StatusPill } from './StatusPill';
import { getJobStatus } from '@/api/ingest';
import { queryKeys } from '@/lib/query-keys';
import { getVisibilityLabel } from '@/i18n/labels';
import type { FileEntry } from '@/types/api';

const isRasterFile = (name: string) => /\.tiff?$/i.test(name);

interface BulkTrackingListProps {
  entries: FileEntry[];
  onReset: () => void;
  autoOpenVrt?: boolean;
}

export function BulkTrackingList({ entries, onReset, autoOpenVrt = false }: BulkTrackingListProps) {
  const { t } = useTranslation('import');
  const [vrtDialogOpen, setVrtDialogOpen] = useState(false);
  const autoOpenedRef = useRef(false);

  const trackable = entries.filter(
    (e) =>
      e.jobId &&
      (e.status === 'tracking' || e.status === 'complete' || e.status === 'failed'),
  );

  const rasterEntries = trackable.filter(
    (e) => e.jobId && isRasterFile(e.fileName),
  );

  const jobQueries = useQueries({
    queries: trackable.map((entry) => ({
      queryKey: queryKeys.ingest.jobStatus(entry.jobId),
      queryFn: () => getJobStatus(entry.jobId!),
      enabled: !!entry.jobId,
    })),
  });

  const rasterEntryIds = new Set(rasterEntries.map((e) => e.jobId));
  const completedRasterIds = trackable.flatMap((entry, i) => {
    if (!rasterEntryIds.has(entry.jobId)) return [];
    const job = jobQueries[i]?.data;
    if (job?.status !== 'complete' || !job.dataset_id) return [];
    return [job.dataset_id];
  });

  const completedEntries = trackable.flatMap((entry, index) => {
    const job = jobQueries[index]?.data;
    if (job?.status !== 'complete' || !job.dataset_id) return [];
    return [{
      datasetId: job.dataset_id,
      title: entry.submittedTitle ?? job.source_filename ?? entry.fileName,
      visibility: entry.submittedVisibility ?? 'private',
      kind: entry.submittedKind ?? 'table',
    }];
  });

  // 'fanned_out' parents have no further status to display — children carry
  // forward progress under their own job IDs (the per-layer modal already shown).
  // Treat fanned_out as terminal so the parent doesn't sit in "Active and recent
  // jobs" forever. See SMOKE-v1013-F1.
  const isTerminal = (status: string | undefined) =>
    status === 'complete' || status === 'fanned_out';

  const activeEntries = trackable.filter((_, index) => {
    const job = jobQueries[index]?.data;
    return !isTerminal(job?.status);
  });

  const inProgressCount = trackable.filter((_, index) => {
    const status = jobQueries[index]?.data?.status;
    return status === 'pending' || status === 'running';
  }).length;

  // Fan-out parents count as "done" for the all-done check — their per-layer
  // outcome was already shown via the FanOutResults modal in UploadForm.
  const doneCount = trackable.filter((_, index) => {
    const status = jobQueries[index]?.data?.status;
    return isTerminal(status);
  }).length;
  const allDone = doneCount === trackable.length && trackable.length > 0;

  useEffect(() => {
    if (
      autoOpenVrt &&
      !autoOpenedRef.current &&
      rasterEntries.length >= 2 &&
      completedRasterIds.length === rasterEntries.length
    ) {
      autoOpenedRef.current = true;
      setVrtDialogOpen(true);
    }
  }, [autoOpenVrt, completedRasterIds.length, rasterEntries.length]);

  const progressStyle = useMemo(
    () => ({ width: `${trackable.length > 0 ? Math.round((completedEntries.length / trackable.length) * 100) : 0}%` }),
    [completedEntries.length, trackable.length],
  );

  /* ── All-done completion card ──────────────────────── */
  if (allDone) {
    return (
      <div className="space-y-4">
        <div className="overflow-hidden rounded-2xl border border-border bg-card">
          {/* Hero */}
          <div className="border-b border-border bg-gradient-to-b from-success/[0.06] to-transparent px-8 py-10 text-center">
            <div className="mx-auto mb-3.5 flex h-14 w-14 items-center justify-center rounded-full bg-success text-success-foreground shadow-[0_0_0_6px] shadow-success/12">
              <CheckCircle2 className="size-6" />
            </div>
            <h2 className="mb-1.5 text-[22px] font-medium tracking-tight">
              {t('complete.heroTitle', {
                count: completedEntries.length,
                defaultValue: `${completedEntries.length} ${completedEntries.length === 1 ? 'dataset' : 'datasets'} added to the catalog`,
              })}
            </h2>
            <p className="text-[13.5px] text-muted-foreground">
              {t('complete.heroDesc', { defaultValue: 'All files ingested, tiled, and indexed. Ready to query, style, and map.' })}
            </p>
          </div>

          {/* Summary stats */}
          <div className="grid grid-cols-2 divide-x divide-border border-b border-border sm:grid-cols-4">
            {[
              { label: t('complete.statDatasets', { defaultValue: 'Datasets' }), value: completedEntries.length },
              { label: t('complete.statVector', { defaultValue: 'Vector' }), value: completedEntries.filter((e) => e.kind === 'vector').length },
              { label: t('complete.statRaster', { defaultValue: 'Raster' }), value: completedEntries.filter((e) => e.kind === 'raster').length },
              { label: t('complete.statTabular', { defaultValue: 'Tabular' }), value: completedEntries.filter((e) => e.kind === 'table').length },
            ].map((stat, i) => (
              <div key={i} className="px-5 py-4">
                <dt className="mb-1.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{stat.label}</dt>
                <dd className="text-xl font-medium tracking-tight">{stat.value}</dd>
              </div>
            ))}
          </div>

          {/* Completed dataset rows */}
          <div>
            {completedEntries.map((entry, i) => (
              <div
                key={entry.datasetId}
                className={cn(
                  'grid grid-cols-[32px_1fr_auto] items-center gap-3 px-4 py-3',
                  i < completedEntries.length - 1 && 'border-b border-border',
                )}
              >
                <TypeTag kind={entry.kind === 'vector' ? 'vector' : entry.kind === 'raster' ? 'raster' : 'table'} />
                <div className="min-w-0">
                  <p className="truncate text-[13.5px] font-medium tracking-tight">{entry.title}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <Badge variant="secondary" className="text-[10px]">{entry.kind}</Badge>
                    <Badge variant="outline" className="text-[10px]">{getVisibilityLabel(t, entry.visibility)}</Badge>
                  </div>
                </div>
                <StatusPill status="complete" />
              </div>
            ))}
          </div>

          {/* Next actions */}
          <div className="flex flex-wrap items-center gap-2.5 border-t border-border bg-surface-0 px-5 py-4">
            <span className="text-[13px] font-semibold me-1">{t('complete.next', { defaultValue: 'Next:' })}</span>
            {completedEntries.length === 1 && completedEntries[0] && (
              <Button asChild size="sm">
                <Link to={`/datasets/${completedEntries[0].datasetId}`}>
                  {t('bulk.openDataset', { defaultValue: 'Open dataset' })}
                  <ArrowRight className="ms-1 size-3 rtl-mirror" />
                </Link>
              </Button>
            )}
            {completedEntries.length > 1 && (
              <Button asChild size="sm">
                <Link to="/">{t('complete.viewCatalog', { defaultValue: 'View in Catalog' })}</Link>
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={onReset}>
              {t('complete.importMore', { defaultValue: 'Import more' })}
            </Button>
            {completedRasterIds.length >= 2 && (
              <Button variant="secondary" size="sm" onClick={() => setVrtDialogOpen(true)}>
                <Layers className="me-1 size-3" />
                {t('bulk.createVrtMosaic')}
              </Button>
            )}
          </div>
        </div>

        <VrtCreateDialog
          open={vrtDialogOpen}
          onOpenChange={setVrtDialogOpen}
          initialSourceIds={completedRasterIds}
        />
      </div>
    );
  }

  /* ── In-progress state (batch banner + active jobs) ── */
  return (
    <div className="space-y-4">
      {/* Batch progress banner */}
      {inProgressCount > 0 && (
        <div className="flex items-center gap-3.5 rounded-xl border border-primary/20 bg-primary/[0.07] px-4 py-3">
          <div className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
          <div className="flex-1">
            <p className="text-[13px]">
              <span className="font-semibold">{t('bulk.importingFiles', { count: trackable.length, defaultValue: `Importing ${trackable.length} files` })}</span>
            </p>
            <p className="font-mono text-[11px] text-muted-foreground tracking-wide mt-0.5">
              {t('bulk.progressDetail', {
                done: completedEntries.length,
                active: inProgressCount,
                queued: trackable.length - completedEntries.length - inProgressCount,
                defaultValue: `${completedEntries.length} complete · ${inProgressCount} in progress · ${trackable.length - completedEntries.length - inProgressCount} queued`,
              })}
            </p>
          </div>
          <div className="h-1 w-48 max-w-[220px] overflow-hidden rounded-full bg-surface-2">
            <span
              className="block h-full rounded-full bg-primary transition-[width] duration-300"
              style={progressStyle}
            />
          </div>
        </div>
      )}

      {/* Completed entries summary */}
      {completedEntries.length > 0 && (
        <div className="rounded-xl border border-success/30 bg-success/5 p-4">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 className="size-4 text-success" />
            <p className="text-sm font-semibold">
              {t('bulk.readyTitle', {
                count: completedEntries.length,
                defaultValue: `${completedEntries.length} ${completedEntries.length === 1 ? 'dataset' : 'datasets'} ready`,
              })}
            </p>
          </div>
          <div className="grid gap-2 lg:grid-cols-2">
            {completedEntries.map((entry) => (
              <div key={entry.datasetId} className="flex items-center justify-between gap-3 rounded-lg border bg-background/80 px-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{entry.title}</p>
                  <Badge variant="secondary" className="text-[10px] mt-0.5">{entry.kind}</Badge>
                </div>
                <Button asChild size="sm" className="shrink-0">
                  <Link to={`/datasets/${entry.datasetId}`}>
                    {t('bulk.openDataset', { defaultValue: 'Open dataset' })}
                    <ArrowRight className="ms-1 size-3 rtl-mirror" />
                  </Link>
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Active jobs */}
      {activeEntries.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm font-medium">{t('bulk.activeJobs', { defaultValue: 'Active and recent jobs' })}</p>
          <div className="grid gap-4 lg:grid-cols-2">
            {activeEntries.map((entry) => (
              <div key={entry.id}>
                <p className="mb-1 text-sm font-medium text-muted-foreground">{entry.fileName}</p>
                <JobProgress
                  jobId={entry.jobId!}
                  onReset={onReset}
                  isRasterEntry={isRasterFile(entry.fileName)}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* VRT mosaic prompt */}
      {completedRasterIds.length >= 2 && (
        <div className="flex items-center gap-2 rounded-md border border-dashed p-3">
          <Layers className="size-4 text-muted-foreground" />
          <span className="text-sm text-muted-foreground flex-1">
            {t('bulk.rasterDatasetsReady', { count: completedRasterIds.length })}
          </span>
          <Button variant="secondary" size="sm" onClick={() => setVrtDialogOpen(true)}>
            {t('bulk.createVrtMosaic')}
          </Button>
        </div>
      )}

      <Button variant="outline" onClick={onReset}>
        {t('bulk.uploadMore')}
      </Button>

      <VrtCreateDialog
        open={vrtDialogOpen}
        onOpenChange={setVrtDialogOpen}
        initialSourceIds={completedRasterIds}
      />
    </div>
  );
}
