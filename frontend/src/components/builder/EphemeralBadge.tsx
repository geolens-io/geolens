import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

interface EphemeralBadgeProps {
  featureCount: number;
  onDismiss: () => void;
  /** Whether the result was truncated server-side. */
  truncated?: boolean;
  /** Total feature count before truncation. */
  totalCount?: number;
  /** feat(#675): opens the Analysis panel prefilled with the operation behind
   *  this preview. Builder-only — the viewer has no Analysis rail, so it
   *  never passes this. */
  onSaveAsDataset?: () => void;
  /** Position override — the viewer's bottom-left corner is occupied by its basemap toggle. */
  className?: string;
}

export function EphemeralBadge({ featureCount, onDismiss, truncated, totalCount, onSaveAsDataset, className }: EphemeralBadgeProps) {
  const { t, i18n } = useTranslation('builder');

  const countLabel = truncated && totalCount != null
    ? t('ephemeralBadge.featureCountTruncated', {
        count: featureCount,
        // fix(#674 audit): group the total per locale, matching how the rest of
        // the app renders feature counts (OverviewTab). `count` drives plural
        // selection so it stays numeric — it is capped anyway, never grouped.
        total: totalCount.toLocaleString(i18n.language),
        defaultValue: '{{count}} of {{total}} features',
      })
    : t('ephemeralBadge.featureCount', { count: featureCount });
  const statusLabel = `${t('ephemeralBadge.queryResult')} · ${countLabel}`;

  // fix(#784): live regions only announce mutations made while the region is
  // already in the accessibility tree — this badge mounts WITH its text, so
  // role="status" on the wrapper alone would stay silent. Mount the region
  // empty and populate it a frame later so the preview success (and any later
  // count change) arrives as a mutation assistive tech actually reads.
  const [announcedLabel, setAnnouncedLabel] = useState('');
  useEffect(() => {
    const frame = requestAnimationFrame(() => setAnnouncedLabel(statusLabel));
    return () => cancelAnimationFrame(frame);
  }, [statusLabel]);

  return (
    <div className={cn('absolute bottom-8 start-4 z-[8] flex items-center gap-2 rounded-md bg-background/95 backdrop-blur-sm border shadow-sm px-3 py-1.5 text-xs', className)}>
      <span className="h-2 w-2 rounded-full bg-warning shrink-0" />
      <span role="status" className="sr-only">{announcedLabel}</span>
      {/* fix(#784): aria-hidden so browse mode doesn't read the badge text
          twice — the sr-only status region above carries the same string. */}
      <span aria-hidden="true" className="text-muted-foreground">
        {statusLabel}
      </span>
      {onSaveAsDataset && (
        <button
          type="button"
          onClick={onSaveAsDataset}
          className="cursor-pointer font-medium text-primary hover:underline"
        >
          {t('ephemeralBadge.saveAsDataset', { defaultValue: 'Save as dataset…' })}
        </button>
      )}
      <button
        type="button"
        onClick={onDismiss}
        className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors"
        title={t('ephemeralBadge.dismiss')}
        aria-label={t('ephemeralBadge.dismiss')}
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}
