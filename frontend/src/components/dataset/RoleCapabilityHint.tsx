import { CircleHelp, Lock } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import type { DatasetCapabilityReason } from '@/components/dataset/hooks/use-dataset-edit-capabilities';

interface RoleCapabilityHintProps {
  reason?: DatasetCapabilityReason | null;
  helper?: string;
  onOpenHelp?: () => void;
  className?: string;
}

export function RoleCapabilityHint({
  reason = 'insufficient_role',
  helper,
  onOpenHelp,
  className,
}: RoleCapabilityHintProps) {
  const { t } = useTranslation('dataset');
  const resolvedReason = reason ?? 'insufficient_role';
  const message = helper ?? t(`affordances.roleHint.${resolvedReason}`);
  const Icon = resolvedReason === 'insufficient_role' ? Lock : CircleHelp;

  return (
    <div
      role="status"
      className={cn(
        'inline-flex items-center gap-2 text-xs text-muted-foreground',
        className,
      )}
      data-testid="role-capability-hint"
    >
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>{message}</span>
      {onOpenHelp && (
        <button
          type="button"
          onClick={onOpenHelp}
          className="font-medium text-primary hover:underline"
        >
          {t('affordances.roleHelp')}
        </button>
      )}
    </div>
  );
}
