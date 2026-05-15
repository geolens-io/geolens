import { memo, useState, useMemo, useEffect, useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, FolderPlus, FolderMinus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
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
      className={cn(
        'sticky bottom-0 flex items-center gap-2 px-3',
        'h-12 bg-[var(--surface-2)] border-t border-[var(--border)]',
        'rounded-bl-[var(--radius-md)] rounded-br-[var(--radius-md)]',
        'transition-all duration-[--motion-fast]',
        mounted ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0',
      )}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={handleContainerKeyDown}
    >
      {/* Dedicated sr-only live region — announces only the selection count,
          not the entire toolbar content. role="toolbar" must not carry aria-live. */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {t('bulkActions.liveAnnouncement', { count: N })}
      </span>
      {confirmingDelete ? (
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
        // Normal state: 5 action buttons
        // ------------------------------------------------------------------
        <>
          {/* Selected count label */}
          <span className="text-[13px] font-medium text-muted-foreground shrink-0">
            {t('bulkActions.selectedCount', { count: N })}
          </span>

          {/* Divider */}
          <span className="mx-1 h-4 w-px bg-[var(--border)] shrink-0" aria-hidden="true" />

          {/* Visibility toggle */}
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

          {/* Opacity slider group */}
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

          {/* Group button */}
          {canGroup ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 gap-1.5 px-2 shrink-0"
                  aria-label={t('bulkActions.groupAriaLabel', { count: N })}
                  onClick={(e) => {
                    e.stopPropagation();
                    onBulkGroup(selectedIds);
                  }}
                  onPointerDown={(e) => e.stopPropagation()}
                >
                  <FolderPlus className="h-3.5 w-3.5" aria-hidden="true" />
                  <span className="hidden sm:inline text-xs">
                    {t('bulkActions.group')}
                  </span>
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">{t('bulkActions.group')}</TooltipContent>
            </Tooltip>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex shrink-0">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={cn(
                      'h-8 gap-1.5 px-2 opacity-40 cursor-not-allowed pointer-events-none',
                    )}
                    aria-label={t('bulkActions.groupAriaLabel', { count: N })}
                    aria-disabled="true"
                    tabIndex={-1}
                  >
                    <FolderPlus className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="hidden sm:inline text-xs">
                      {t('bulkActions.group')}
                    </span>
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent side="top">
                {t('bulkActions.groupDisabledTooltip')}
              </TooltipContent>
            </Tooltip>
          )}

          {/* Ungroup button */}
          {canUngroup ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 gap-1.5 px-2 shrink-0"
                  aria-label={t('bulkActions.ungroupAriaLabel', { count: N })}
                  onClick={(e) => {
                    e.stopPropagation();
                    onBulkUngroup(selectedIds);
                  }}
                  onPointerDown={(e) => e.stopPropagation()}
                >
                  <FolderMinus className="h-3.5 w-3.5" aria-hidden="true" />
                  <span className="hidden sm:inline text-xs">
                    {t('bulkActions.ungroup')}
                  </span>
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">{t('bulkActions.ungroup')}</TooltipContent>
            </Tooltip>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex shrink-0">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={cn(
                      'h-8 gap-1.5 px-2 opacity-40 cursor-not-allowed pointer-events-none',
                    )}
                    aria-label={t('bulkActions.ungroupAriaLabel', { count: N })}
                    aria-disabled="true"
                    tabIndex={-1}
                  >
                    <FolderMinus className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="hidden sm:inline text-xs">
                      {t('bulkActions.ungroup')}
                    </span>
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent side="top">
                {t('bulkActions.ungroupDisabledTooltip')}
              </TooltipContent>
            </Tooltip>
          )}

          {/* Delete button */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5 px-2 text-destructive shrink-0 ml-auto"
                aria-label={t('bulkActions.deleteAriaLabel', { count: N })}
                onClick={(e) => {
                  e.stopPropagation();
                  setConfirmingDelete(true);
                }}
                onPointerDown={(e) => e.stopPropagation()}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                <span className="hidden sm:inline text-xs">
                  {t('bulkActions.delete')}
                </span>
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top">{t('bulkActions.delete')}</TooltipContent>
          </Tooltip>
        </>
      )}
    </div>
  );
});
