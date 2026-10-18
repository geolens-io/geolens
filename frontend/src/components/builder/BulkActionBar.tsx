import { memo, useState, useMemo, useEffect, useId, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, FolderPlus, FolderMinus, Loader2, Paintbrush, Trash2, MoreHorizontal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { canJoinFolderGroup } from '@/components/builder/folder-groups';
import type { MapLayerResponse } from '@/types/api';

interface BulkActionBarProps {
  selectedIds: Set<string>;
  layers: MapLayerResponse[];
  // Selection clearing is the caller's responsibility (handleBulk* wrappers in
  // MapBuilderPage); the bar has no X/clear button.
  onBulkVisibility: (ids: Set<string>) => void;
  onBulkOpacity: (ids: Set<string>, opacity: number) => void;
  onBulkGroup: (ids: Set<string>) => void;
  onBulkUngroup: (ids: Set<string>) => void;
  onBulkDelete: (ids: Set<string>) => void;
  /**
   * Apply the first selected (or copied) layer's style to all
   * geometry-compatible selected layers. Optional; the menu item hides when
   * absent.
   */
  onBulkApplyStyle?: (ids: Set<string>) => void;
  /** True while bulk-delete HTTP call is in flight.
   *  Swaps Trash2 → Loader2, disables the Delete button, sets aria-busy. */
  isDeleting?: boolean;
  /**
   * Count of layers in the in-flight delete batch, captured synchronously in
   * the hook BEFORE the optimistic removal. The optimistic setLocalLayers
   * empties the selection-derived deletableCount in the same commit that sets
   * isDeleting, so deriving the label from props would announce "Deleting 0
   * layers…".
   */
  deletingCount?: number;
}

export const BulkActionBar = memo(function BulkActionBar({
  selectedIds,
  layers,
  onBulkVisibility,
  onBulkOpacity,
  onBulkGroup,
  onBulkUngroup,
  onBulkDelete,
  onBulkApplyStyle,
  isDeleting = false,
  deletingCount,
}: BulkActionBarProps) {
  const { t } = useTranslation('builder');
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [mounted, setMounted] = useState(false);
  const confirmId = useId();
  // The overflow items' aria-label overrides their subtree as the accessible
  // name, which hides inline disabled-reason hints from assistive tech. Each
  // hint is exposed via aria-describedby (only while it renders), keeping the
  // short label as the name and the reason as the description.
  const hintId = useId();
  const barRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLDivElement>(null);

  // Every exit path out of the inline delete-confirm must hand focus somewhere
  // stable instead of dropping it on <body>. The pre-confirm trigger (the
  // overflow-menu Delete item) unmounts on confirm, so restore to the first
  // remaining enabled control in the bar, else the bar itself (tabIndex={-1}
  // makes it focusable as the last resort). Mirrors the row-chrome.tsx
  // InlineDeleteConfirm cancel-path restore.
  const restoreFocusToBar = useCallback(() => {
    requestAnimationFrame(() => {
      const bar = barRef.current;
      if (!bar) return;
      const first = bar.querySelector<HTMLElement>('button:not([disabled])');
      (first ?? bar).focus();
    });
  }, []);

  // Minimal focus trap for the aria-modal confirm: Tab and Shift+Tab cycle
  // between Cancel and the destructive action.
  const handleConfirmKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab') return;
    const root = confirmRef.current;
    if (!root) return;
    const focusables = Array.from(root.querySelectorAll<HTMLElement>('button:not([disabled])'));
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }, []);

  // Mount animation: initial state → rAF flip to mounted state (translate-y + opacity)
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const N = selectedIds.size;

  const selectedLayers = useMemo(
    () => layers.filter((l) => selectedIds.has(l.id)),
    [layers, selectedIds],
  );

  // Group container rows have no backend record (handleBulkDelete filters them
  // out of the batch), so every delete-facing count must be the DELETABLE
  // count, not the selection size. Otherwise two group headers would promise
  // "Delete 2 layers" and silently do nothing; the Delete item disables when
  // nothing is deletable.
  const deletableCount = useMemo(
    () => selectedLayers.filter((l) => !isFolderGroupLayer(l)).length,
    [selectedLayers],
  );

  const avgOpacity =
    N > 0
      ? selectedLayers.reduce((sum, l) => sum + (l.opacity ?? 1), 0) / N
      : 1;

  const visibleCount = selectedLayers.filter((l) => l.visible !== false).length;
  const majorityVisible = visibleCount > N / 2;

  // Group enabled: ALL selected are loose layers (not in a group, not a group
  // row). canJoinFolderGroup is the shared predicate, matching StackRow's "Add
  // to group…" and drag-and-drop membership, which accept raster/DEM rows too.
  const canGroup = useMemo(
    () => N > 0 && selectedLayers.every(canJoinFolderGroup),
    [selectedLayers, N],
  );

  // Ungroup enabled: ALL selected are folder-group rows
  const canUngroup = useMemo(
    () =>
      N > 0 &&
      selectedLayers.every((l) => isFolderGroupLayer(l)),
    [selectedLayers, N],
  );

  // Reset confirmation state whenever selection is fully cleared
  useEffect(() => {
    if (selectedIds.size === 0) {
      setConfirmingDelete(false);
    }
  }, [selectedIds.size]);

  // Handle Escape inside the confirmation state — stop propagation so it does
  // NOT reach the parent's selection-clearing Escape handler (selection preserved).
  function handleContainerKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape' && confirmingDelete) {
      e.stopPropagation();
      setConfirmingDelete(false);
      // Escape closed a focus-owning confirm: restore focus.
      restoreFocusToBar();
    }
  }

  // While a delete is in flight the optimistic removal has already emptied
  // selectedLayers, so deletableCount is 0; render the batch size the hook
  // captured synchronously instead.
  const displayDeleteCount = isDeleting ? (deletingCount ?? deletableCount) : deletableCount;

  return (
    <div
      ref={barRef}
      tabIndex={-1}
      role="toolbar"
      aria-label={t('bulkActions.toolbarLabel', { count: N })}
      // Marker for UnifiedStackPanel's outside-click guard. Without it,
      // clicking the inline "Delete N layers" confirm button fires the
      // document-level mousedown listener BEFORE the React click handler,
      // clearing selection and unmounting the bar, so onBulkDelete never runs
      // against a populated selection set.
      data-bulk-action-bar="true"
      className={cn(
        'sticky bottom-0 flex items-center gap-2 px-3',
        'h-12 bg-[var(--surface-2)] border-t border-[var(--border)]',
        'rounded-bl-[var(--radius-md)] rounded-br-[var(--radius-md)]',
        'transition-[transform,opacity] duration-[--motion-fast]',
        mounted ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0',
        isDeleting ? 'cursor-not-allowed' : '',
      )}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={handleContainerKeyDown}
    >
      {/* Dedicated sr-only live region: announces the selection count in normal
          state and "Deleting N layers…" while a bulk-delete is in flight.
          role="toolbar" must not carry aria-live. Mounts EMPTY and populates on
          the rAF tick (the `mounted` flip), because screen readers ignore
          content already present when a live region enters the accessibility
          tree. */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {mounted
          ? isDeleting
            ? t('bulkActions.deletingLayers', { count: displayDeleteCount })
            : t('bulkActions.liveAnnouncement', { count: N })
          : null}
      </span>
      {isDeleting ? (
        // Deleting state: spinner replaces the normal / confirmation UI.
        <div className="flex items-center gap-2 w-full">
          <Loader2 className="size-4 animate-spin text-muted-foreground shrink-0" aria-hidden="true" />
          <span className="text-sm text-muted-foreground flex-1">
            {t('bulkActions.deletingLayers', { count: displayDeleteCount })}
          </span>
          {/* variant="destructive" (not ghost+text-destructive) so the
              in-flight button matches the confirm button the user just pressed. */}
          <Button
            type="button"
            variant="destructive"
            size="sm"
            className="h-8 gap-1.5 px-2 shrink-0 cursor-not-allowed"
            disabled={true}
            aria-busy={true}
            aria-label={t('bulkActions.deleteAriaLabel', { count: displayDeleteCount })}
          >
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            {t('bulkActions.delete')}
          </Button>
        </div>
      ) : confirmingDelete ? (
        // Confirmation state.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
        <div
          ref={confirmRef}
          role="alertdialog"
          // aria-modal, backed by the Tab-cycle trap below and focus
          // restoration on every exit path.
          aria-modal="true"
          aria-labelledby={confirmId}
          className="flex items-center gap-2 w-full"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={handleConfirmKeyDown}
        >
          <p
            id={confirmId}
            className="flex-1 text-sm text-destructive text-center"
          >
            {/* The confirm promises only what the handler will
                actually delete — group rows are filtered out of the batch. */}
            {t('bulkActions.deleteConfirmLabel', { count: deletableCount })}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            // eslint-disable-next-line jsx-a11y/no-autofocus -- focus on safe choice
            autoFocus
            onClick={(e) => {
              e.stopPropagation();
              setConfirmingDelete(false);
              // The confirm owned focus: hand it back.
              restoreFocusToBar();
            }}
            onPointerDown={(e) => e.stopPropagation()}
          >
            {t('bulkActions.deleteConfirmCancel')}
          </Button>
          {/* Destructive action styled variant="destructive" and placed last
              (right), matching InlineDeleteConfirm and every ui/alert-dialog
              footer. */}
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onBulkDelete(selectedIds);
              setConfirmingDelete(false);
              // Confirming unmounts this button (the bar swaps to the deleting
              // state): restore to a stable element (the first remaining
              // control, else the bar itself), never the dead trigger.
              restoreFocusToBar();
            }}
            onPointerDown={(e) => e.stopPropagation()}
          >
            {t('bulkActions.deleteConfirmAction', { count: deletableCount })}
          </Button>
        </div>
      ) : (
        // Normal state: inline count + Visibility + Opacity, then an overflow
        // menu. Group / Ungroup / Delete live behind a `…` trigger because
        // inline they clipped at the 340px sidebar `<aside
        // class="overflow-hidden">`; they stay reachable via keyboard and
        // pointer.
        <>
          {/* Selected count label */}
          <span className="text-xs font-medium text-muted-foreground shrink-0">
            {t('bulkActions.selectedCount', { count: N })}
          </span>

          {/* Divider */}
          <span className="mx-1 h-4 w-px bg-[var(--border)] shrink-0" aria-hidden="true" />

          {/* Visibility toggle (inline) */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5 px-2 shrink-0"
                aria-label={t('bulkActions.visibilityAriaLabel', { count: N })}
                onClick={(e) => {
                  e.stopPropagation();
                  onBulkVisibility(selectedIds);
                }}
                onPointerDown={(e) => e.stopPropagation()}
              >
                {majorityVisible ? (
                  <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                  <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                <span className="hidden sm:inline text-xs">
                  {t('bulkActions.visibility')}
                </span>
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top">{t('bulkActions.visibility')}</TooltipContent>
          </Tooltip>

          {/* Opacity slider group (inline) */}
          <div
            className="flex items-center gap-1 shrink-0"
            onPointerDown={(e) => e.stopPropagation()}
          >
            <span className="hidden sm:inline text-xs text-muted-foreground">
              {t('bulkActions.opacity')}
            </span>
            <Slider
              value={[Math.round(avgOpacity * 100)]}
              min={0}
              max={100}
              step={1}
              className="w-20"
              aria-label={t('bulkActions.opacityAriaLabel', { count: N })}
              onValueChange={(v) => {
                onBulkOpacity(selectedIds, v[0] / 100);
              }}
            />
          </div>

          {/* Overflow menu — Group / Ungroup / Delete */}
          <DropdownMenu>
            <Tooltip>
              <TooltipTrigger asChild>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    data-testid="bulk-action-overflow"
                    className="h-8 w-8 p-0 shrink-0 ms-auto"
                    aria-label={t('bulkActions.moreActionsAriaLabel', { count: N })}
                    onPointerDown={(e) => e.stopPropagation()}
                  >
                    <MoreHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
              </TooltipTrigger>
              <TooltipContent side="top">{t('bulkActions.moreActions')}</TooltipContent>
            </Tooltip>
            <DropdownMenuContent
              align="end"
              side="top"
              className="w-48"
              // Radix portals the menu content out of UnifiedStackPanel's
              // stackPanelRef subtree, so the panel's `document.mousedown`
              // outside-click guard would treat portal clicks as "outside" and
              // clear the multi-selection before our onSelect handlers read it.
              // The data-bulk-action-menu attribute is the marker the panel
              // reads to keep the selection intact while this menu is the
              // target.
              data-bulk-action-menu="true"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
            >
              {/* Apply one selected layer's style to all geometry-compatible
                  peers. Enabled at 2+ selected; the hook filters compatibility
                  and skips mismatches with a count toast. */}
              {onBulkApplyStyle && (
                <DropdownMenuItem
                  data-testid="bulk-action-apply-style"
                  disabled={N < 2}
                  aria-label={t('bulkActions.applyStyleAriaLabel', { count: N })}
                  aria-describedby={N < 2 ? `${hintId}-apply-style` : undefined}
                  onSelect={() => {
                    if (N >= 2) onBulkApplyStyle(selectedIds);
                  }}
                >
                  <Paintbrush className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                  {/* Disabled items state their reason inline
                      (tooltips don't fire on disabled elements). */}
                  <span className="flex flex-col items-start">
                    {t('bulkActions.applyStyle')}
                    {N < 2 && (
                      <span id={`${hintId}-apply-style`} className="text-2xs text-muted-foreground">
                        {t('bulkActions.applyStyleHint', { defaultValue: 'Select at least 2 layers' })}
                      </span>
                    )}
                  </span>
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                data-testid="bulk-action-group"
                disabled={!canGroup}
                aria-label={t('bulkActions.groupAriaLabel', { count: N })}
                aria-describedby={!canGroup ? `${hintId}-group` : undefined}
                onSelect={() => {
                  if (canGroup) onBulkGroup(selectedIds);
                }}
              >
                <FolderPlus className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                <span className="flex flex-col items-start">
                  {t('bulkActions.group')}
                  {!canGroup && (
                    <span id={`${hintId}-group`} className="text-2xs text-muted-foreground">
                      {t('bulkActions.groupHint', { defaultValue: 'Only ungrouped layers can be grouped' })}
                    </span>
                  )}
                </span>
              </DropdownMenuItem>
              <DropdownMenuItem
                data-testid="bulk-action-ungroup"
                disabled={!canUngroup}
                aria-label={t('bulkActions.ungroupAriaLabel', { count: N })}
                aria-describedby={!canUngroup ? `${hintId}-ungroup` : undefined}
                onSelect={() => {
                  if (canUngroup) onBulkUngroup(selectedIds);
                }}
              >
                <FolderMinus className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                <span className="flex flex-col items-start">
                  {t('bulkActions.ungroup')}
                  {!canUngroup && (
                    <span id={`${hintId}-ungroup`} className="text-2xs text-muted-foreground">
                      {t('bulkActions.ungroupHint', { defaultValue: 'Select only group rows to ungroup' })}
                    </span>
                  )}
                </span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                data-testid="bulk-action-delete"
                className="text-destructive focus:text-destructive"
                // Disabled when the selection holds only group rows —
                // the handler filters them out, so confirming would delete nothing.
                disabled={deletableCount === 0}
                aria-label={t('bulkActions.deleteAriaLabel', { count: deletableCount })}
                aria-describedby={deletableCount === 0 ? `${hintId}-delete` : undefined}
                onSelect={(e) => {
                  // Keep the row from auto-closing the menu so the inline
                  // confirmation dialog appears in the toolbar below.
                  e.preventDefault();
                  if (deletableCount > 0) setConfirmingDelete(true);
                }}
              >
                <Trash2 className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                <span className="flex flex-col items-start">
                  {t('bulkActions.delete')}
                  {deletableCount === 0 && (
                    <span id={`${hintId}-delete`} className="text-2xs text-muted-foreground">
                      {t('bulkActions.deleteHint', { defaultValue: 'Group rows are deleted from their row menu' })}
                    </span>
                  )}
                </span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      )}
    </div>
  );

});
