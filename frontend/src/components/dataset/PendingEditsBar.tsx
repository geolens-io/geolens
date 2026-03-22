import { Button } from '@/components/ui/button';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

interface PendingEditsBarProps {
  pendingCount: number;
  onSaveAll: () => void | Promise<void>;
  onCancelAll: () => void;
  isSaving?: boolean;
  className?: string;
}

function getPendingLabel(
  t: (key: string, options?: Record<string, unknown>) => string,
  pendingCount: number,
): string {
  return t('affordances.pending.count', { count: pendingCount });
}

export function PendingEditsBar({
  pendingCount,
  onSaveAll,
  onCancelAll,
  isSaving = false,
  className,
}: PendingEditsBarProps) {
  const { t } = useTranslation('dataset');

  if (pendingCount <= 0) {
    return null;
  }

  return (
    <div
      className={cn(
        'sticky bottom-4 z-40 rounded-lg border bg-card/95 px-4 py-3 shadow-lg backdrop-blur',
        className,
      )}
      data-testid="pending-edits-bar"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm font-medium" data-testid="pending-edits-count">
          {getPendingLabel(t, pendingCount)}
        </p>

        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onCancelAll}
            data-testid="pending-edits-cancel"
          >
            {t('affordances.pending.discard')}
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={onSaveAll}
            disabled={isSaving}
            data-testid="pending-edits-save"
          >
            {isSaving ? t('affordances.pending.saving') : t('affordances.pending.save')}
          </Button>
        </div>
      </div>
    </div>
  );
}
