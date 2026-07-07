import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import type { FileEntryStatus } from '@/types/api';

const STATUS_CONFIG: Partial<Record<FileEntryStatus | 'detected', { key: string; cls: string; pulse?: boolean }>> = {
  uploading: { key: 'status.uploading', cls: 'bg-info/15 text-info', pulse: true },
  previewing: { key: 'status.detecting', cls: 'bg-info/15 text-info', pulse: true },
  preview: { key: 'status.detected', cls: 'bg-success/15 text-success' },
  committing: { key: 'status.importing', cls: 'bg-primary/12 text-primary', pulse: true },
  tracking: { key: 'status.ready', cls: 'bg-success/18 text-success' },
  complete: { key: 'status.ready', cls: 'bg-success/18 text-success' },
  'upload-failed': { key: 'status.failed', cls: 'bg-destructive/15 text-destructive' },
  'commit-failed': { key: 'status.failed', cls: 'bg-destructive/15 text-destructive' },
  failed: { key: 'status.failed', cls: 'bg-destructive/15 text-destructive' },
};

interface StatusPillProps {
  status: FileEntryStatus | string;
}

export function StatusPill({ status }: StatusPillProps) {
  const { t } = useTranslation('import');
  const c = STATUS_CONFIG[status as FileEntryStatus];
  // Unknown/transient statuses fall back to the raw status string. The dynamic
  // key is always a real 'import' key, so the cast is safe.
  const label = c ? (t(c.key) as string) : status;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10.5px] font-medium uppercase tracking-wider',
        c?.cls ?? 'bg-muted text-muted-foreground',
      )}
    >
      <span
        className={cn(
          'h-1.5 w-1.5 rounded-full bg-current',
          c?.pulse && 'animate-pulse',
        )}
      />
      {label}
    </span>
  );
}
