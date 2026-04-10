import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useQueries } from '@tanstack/react-query';
import { ArrowRight, CheckCircle2, Layers } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { JobProgress } from './JobProgress';
import { VrtCreateDialog } from './VrtCreateDialog';
import { getJobStatus } from '@/api/ingest';
import { queryKeys } from '@/lib/query-keys';
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

  // Read job status for each raster entry — piggybacks on JobProgress cache updates
  const rasterJobQueries = useQueries({
    queries: rasterEntries.map((entry) => ({
      queryKey: queryKeys.ingest.jobStatus(entry.jobId),
      queryFn: () => getJobStatus(entry.jobId!),
      enabled: !!entry.jobId,
    })),
  });

  const completedRasterIds = rasterJobQueries
    .filter((q) => q.data?.status === 'complete' && q.data?.dataset_id)
    .map((q) => q.data!.dataset_id!);

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

  const activeEntries = trackable.filter((_, index) => {
    const job = jobQueries[index]?.data;
    return job?.status !== 'complete';
  });

  const getKindLabel = (kind: NonNullable<FileEntry['submittedKind']>) => {
    if (kind === 'raster') return t('bulk.kindRaster', { defaultValue: 'Raster dataset' });
    if (kind === 'vector') return t('bulk.kindVector', { defaultValue: 'Spatial dataset' });
    return t('bulk.kindTable', { defaultValue: 'Non-spatial table' });
  };

  // Auto-open VRT dialog when triggered from review page and all raster jobs complete
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

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium">{t('bulk.importProgress')}</h3>
      {completedEntries.length > 0 && (
        <div className="rounded-xl border border-success/30 bg-success/5 p-4 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="size-4 text-success" />
                <p className="text-sm font-semibold">
                  {t('bulk.readyTitle', {
                    count: completedEntries.length,
                    defaultValue: completedEntries.length === 1 ? '1 dataset ready' : `${completedEntries.length} datasets ready`,
                  })}
                </p>
              </div>
              <p className="text-sm text-muted-foreground">
                {t('bulk.readyDescription', {
                  defaultValue: 'Open the finished datasets directly, or keep uploading while the rest of the jobs settle.',
                })}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={onReset}>
              {t('bulk.uploadMore')}
            </Button>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {completedEntries.map((entry) => (
              <div key={entry.datasetId} className="flex items-center justify-between gap-3 rounded-lg border bg-background/80 px-3 py-3">
                <div className="min-w-0 space-y-1">
                  <p className="truncate text-sm font-medium">{entry.title}</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary" className="text-[11px]">
                      {getKindLabel(entry.kind)}
                    </Badge>
                    <Badge variant="outline" className="text-[11px] capitalize">
                      {entry.visibility}
                    </Badge>
                  </div>
                </div>
                <Button asChild size="sm" className="shrink-0">
                  <Link to={`/datasets/${entry.datasetId}`}>
                    {t('bulk.openDataset', { defaultValue: 'Open dataset' })}
                    <ArrowRight className="ms-1 size-3" />
                  </Link>
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}
      {activeEntries.map((entry) => (
        <div key={entry.id}>
          <p className="mb-1 text-sm font-medium text-muted-foreground">
            {entry.fileName}
          </p>
          <JobProgress
            jobId={entry.jobId!}
            onReset={onReset}
            isRasterEntry={isRasterFile(entry.fileName)}
          />
        </div>
      ))}
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
      {completedEntries.length === 0 && (
        <Button variant="outline" onClick={onReset}>
          {t('bulk.uploadMore')}
        </Button>
      )}
      <VrtCreateDialog
        open={vrtDialogOpen}
        onOpenChange={setVrtDialogOpen}
        initialSourceIds={completedRasterIds}
      />
    </div>
  );
}
