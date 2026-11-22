import {
  CircleCheck,
  Clock3,
  CircleX,
  TriangleAlert,
  WifiOff,
  type LucideIcon,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { semanticBadgeColors } from '@/lib/status-colors';
import { cn } from '@/lib/utils';
import type { SourceFreshness, SourceHealth } from '@/types/api';

interface StateChipSpec {
  icon: LucideIcon;
  color: string;
}

const FRESHNESS_SPECS: Record<Exclude<SourceFreshness, 'unknown'>, StateChipSpec> = {
  fresh: { icon: CircleCheck, color: semanticBadgeColors.success },
  due: { icon: Clock3, color: semanticBadgeColors.info },
  overdue: { icon: TriangleAlert, color: semanticBadgeColors.warning },
};

const HEALTH_SPECS: Record<Exclude<SourceHealth, 'unknown'>, StateChipSpec> = {
  healthy: { icon: CircleCheck, color: semanticBadgeColors.success },
  missing: { icon: CircleX, color: semanticBadgeColors.destructive },
  inaccessible: { icon: WifiOff, color: semanticBadgeColors.warning },
};

interface SourceStateChipProps {
  icon: LucideIcon;
  color: string;
  label: string;
  description: string;
  kind: 'freshness' | 'health';
  state: string;
  className?: string;
  /** Icon only, for dense rows; the label stays as the accessible name. */
  iconOnly?: boolean;
}

function SourceStateChip({
  icon: Icon,
  color,
  label,
  description,
  kind,
  state,
  className,
  iconOnly = false,
}: SourceStateChipProps) {
  return (
    <Badge
      variant="outline"
      className={cn('text-xs', color, iconOnly && 'px-1.5', className)}
      data-testid={`source-${kind}-chip`}
      data-state={state}
      title={iconOnly ? `${label}. ${description}` : description}
    >
      <Icon aria-hidden="true" />
      <span className={iconOnly ? 'sr-only' : undefined}>{label}</span>
    </Badge>
  );
}

interface FreshnessChipProps {
  state?: SourceFreshness;
  className?: string;
  iconOnly?: boolean;
}

/** Source refresh cadence. Unknown is intentionally silent. */
export function FreshnessChip({ state = 'unknown', className, iconOnly }: FreshnessChipProps) {
  const { t } = useTranslation();
  if (state === 'unknown') return null;

  const spec = FRESHNESS_SPECS[state];
  return (
    <SourceStateChip
      {...spec}
      kind="freshness"
      state={state}
      label={t(`sourceState.freshness.${state}.label`)}
      description={t(`sourceState.freshness.${state}.description`)}
      className={className}
      iconOnly={iconOnly}
    />
  );
}

interface HealthChipProps {
  state?: SourceHealth;
  className?: string;
  iconOnly?: boolean;
}

/** Persisted source reachability. Unknown is intentionally silent. */
export function HealthChip({ state = 'unknown', className, iconOnly }: HealthChipProps) {
  const { t } = useTranslation();
  if (state === 'unknown') return null;

  const spec = HEALTH_SPECS[state];
  return (
    <SourceStateChip
      {...spec}
      kind="health"
      state={state}
      label={t(`sourceState.health.${state}.label`)}
      description={t(`sourceState.health.${state}.description`)}
      className={className}
      iconOnly={iconOnly}
    />
  );
}
