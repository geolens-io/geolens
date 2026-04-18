import { cn } from '@/lib/utils';
import type { FileEntryStatus } from '@/types/api';

const STATUS_CONFIG: Partial<Record<FileEntryStatus | 'detected', { label: string; cls: string; pulse?: boolean }>> = {
  uploading: { label: 'Uploading', cls: 'bg-info/15 text-info', pulse: true },
  previewing: { label: 'Detecting', cls: 'bg-info/15 text-info', pulse: true },
  preview: { label: 'Detected', cls: 'bg-success/15 text-success' },
  committing: { label: 'Importing', cls: 'bg-primary/12 text-primary', pulse: true },
  tracking: { label: 'Ready', cls: 'bg-success/18 text-success' },
  complete: { label: 'Ready', cls: 'bg-success/18 text-success' },
  'upload-failed': { label: 'Failed', cls: 'bg-destructive/15 text-destructive' },
  'commit-failed': { label: 'Failed', cls: 'bg-destructive/15 text-destructive' },
  failed: { label: 'Failed', cls: 'bg-destructive/15 text-destructive' },
};

interface StatusPillProps {
  status: FileEntryStatus | string;
}

export function StatusPill({ status }: StatusPillProps) {
  const c = STATUS_CONFIG[status as FileEntryStatus] ?? { label: status, cls: 'bg-muted text-muted-foreground' };

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10.5px] font-medium uppercase tracking-wider',
        c.cls,
      )}
    >
      <span
        className={cn(
          'h-1.5 w-1.5 rounded-full bg-current',
          c.pulse && 'animate-pulse',
        )}
      />
      {c.label}
    </span>
  );
}
