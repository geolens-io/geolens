import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { TypeTag } from './TypeTag';
import { StatusPill } from './StatusPill';
import { fileExt, kindFromEntry } from './utils';
import type { FileEntry } from '@/types/api';

interface BulkUploadProgressProps {
  entries: FileEntry[];
}

export function BulkUploadProgress({ entries }: BulkUploadProgressProps) {
  const { t } = useTranslation('import');

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border bg-surface-0 px-4 py-2.5 font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
        <span>
          {t('bulk.uploading', { count: entries.length })}
        </span>
        <span className="flex-1" />
        <span>{t('bulk.detectingHint', { defaultValue: 'Uploading & detecting…' })}</span>
      </div>

      {/* File rows */}
      {entries.map((entry, i) => {
        const ext = fileExt(entry.fileName);
        const kind = kindFromEntry(entry);
        const pct =
          entry.status === 'uploading' && entry.progress != null
            ? Math.round(entry.progress * 100)
            : null;

        return (
          <div
            key={entry.id}
            className={cn(
              'grid grid-cols-[32px_1fr_auto] items-center gap-3 px-4 py-3',
              i < entries.length - 1 && 'border-b border-border',
            )}
          >
            <TypeTag kind={kind} />
            <div>
              <div className="text-[13.5px] font-medium tracking-tight">
                {entry.fileName.replace(/\.[^.]+$/, '')}
                <span className="font-mono font-normal text-muted-foreground">{ext}</span>
              </div>
              {pct != null && (
                <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-surface-2">
                  <div
                    className="h-full rounded-full bg-primary transition-[width] duration-150 ease-out"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              )}
              {entry.status === 'upload-failed' && entry.error && (
                <p className="mt-0.5 text-xs text-destructive">{entry.error}</p>
              )}
            </div>
            <div className="flex items-center gap-2">
              {pct != null && (
                <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                  {pct}%
                </span>
              )}
              <StatusPill status={entry.status} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
