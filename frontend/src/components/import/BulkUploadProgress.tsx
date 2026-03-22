import { useTranslation } from 'react-i18next';
import { Check, X } from 'lucide-react';
import { Card } from '@/components/ui/card';
import type { FileEntry } from '@/types/api';

interface BulkUploadProgressProps {
  entries: FileEntry[];
}

export function BulkUploadProgress({ entries }: BulkUploadProgressProps) {
  const { t } = useTranslation('import');

  return (
    <Card className="p-6">
      <p className="mb-4 text-sm font-medium">
        {t('bulk.uploading', { count: entries.length })}
      </p>
      <div className="space-y-3">
        {entries.map((entry) => (
          <div key={entry.id} className="flex items-center gap-3">
            {(entry.status === 'uploading' || entry.status === 'previewing') && (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            )}
            {entry.status === 'preview' && (
              <Check className="h-4 w-4 text-success" />
            )}
            {entry.status === 'upload-failed' && (
              <X className="h-4 w-4 text-destructive" />
            )}
            <span className="text-sm">{entry.fileName}</span>
            <span className="text-xs text-muted-foreground">
              {entry.status === 'uploading' && t('bulk.statusUploading')}
              {entry.status === 'previewing' && t('bulk.statusPreviewing')}
              {entry.status === 'preview' && t('bulk.statusReady')}
            </span>
            {entry.status === 'upload-failed' && entry.error && (
              <span className="text-xs text-destructive">{entry.error}</span>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
