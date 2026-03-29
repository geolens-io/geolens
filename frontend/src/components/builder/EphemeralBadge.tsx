import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';

interface EphemeralBadgeProps {
  featureCount: number;
  onDismiss: () => void;
}

export function EphemeralBadge({ featureCount, onDismiss }: EphemeralBadgeProps) {
  const { t } = useTranslation('builder');

  return (
    <div className="absolute bottom-4 left-4 z-10 flex items-center gap-2 rounded-full bg-background/95 backdrop-blur-sm border shadow-sm px-3 py-1.5 text-xs">
      <span className="h-2 w-2 rounded-full bg-warning shrink-0" />
      <span className="text-muted-foreground">
        {t('ephemeralBadge.queryResult')} &middot; {t('ephemeralBadge.featureCount', { count: featureCount })}
      </span>
      <button
        type="button"
        onClick={onDismiss}
        className="text-muted-foreground hover:text-foreground transition-colors"
        title={t('ephemeralBadge.dismiss')}
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}
