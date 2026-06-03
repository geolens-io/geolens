import { memo, useState, useMemo, useEffect, useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, FolderPlus, FolderMinus, Loader2, Trash2, MoreHorizontal } from 'lucide-react';
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
import type { MapLayerResponse } from '@/types/api';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface BulkActionBarProps {
  selectedIds: Set<string>;
  layers: MapLayerResponse[];
  // onClearSelection removed — selection clearing is the caller's responsibility
  // via handleBulk* wrappers in MapBuilderPage. The bar has no X/clear button.
  onBulkVisibility: (ids: Set<string>) => void;
  onBulkOpacity: (ids: Set<string>, opacity: number) => void;
  onBulkGroup: (ids: Set<string>) => void;
  onBulkUngroup: (ids: Set<string>) => void;
  onBulkDelete: (ids: Set<string>) => void;
  /** Phase 1047-04 (PERF-03): true while bulk-delete HTTP call is in flight.
   *  Swaps Trash2 → Loader2, disables the Delete button, sets aria-busy. */
  isDeleting?: boolean;
}

// ---------------------------------------------------------------------------
// Helper: parent_group_id is an in-memory field added by use-builder-layers,
// not in the MapLayerResponse type definition. Cast to access it safely.
// ---------------------------------------------------------------------------
function getParentGroupId(layer: MapLayerResponse): string | null {
  return (layer as unknown as { parent_group_id?: string | null }).parent_group_id ?? null;
}

// ---------------------------------------------------------------------------
// BulkActionBar component
// ---------------------------------------------------------------------------

export const BulkActionBar = memo(function BulkActionBar({
  selectedIds,
  layers,
  onBulkVisibility,
  onBulkOpacity,
  onBulkGroup,
  onBulkUngroup,
  onBulkDelete,
  isDeleting = false,
}: BulkActionBarProps) {
  const { t } = useTranslation('builder');
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [mounted, setMounted] = useState(false);
  const confirmId = useId();

  // Mount animation: initial state → rAF flip to mounted state (translate-y + opacity)
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const N = selectedIds.size;

  // Derive selected layers — memoized per render cycle
  const selectedLayers = useMemo(
    () => layers.filter((l) => selectedIds.has(l.id)),
    [layers, selectedIds],
  );

  // Derived values for display and enable/disable logic
  const avgOpacity =
    N > 0
      ? selectedLayers.reduce((sum, l) => sum + (l.opacity ?? 1), 0) / N
      : 1;

  const visibleCount = selectedLayers.filter((l) => l.visible !== false).length;
  const majorityVisible = visibleCount > N / 2;

  // Group enabled: ALL selected are loose vector layers (not in a group, not a group row, not raster/DEM/basemap)
  const canGroup = useMemo(
    () =>
      N > 0 &&
      selectedLayers.every(
        (l) =>
          !getParentGroupId(l) &&
          !((l.layer_type as string | null | undefined) ?? '').startsWith('group:folder') &&
          l.dataset_record_type === 'vector_dataset',
      ),
    [selectedLayers, N],
  );

  // Ungroup enabled: ALL selected are folder-group rows
  const canUngroup = useMemo(
    () =>
      N > 0 &&
      selectedLayers.every((l) =>
        ((l.layer_type as string | null | undefined) ?? '').startsWith('group:folder'),
      ),
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
    }
  }

  return (
    <div
      role="toolbar"
      aria-label={t('bulkActions.toolbarLabel', { count: N })}
      // SF-01 (Phase 1049): marker for UnifiedStackPanel's outside-click guard.
      // Without it, clicking the inline "Delete N layers" confirm button fires the
      // document-level mousedown listener BEFORE the React click handler, clearing
      // selection + unmounting the bar — so the onClick that calls onBulkDelete
      // never runs against a populated selection set.
      data-bulk-action-bar="true"
      className={cn(
        'sticky bottom-0 flex items-center gap-2 px-3',
        'h-12 bg-[var(--surface-2)] border-t border-[var(--border)]',
        'rounded-bl-[var(--radius-md)] rounded-br-[var(--radius-md)]',
        'transition-all duration-[--motion-fast]',
        mounted ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0',
        isDeleting ? 'cursor-not-allowed' : '',
      )}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={handleContainerKeyDown}
    >
      {/* Dedicated sr-only live region — announces selection count during normal
          state and "Deleting N layers…" when a bulk-delete is in flight.
          role="toolbar" must not carry aria-live. */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {isDeleting
          ? t('bulkActions.deletingLayers', { count: N })
          : t('bulkActions.liveAnnouncement', { count: N })}
      </span>
      {isDeleting ? (
        // ------------------------------------------------------------------
        // Deleting state — spinner replaces the normal / confirmation UI
        // ------------------------------------------------------------------
        <div className="flex items-center gap-2 w-full">
          <Loader2 className="size-4 animate-spin text-muted-foreground shrink-0" aria-hidden="true" />
          <span className="text-sm text-muted-foreground flex-1">
            {t('bulkActions.deletingLayers', { count: N })}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 px-2 shrink-0 text-destructive cursor-not-allowed"
            disabled={true}
            aria-busy={true}
            aria-label={t('bulkActions.deleteAriaLabel', { count: N })}
          >
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            {t('bulkActions.delete')}
          </Button>
        </div>
      ) : confirmingDelete ? (
        // ------------------------------------------------------------------
        // Confirmation state
        // ------------------------------------------------------------------
        // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions
        <div
          role="alertdialog"
          aria-labelledby={confirmId}
          className="flex items-center gap-2 w-full"
          onClick={(e) => e.stopPropagation()}
        >
          <p
            id={confirmId}
            className="flex-1 text-sm text-destructive text-center"
          >
            {t('bulkActions.deleteConfirmLabel', { count: N })}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            // eslint-disable-next-line jsx-a11y/no-autofocus -- focus on safe choice per AUD-09 / UI-SPEC §5
            autoFocus
            onClick={(e) => {
              e.stopPropagation();
              setConfirmingDelete(false);
            }}
            onPointerDown={(e) => e.stopPropagation()}
          >
            {t('bulkActions.deleteConfirmCancel')}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-destructive"
            onClick={(e) => {
              e.stopPropagation();
              onBulkDelete(selectedIds);
              setConfirmingDelete(false);
            }}
            onPointerDown={(e) => e.stopPropagation()}
          >
            {t('bulkActions.deleteConfirmAction', { count: N })}
          </Button>
        </div>
      ) : (
        // ------------------------------------------------------------------
        // Normal state: inline count + Visibility + Opacity, then overflow menu
        // SP-01 (Phase 1045): Group / Ungroup / Delete were previously inline
        // and clipped by the 340px sidebar `<aside class="overflow-hidden">`
        // (smoke check 2026-05-15, B-02). They now live behind a `…` overflow
        // trigger so the entire bar fits the sidebar width while Group / Ungroup
        // / Delete remain reachable via keyboard + pointer.
        // ------------------------------------------------------------------
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

          {/* Overflow menu — Group / Ungroup / Delete (SP-01) */}
          <DropdownMenu>
            <Tooltip>
              <TooltipTrigger asChild>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    data-testid="bulk-action-overflow"
                    className="h-8 w-8 p-0 shrink-0 ml-auto"
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
              // SP-01 (Phase 1045): Radix portals the menu content out of the
              // UnifiedStackPanel's stackPanelRef subtree. The panel's
              // `document.mousedown` outside-click guard treats portal clicks
              // as "outside" and would clear the multi-selection before our
              // onSelect handlers can read it. The data-bulk-action-menu
              // attribute is the marker UnifiedStackPanel reads to keep the
              // selection intact while this menu is the target.
              data-bulk-action-menu="true"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
            >
              <DropdownMenuItem
                data-testid="bulk-action-group"
                disabled={!canGroup}
                aria-label={t('bulkActions.groupAriaLabel', { count: N })}
                onSelect={() => {
                  if (canGroup) onBulkGroup(selectedIds);
                }}
              >
                <FolderPlus className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                {t('bulkActions.group')}
              </DropdownMenuItem>
              <DropdownMenuItem
                data-testid="bulk-action-ungroup"
                disabled={!canUngroup}
                aria-label={t('bulkActions.ungroupAriaLabel', { count: N })}
                onSelect={() => {
                  if (canUngroup) onBulkUngroup(selectedIds);
                }}
              >
                <FolderMinus className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                {t('bulkActions.ungroup')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                data-testid="bulk-action-delete"
                className="text-destructive focus:text-destructive"
                aria-label={t('bulkActions.deleteAriaLabel', { count: N })}
                onSelect={(e) => {
                  // Keep the row from auto-closing the menu so the inline
                  // confirmation dialog appears in the toolbar below.
                  e.preventDefault();
                  setConfirmingDelete(true);
                }}
              >
                <Trash2 className="h-3.5 w-3.5 me-2" aria-hidden="true" />
                {t('bulkActions.delete')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      )}
    </div>
  );

});
