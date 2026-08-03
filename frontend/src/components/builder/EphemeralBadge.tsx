import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ephemeralStatusLabel, useAnnouncedLabel } from '@/components/builder/ephemeral-preview';

// fix(#1009): the builder's full stack panel now surfaces the preview as a row
// (EphemeralPreviewRow), so this badge no longer renders there. It survives as
// the surface for the two places that have NO layer stack to put a row in:
//   - the public viewer (ViewerChatPanel — fix(#542) added it precisely because
//     the viewer's overlay had no legend entry, badge, or dismissal), and
//   - the builder below 1100px, where the sidebar collapses to SidebarRail.
// One ephemeral object still gets exactly one surface; which surface depends on
// whether a stack exists to host the row.
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
  const { t } = useTranslation('builder');

  // fix(#1009): the count sentence and the announced-label pattern moved to
  // ephemeral-preview.ts so this badge and the stack row cannot drift apart.
  const counts = { featureCount, truncated, totalCount };
  const statusLabel = ephemeralStatusLabel(t, counts);
  const announcedLabel = useAnnouncedLabel(statusLabel);

  // fix(#787 item 1): z-20, above the z-10 PluginHost slots. The bottom-left slot
  // is offset to clear this badge, but a panel taller than that offset overlaps it
  // and the z-index decided — the badge lost.
  return (
    <div className={cn('absolute bottom-8 start-4 z-20 flex items-center gap-2 rounded-md bg-background/95 backdrop-blur-sm border shadow-sm px-3 py-1.5 text-xs', className)}>
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
