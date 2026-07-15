import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { fileEntryStatusColors } from '@/lib/status-colors';
import type { FileEntryStatus } from '@/types/api';

const STATUS_CONFIG: Partial<Record<FileEntryStatus | 'detected', { key: string; pulse?: boolean }>> = {
  uploading: { key: 'status.uploading', pulse: true },
  previewing: { key: 'status.detecting', pulse: true },
  preview: { key: 'status.detected' },
  committing: { key: 'status.importing', pulse: true },
  tracking: { key: 'status.ready' },
  complete: { key: 'status.ready' },
  'upload-failed': { key: 'status.failed' },
  'commit-failed': { key: 'status.failed' },
  failed: { key: 'status.failed' },
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
    <Badge
      className={cn(
        'gap-1.5 font-mono text-2xs uppercase tracking-wider',
        fileEntryStatusColors[status] ?? 'border-border bg-muted text-muted-foreground',
      )}
    >
      <span
        className={cn(
          'h-1.5 w-1.5 rounded-full bg-current',
          c?.pulse && 'animate-pulse',
        )}
      />
      {label}
    </Badge>
  );
}
