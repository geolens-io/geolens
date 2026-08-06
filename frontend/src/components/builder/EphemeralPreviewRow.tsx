// fix(#1009): the analysis/chat preview drew an ephemeral overlay the layer
// stack knew nothing about — with several layers on screen nothing said which
// one was the preview, or how to get rid of it short of finding the badge in
// the map's corner. This is that preview as a row in the stack.
//
// Deliberately NOT a StackRow and deliberately NOT wrapped in SortableStackRow:
// the preview is not a MapLayerResponse and must never register with dnd-kit.
// `dragDisabled` on the sortable wrapper would not do — a disabled sortable is
// still a member of the sortable collection, so its id would sit in
// UnifiedStackPanel's `sortableIds` with no layer behind it, and MapBuilderPage's
// handleDragEnd resolves those ids back to real layers to write sort_order.
// UnifiedStackPanel renders this row BEFORE the SortableContext opens, the same
// way the DragOverlay ghost renders a bare StackRow.
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { semanticBadgeColors } from '@/lib/status-colors';
import {
  ephemeralCountLabel,
  ephemeralStatusLabel,
  useAnnouncedLabel,
  type EphemeralCountInput,
} from '@/components/builder/ephemeral-preview';

export interface EphemeralPreviewRowProps extends EphemeralCountInput {
  onDismiss: () => void;
  /** feat(#675): opens the Analysis panel prefilled with the operation behind
   *  this preview. Absent for previews with no analysis behind them (a plain
   *  chat query result), which is why the action is conditional. */
  onSaveAsDataset?: () => void;
}

export function EphemeralPreviewRow({
  featureCount,
  truncated,
  totalCount,
  viewportScoped,
  onDismiss,
  onSaveAsDataset,
}: EphemeralPreviewRowProps) {
  const { t } = useTranslation('builder');

  const counts = { featureCount, truncated, totalCount, viewportScoped };
  const countLabel = ephemeralCountLabel(t, counts);
  const announcedLabel = useAnnouncedLabel(ephemeralStatusLabel(t, counts));

  return (
    // Visual treatment reuses the vocabulary the badge established rather than
    // introducing tokens: the warning tint every other ephemeral/attention
    // affordance in the stack already uses (semanticBadgeColors.warning), made
    // dashed so the row reads as provisional next to the solid real rows.
    <div
      data-testid="ephemeral-preview-row"
      className="mx-2 mt-2 mb-1 rounded-md border border-dashed border-warning/30 bg-warning/10 px-2 py-1.5 text-xs"
    >
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full bg-warning" />
        {/* The visible copies below are aria-hidden so browse mode doesn't read
            the row twice — this region carries the same sentence the badge
            announced, so screen-reader output is unchanged by the move. */}
        <span role="status" className="sr-only">{announcedLabel}</span>
        <span aria-hidden="true" className="truncate font-medium">
          {t('ephemeralBadge.queryResult')}
        </span>
        <span
          aria-hidden="true"
          data-testid="ephemeral-preview-tag"
          className={cn(
            'shrink-0 rounded-sm px-1 text-2xs font-medium leading-tight',
            semanticBadgeColors.warning,
          )}
        >
          {t('previewRow.ephemeralTag', { defaultValue: 'Ephemeral — not saved' })}
        </span>
        <button
          type="button"
          onClick={onDismiss}
          data-testid="ephemeral-preview-dismiss"
          className="ms-auto shrink-0 cursor-pointer rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          title={t('ephemeralBadge.dismiss')}
          aria-label={t('ephemeralBadge.dismiss')}
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
      {/* Second line, indented past the status dot: the truncation count the
          badge carried, plus the #675 hand-off. Both were badge-only affordances
          before this row existed. */}
      <div className="mt-0.5 flex items-center gap-2 ps-4">
        <span aria-hidden="true" className="truncate text-muted-foreground">
          {countLabel}
        </span>
        {onSaveAsDataset && (
          <button
            type="button"
            onClick={onSaveAsDataset}
            data-testid="ephemeral-preview-save"
            className="shrink-0 cursor-pointer rounded-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t('ephemeralBadge.saveAsDataset', { defaultValue: 'Save as dataset…' })}
          </button>
        )}
      </div>
    </div>
  );
}
