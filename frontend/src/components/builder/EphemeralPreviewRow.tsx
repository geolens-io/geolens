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
import { useId } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { semanticBadgeColors } from '@/lib/status-colors';
import {
  ephemeralCountLabel,
  ephemeralStatusLabel,
  useAnnouncedLabel,
  type EphemeralCountInput,
  type PreviewSaveDisabledReason,
} from '@/components/builder/ephemeral-preview';

export interface EphemeralPreviewRowProps extends EphemeralCountInput {
  onDismiss: () => void;
  /** feat(#675): opens the Analysis panel prefilled with the operation behind
   *  this preview. feat(#1241): or opens the save-as-dataset dialog for a
   *  plain chat result. Absent when neither is on offer, which is why the
   *  action is conditional. */
  onSaveAsDataset?: () => void;
  /** feat(#1241): set instead of `onSaveAsDataset` when the save belongs on
   *  this preview but cannot be honoured — the affordance renders disabled
   *  with the reason spelled out rather than silently disappearing. */
  saveDisabledReason?: PreviewSaveDisabledReason;
}

export function EphemeralPreviewRow({
  featureCount,
  truncated,
  totalCount,
  viewportScoped,
  onDismiss,
  onSaveAsDataset,
  saveDisabledReason,
}: EphemeralPreviewRowProps) {
  const { t } = useTranslation('builder');
  const saveDisabledId = useId();

  const counts = { featureCount, truncated, totalCount, viewportScoped };
  const countLabel = ephemeralCountLabel(t, counts);
  const announcedLabel = useAnnouncedLabel(ephemeralStatusLabel(t, counts));
  const saveDisabledText = saveDisabledReason
    ? t('ephemeralBadge.saveTruncatedReason')
    : null;
  // A stated reason wins over a handler: "disabled" must not depend on the
  // caller also remembering to withhold the callback.
  const onSave = saveDisabledText ? undefined : onSaveAsDataset;

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
        {(onSave || saveDisabledText) && (
          <button
            type="button"
            onClick={onSave}
            disabled={!onSave}
            aria-describedby={saveDisabledText ? saveDisabledId : undefined}
            data-testid="ephemeral-preview-save"
            className="shrink-0 cursor-pointer rounded-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:text-muted-foreground disabled:no-underline"
          >
            {t('ephemeralBadge.saveAsDataset', { defaultValue: 'Save as dataset…' })}
          </button>
        )}
      </div>
      {/* feat(#1241): a disabled control with no stated reason is a dead end.
          The count line above already carries the "N of M" — this says why
          that N is what rules the save out. Visible text (not a title
          tooltip), because a disabled button gets no hover or focus. */}
      {saveDisabledText && (
        <p id={saveDisabledId} className="mt-0.5 ps-4 text-2xs text-muted-foreground">
          {saveDisabledText}
        </p>
      )}
    </div>
  );
}
