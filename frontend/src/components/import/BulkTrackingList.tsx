import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { JobProgress } from './JobProgress';
import type { FileEntry } from '@/types/api';

interface BulkTrackingListProps {
  entries: FileEntry[];
  onReset: () => void;
}

export function BulkTrackingList({ entries, onReset }: BulkTrackingListProps) {
  const { t } = useTranslation('import');
  const trackable = entries.filter(
    (e) =>
      e.jobId &&
      (e.status === 'tracking' || e.status === 'complete' || e.status === 'failed'),
  );

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
      <Button variant="outline" onClick={onReset}>
        {t('bulk.uploadMore')}
      </Button>
    </div>
  );
}
