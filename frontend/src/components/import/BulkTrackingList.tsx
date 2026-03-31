import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueries } from '@tanstack/react-query';
import { Layers } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { JobProgress } from './JobProgress';
import { VrtCreateDialog } from './VrtCreateDialog';
import { getJobStatus } from '@/api/ingest';
import { queryKeys } from '@/lib/query-keys';
import type { FileEntry } from '@/types/api';

interface BulkTrackingListProps {
  entries: FileEntry[];
  onReset: () => void;
}

export function BulkTrackingList({ entries, onReset }: BulkTrackingListProps) {
  const { t } = useTranslation('import');
  const [vrtDialogOpen, setVrtDialogOpen] = useState(false);

  const trackable = entries.filter(
    (e) =>
      e.jobId &&
      (e.status === 'tracking' || e.status === 'complete' || e.status === 'failed'),
  );

  // Identify raster entries (by file extension)
  const rasterEntries = trackable.filter(
    (e) => e.jobId && /\.tiff?$/i.test(e.fileName),
  );

  // Read cached job status for each raster entry (JobProgress already polls, no extra polling here)
  const rasterJobQueries = useQueries({
    queries: rasterEntries.map((entry) => ({
      queryKey: queryKeys.ingest.jobStatus(entry.jobId),
      queryFn: () => getJobStatus(entry.jobId!),
      enabled: !!entry.jobId,
      staleTime: Infinity,
      refetchInterval: false as const,
    })),
  });

  const completedRasterIds = rasterJobQueries
    .filter((q) => q.data?.status === 'complete' && q.data?.dataset_id)
    .map((q) => q.data!.dataset_id!);

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium">{t('bulk.importProgress')}</h3>
      {trackable.map((entry) => (
        <div key={entry.id}>
          <p className="mb-1 text-sm font-medium text-muted-foreground">
            {entry.fileName}
          </p>
          <JobProgress
            jobId={entry.jobId!}
            onReset={onReset}
            isRasterEntry={/\.tiff?$/i.test(entry.fileName)}
          />
        </div>
      ))}
      {completedRasterIds.length >= 2 && (
        <div className="flex items-center gap-2 rounded-md border border-dashed p-3">
          <Layers className="size-4 text-muted-foreground" />
          <span className="text-sm text-muted-foreground flex-1">
            {completedRasterIds.length} raster datasets ready
          </span>
          <Button variant="secondary" size="sm" onClick={() => setVrtDialogOpen(true)}>
            Create VRT Mosaic
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
