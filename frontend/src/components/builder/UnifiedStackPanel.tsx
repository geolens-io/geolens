import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  DragOverlay,
  useDndContext,
} from '@dnd-kit/core';
import type { DraggableAttributes } from '@dnd-kit/core';
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, GripVertical, Plus, Search, Settings } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { StackRow } from '@/components/builder/StackRow';
import { SortableStackRow } from '@/components/builder/SortableStackRow';
import { BasemapGroupRowWrapper } from '@/components/builder/BasemapGroupRowWrapper';
import { FolderGroupRowWrapper } from '@/components/builder/FolderGroupRowWrapper';
import { CatalogDragGhost } from '@/components/builder/CatalogDragGhost';
// The ephemeral analysis/chat preview as a non-persisting stack row.
import { EphemeralPreviewRow, type EphemeralPreviewRowProps } from '@/components/builder/EphemeralPreviewRow';
import { EmptyStackState, eyebrowClassName } from '@/components/builder/EmptyStackState';
import { BulkActionBar } from '@/components/builder/BulkActionBar';
import { getParentGroupId } from '@/components/builder/folder-groups';
// Single source of truth for which rows the stack renders; the same helper
// MapBuilderPage uses for selectableRowIds, so range selection can't disagree
// with what is on screen.
import { computeSelectableRowIds } from '@/components/builder/selection-utils';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { cn } from '@/lib/utils';
import type { MapLayerResponse, MapVisibility } from '@/types/api';
import type { BasemapGroupInfo, BasemapSublayerInfo } from '@/components/builder/stack-types';
import { computeDisambiguationLabels, isLayerHiddenFromMapAudience } from './map-stack';
import { geometryClassOf, type GeometryStyleClass } from '@/lib/builder/layer-style-clipboard';

// Re-exported so imports of CatalogDragGhost from this module keep working.
export { CatalogDragGhost };

// Stable noop, created once at module scope so optional-prop fallbacks don't
// produce new function references each render and defeat memo() on children
// (BasemapGroupRowWrapper, FolderGroupRowWrapper, SortableStackRow).
const NOOP = () => {};

interface UnifiedStackPanelProps {
  layers: MapLayerResponse[];
  /**
   * The map's own visibility, used to compute per-layer audience-hidden badges
   * (a private dataset on a public/shared map is silently filtered out for
   * other audiences). Defaults to private, meaning no audience beyond the owner
   * and so no warning.
   */
  mapVisibility?: MapVisibility;
  /**
   * Ids of DEM layers whose 2D overlay is off and that aren't the active 3D
   * terrain source: they paint nothing despite the eye being on. Computed by
   * MapBuilderPage (needs terrain_config).
   */
  drawsNothingLayerIds?: ReadonlySet<string>;
  selectedLayerId: string | null;
  onSelectLayer: (id: string | null) => void;
  onToggleVisibility: (id: string) => void;
  /**
   * @deprecated: inert here (drag-reorder is lifted to MapBuilderPage). Kept
   * for call-site compatibility.
   */
  onReorder: (layers: MapLayerResponse[]) => void;
  /**
   * @deprecated: inert here (opacity editing lives in the LayerEditorPanel
   * flyout). Kept for call-site compatibility.
   */
  onOpacityChange: (layerId: string, opacity: number) => void;
  onRemove: (id: string) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onDuplicate: (id: string) => void;
  // Authoring actions threaded to the kebab and bulk bar.
  onZoomToLayer?: (id: string) => void;
  /** Opens the Analysis panel prefilled with this layer. */
  onAnalyzeLayer?: (id: string) => void;
  onCopyStyle?: (id: string) => void;
  onPasteStyle?: (id: string) => void;
  onBulkApplyStyle?: (ids: Set<string>) => void;
  /** Geometry class of the currently-copied style (null = nothing copied). Used
   *  to enable "Paste style" only on geometry-compatible rows. */
  copiedStyleGeometryClass?: GeometryStyleClass | null;
  onKeyboardReorder?: (layerId: string, direction: 'up' | 'down') => boolean | void;
  /** Shared aria-live announcer for the keyboard reorder mode. */
  onAnnounce?: (text: string) => void;
  onAddDataClick: (initialQuery?: string) => void;
  onAddDataset?: (datasetId: string) => void;
  onSettingsClick: () => void;
  isSettingsOpen?: boolean;
  /** Id of the item currently being dragged (from the lifted drag context in MapBuilderPage) */
  activeDragId?: string | null;
  groupMeta?: Record<string, { expanded: boolean }>;
  onToggleGroupExpand?: (groupId: string) => void;
  basemapGroup?: BasemapGroupInfo | null;
  isBasemapExpanded?: boolean;
  onToggleSublayerVisibility?: (sublayerId: string) => void;
  /**
   * @deprecated: inert here (per-sublayer opacity lives in the LayerEditorPanel
   * flyout). Kept for call-site compatibility.
   */
  onSublayerOpacityChange?: (sublayerId: string, opacity: number) => void;
  onSwapBasemap?: () => void;
  onResetBasemapAppearance?: () => void;
  /** Session-local basemap show/hide toggle (no backend change). */
  onToggleBasemapVisibility?: () => void;
  onRenameGroup?: (groupId: string, name: string) => void;
  onAddLayerToGroup?: (groupId: string) => void;
  onUngroup?: (groupId: string) => void;
  onDeleteGroup?: (groupId: string) => void;
  onAddLayerToExistingGroup?: (layerId: string, groupId: string) => void;
  onCreateGroupWithLayer?: (layerId: string) => void;
  onMoveLayerOutOfGroup?: (layerId: string) => void;
  existingFolderGroups?: Array<{ id: string; name: string }>;
  // Multi-selection props (lifted to MapBuilderPage)
  selectedIds?: Set<string>;
  isMultiSelectionActive?: boolean;
  selectableRowIds?: string[];
  /**
   * Controlled layer-search query. When provided (with onLayerSearchChange),
   * MapBuilderPage owns the query so it can derive selectableRowIds from the
   * RENDERED row set via computeSelectableRowIds: range selection must never
   * sweep rows the search has hidden. Omit both to keep the panel's internal
   * search state (standalone/test usage).
   */
  layerSearch?: string;
  onLayerSearchChange?: (query: string) => void;
  onCmdClick?: (id: string) => void;
  onShiftClick?: (id: string) => void;
  onCheckboxClick?: (id: string) => void;
  /** Called when outside-click or Escape should clear the multi-selection set */
  onClearSelection?: () => void;
  // Bulk action handlers. Required so a partial wiring at the call site fails
  // at compile time instead of silently unmounting the BulkActionBar at
  // runtime.
  onBulkVisibility: (ids: Set<string>) => void;
  onBulkOpacity: (ids: Set<string>, opacity: number) => void;
  onBulkGroup: (ids: Set<string>) => void;
  onBulkUngroup: (ids: Set<string>) => void;
  onBulkDelete: (ids: Set<string>) => void;
  /** Forwarded from useBuilderLayers.isDeleting */
  isDeleting?: boolean;
  /**
   * In-flight bulk-delete batch size, forwarded from
   * useBuilderLayers.deletingCount for the bar's "Deleting N layers…" label.
   */
  deletingCount?: number;
  // freshLayerId — id of most recently added layer for entry animation
  freshLayerId?: string | null;
  /**
   * Basemap position in the unified stack: 'top' renders the basemap row above
   * data layers, 'bottom' (default) below. Persisted via
   * MapBasemapConfig.basemap_position.
   */
  basemapPosition?: 'top' | 'bottom';
  /**
   * The live ephemeral preview, rendered as a non-persisting row pinned at the
   * top of the stack. Null/omitted when no preview is on the map. It is NOT a
   * layer: it never enters `layers` or `sortableIds` and carries no sort_order
   * (see the render site).
   */
  preview?: EphemeralPreviewRowProps | null;
}

interface SublayerRowProps {
  sublayer: BasemapSublayerInfo;
  selected: boolean;
  onSelectLayer: (id: string | null) => void;
  onToggleSublayerVisibility: (sublayerId: string) => void;
}

// SublayerRow doesn't consume onSublayerOpacityChange; the prop stays on
// UnifiedStackPanelProps for the LayerEditorPanel flyout consumers
// (BasemapGroupEditorScene, MapBuilderPage).
/* eslint-disable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex -- basemap sublayer rows are composite focus targets with nested controls, so role="button"/listbox roles are intentionally avoided. */
const SublayerRow = memo(function SublayerRow({
  sublayer,
  selected,
  onSelectLayer,
  onToggleSublayerVisibility,
}: SublayerRowProps) {
  const { t } = useTranslation('builder');
  // Basemap sublayers CANNOT be dragged out of the group — useSortable disabled
  const { setNodeRef } = useSortable({ id: sublayer.id, disabled: true });

  return (
    <div
      ref={setNodeRef}
      id={`stack-row-${sublayer.id}`}
      data-selected={selected ? 'true' : undefined}
      aria-current={selected ? 'true' : undefined}
      tabIndex={0}
      className={cn(
        'group/row grid grid-cols-[16px_14px_22px_22px_1fr_76px_22px] gap-2 items-center py-2 px-2 cursor-pointer select-none',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
        !selected && 'hover:bg-[var(--surface-2,theme(colors.accent.DEFAULT))]',
        selected && 'bg-primary-50 selection-inset',
      )}
      onClick={() => onSelectLayer(sublayer.id)}
      onKeyDown={(e) => {
        // WCAG 2.1.1: keys from the descendant eye toggle keep their native
        // button activation; the container only handles keys aimed at the row
        // itself. First-line is safe: the sublayer row has no
        // kebab/context-menu key handling.
        if (e.target !== e.currentTarget) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelectLayer(sublayer.id);
        }
      }}
    >
      {/* Cell 1: Caret — hidden for sublayer rows */}
      <span aria-hidden="true" style={{ visibility: 'hidden' }} className="text-xs" >▸</span>

      {/* Cell 2: Grip — visible but not-allowed cursor; no drag */}
      <span
        className="flex items-center justify-center cursor-not-allowed opacity-20 text-muted-foreground"
        aria-hidden="true"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <GripVertical className="h-3.5 w-3.5" />
      </span>

      {/* Cell 3: Eye visibility toggle (aria-pressed reflects state) */}
      <button
        type="button"
        aria-label={t('unifiedStack.toggleSublayerVisibility', {
          name: sublayer.name,
          defaultValue: 'Toggle visibility for {{name}}',
        })}
        aria-pressed={sublayer.visible}
        className="flex items-center justify-center h-[22px] w-[22px] rounded-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={(e) => {
          e.stopPropagation();
          onToggleSublayerVisibility(sublayer.id);
        }}
      >
        {sublayer.visible ? (
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
        )}
      </button>

      {/* Cell 4: Type icon — raster or vector */}
      <div className="flex items-center justify-center h-[22px] w-[22px]">
        {sublayer.kind === 'raster' ? (
          <span
            className="flex items-center justify-center h-[22px] w-[22px] rounded-sm bg-[--type-raster-bg] text-[--type-raster] text-xs font-semibold"
            aria-hidden="true"
          >
            ▦
          </span>
        ) : (
          <span
            className="flex items-center justify-center h-[22px] w-[22px] rounded-sm bg-[var(--surface-3,theme(colors.muted.DEFAULT))] text-muted-foreground text-xs font-semibold"
            aria-hidden="true"
          >
            ≡
          </span>
        )}
      </div>

      {/* Cell 5: Sublayer name */}
      <div className="min-w-0">
        <span className="truncate text-sm block">{sublayer.name}</span>
      </div>

      {/* Cell 6: intentionally empty; keeps the grid column. */}
      <div className="flex items-center" aria-hidden="true" />

      {/* Cell 7: Kebab — hidden for basemap sublayers */}
      <span aria-hidden="true" style={{ visibility: 'hidden' }} className="h-[22px] w-[22px]" />
    </div>
  );
});
/* eslint-enable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex */

// The layer stack is intentionally NOT virtualized. Real maps run well under
// ~100 layers, where a plain map() out-performs a windowed list (no scroll
// math, no measurement churn). Swap to a virtual list only if maps are observed
// to exceed ~100 layers.
export const UnifiedStackPanel = memo(function UnifiedStackPanel({
  layers,
  mapVisibility = 'private',
  drawsNothingLayerIds,
  selectedLayerId,
  onSelectLayer,
  onToggleVisibility,
  // onReorder / onOpacityChange / onSublayerOpacityChange are deliberately NOT
  // destructured: drag-reorder is lifted to MapBuilderPage and opacity editing
  // lives in the LayerEditorPanel flyout. The props stay on
  // UnifiedStackPanelProps for call-site compatibility and are inert here.
  onRemove,
  onRename,
  onDuplicate,
  onZoomToLayer,
  onAnalyzeLayer,
  onCopyStyle,
  onPasteStyle,
  onBulkApplyStyle,
  copiedStyleGeometryClass = null,
  onKeyboardReorder,
  onAnnounce,
  onAddDataClick,
  onAddDataset,
  onSettingsClick,
  isSettingsOpen = false,
  activeDragId = null,
  groupMeta = {},
  onToggleGroupExpand,
  basemapGroup = null,
  isBasemapExpanded = false,
  onToggleSublayerVisibility,
  onSwapBasemap,
  onResetBasemapAppearance,
  onToggleBasemapVisibility,
  onRenameGroup,
  onAddLayerToGroup,
  onUngroup,
  onDeleteGroup,
  onAddLayerToExistingGroup,
  onCreateGroupWithLayer,
  onMoveLayerOutOfGroup,
  existingFolderGroups = [],
  selectedIds = new Set(),
  isMultiSelectionActive = false,
  selectableRowIds = [],
  layerSearch: layerSearchProp,
  onLayerSearchChange,
  onCmdClick,
  onShiftClick,
  onCheckboxClick,
  onClearSelection,
  onBulkVisibility,
  onBulkOpacity,
  onBulkGroup,
  onBulkUngroup,
  onBulkDelete,
  isDeleting = false,
  deletingCount,
  freshLayerId = null,
  basemapPosition = 'bottom',
  preview = null,
}: UnifiedStackPanelProps) {
  const { t } = useTranslation('builder');

  // Search/filter state. An empty query shows all rows and preserves
  // drag/reorder. A non-empty query narrows to rows whose display name contains
  // the query (case-insensitive substring) and disables drag so reordering a
  // filtered subset can't corrupt sort_order. Hybrid controlled: when the
  // layerSearch prop is provided the parent owns the query (so it can derive
  // selectableRowIds from the rendered row set); internal state remains for
  // standalone usage.
  const [localLayerSearch, setLocalLayerSearch] = useState('');
  const layerSearch = layerSearchProp ?? localLayerSearch;
  const handleLayerSearchChange = (query: string) => {
    setLocalLayerSearch(query);
    onLayerSearchChange?.(query);
  };

  // Read the active drag item from the lifted DndContext so the DragOverlay can
  // branch between an intra-stack StackRow ghost and a catalog drag pill. This
  // is a second useDndContext call (the first lives in FolderGroupRowWrapper);
  // @dnd-kit supports multiple consumers.
  const { active } = useDndContext();

  // Ref for the scrollable stack panel element, used for the outside-click
  // guard and Shift+Arrow focus management.
  const stackPanelRef = useRef<HTMLDivElement>(null);

  // Outside-click clears selection. Guard: stackPanelRef.contains so row clicks
  // (handled by row onClick) are NOT cleared here.
  //
  // Also skip the clear when the click lands inside the BulkActionBar overflow
  // DropdownMenu: Radix portals that content out of the panel subtree, so a
  // menuitem click would otherwise clear the selection before its onSelect
  // handler reads it (unmounting the BulkActionBar via the `selectedIds.size >=
  // 2` gate before Delete's confirmation dialog can appear).
  //
  // Also skip it inside the BulkActionBar itself. stackPanelRef points to the
  // scroll region only; the bar is a sticky sibling below it. Without this
  // guard, mousedown on the inline "Delete N layers" confirm button clears
  // selection BEFORE the React click handler fires, so onBulkDelete sees an
  // empty Set and silently no-ops. The bar's own onPointerDown stopPropagation
  // does not help because document-level listeners fire in capture phase
  // regardless.
  //
  // The effect mounts only when selection is non-empty.
  useEffect(() => {
    if (selectedIds.size === 0) return;
    function handleMouseDown(e: MouseEvent) {
      const target = e.target as Node;
      if (stackPanelRef.current?.contains(target)) return;
      // Portal-rendered bulk-action overflow menu — treat as in-bounds.
      if ((target as Element | null)?.closest?.('[data-bulk-action-menu="true"]')) return;
      // BulkActionBar sticky footer (sibling of the scroll region) — treat as
      // in-bounds.
      if ((target as Element | null)?.closest?.('[data-bulk-action-bar="true"]')) return;
      onClearSelection?.();
    }
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [selectedIds.size, onClearSelection]);

  // Escape clears selection; Shift+ArrowUp/Down extends it. Both listeners are
  // scoped to the stack panel element so Escape pressed outside it (e.g. inside
  // a flyout input or a Radix dropdown) does NOT clear the selection.
  useEffect(() => {
    if (selectedIds.size === 0) return;
    const el = stackPanelRef.current;
    if (!el) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onClearSelection?.();
        return;
      }
      if (e.shiftKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
        const focused = document.activeElement as HTMLElement | null;
        if (!focused) return;
        // Walk up to find the element with data-row-id
        const rowEl = focused.closest<HTMLElement>('[data-row-id]');
        const focusedId = rowEl?.dataset?.rowId ?? null;
        if (!focusedId) return;
        // Derive adjacent index in selectable rows list
        const currentIdx = selectableRowIds.indexOf(focusedId);
        if (currentIdx < 0) return;
        const delta = e.key === 'ArrowDown' ? 1 : -1;
        const adjacentIdx = Math.max(0, Math.min(selectableRowIds.length - 1, currentIdx + delta));
        if (adjacentIdx === currentIdx) return; // clamped, no-op
        const adjacentId = selectableRowIds[adjacentIdx];
        if (!adjacentId) return;
        e.preventDefault();
        onShiftClick?.(adjacentId);
        const adjacentEl = stackPanelRef.current?.querySelector<HTMLElement>(`[data-row-id="${adjacentId}"]`);
        adjacentEl?.focus();
      }
    }
    el.addEventListener('keydown', handleKeyDown);
    return () => el.removeEventListener('keydown', handleKeyDown);
  }, [selectedIds.size, selectableRowIds, onClearSelection, onShiftClick]);

  // Terrain-mode (overlay-off) DEM rows stay in the stack. Hiding the row would
  // leave the DEM unmanageable once the editor closes (its only controls live
  // in the DEM editor this row opens) and let rebinding orphan invisible
  // render_mode:"terrain" layers. The map still paints nothing for them
  // (map-sync suppression); the row just stays reachable like any hidden layer.
  const visibleStackLayers = layers;

  // Per-layer "Copy N of M" disambiguation labels for the live stack rows, from
  // the same helper map-stack.ts uses for the derived/legend path so the two
  // badges can't drift. Computed over `layers` sorted by sort_order to match
  // the derived-stack occurrence numbering.
  const disambiguationLabels = useMemo(() => {
    const ordered = [...layers].sort((a, b) => a.sort_order - b.sort_order);
    return computeDisambiguationLabels(ordered, t);
  }, [layers, t]);

  // Per-layer audience-visibility mismatch: a private/unpublished dataset on a
  // public/shared map is silently filtered out server-side for other audiences.
  // Flag it on the stack row.
  const audienceHiddenLayerIds = useMemo(() => {
    const ids = new Set<string>();
    for (const layer of layers) {
      if (isLayerHiddenFromMapAudience(layer, mapVisibility)) ids.add(layer.id);
    }
    return ids;
  }, [layers, mapVisibility]);

  // SortableContext items: all layer ids plus the basemap-group id, so the user
  // can drag the basemap between 'top' and 'bottom'. Insert order matches the
  // render order: basemap first when basemap_position='top', last when
  // 'bottom'. handleDragEnd in MapBuilderPage detects basemap drags via the
  // special id and updates basemap_position on MapBasemapConfig instead of
  // mutating localLayers.
  const sortableIds = useMemo(() => {
    const layerIds: string[] = visibleStackLayers.map((l) => l.id);
    if (!basemapGroup) return layerIds;
    return basemapPosition === 'top'
      ? [basemapGroup.id, ...layerIds]
      : [...layerIds, basemapGroup.id];
  }, [visibleStackLayers, basemapGroup, basemapPosition]);

  // Build the render plan: group children by parent for O(N) pass
  const childrenByGroup = useMemo(() => {
    const map: Record<string, MapLayerResponse[]> = {};
    for (const layer of visibleStackLayers) {
      const parent = getParentGroupId(layer);
      if (parent) {
        (map[parent] ??= []).push(layer);
      }
    }
    return map;
  }, [visibleStackLayers]);

  // Noop fallbacks for optional handlers; the module-level NOOP keeps
  // references stable so memo() on children isn't defeated.
  const safeToggleSublayerVisibility = onToggleSublayerVisibility ?? NOOP;
  const safeSwapBasemap = onSwapBasemap ?? NOOP;
  const safeResetBasemapAppearance = onResetBasemapAppearance ?? NOOP;
  // Session-local basemap visibility toggle.
  const safeToggleBasemapVisibility = onToggleBasemapVisibility ?? NOOP;
  const safeRenameGroup = onRenameGroup ?? NOOP;
  const safeAddLayerToGroup = onAddLayerToGroup ?? NOOP;
  const safeUngroup = onUngroup ?? NOOP;
  const safeDeleteGroup = onDeleteGroup ?? NOOP;
  const safeAddLayerToExistingGroup = onAddLayerToExistingGroup ?? NOOP;
  const safeCreateGroupWithLayer = onCreateGroupWithLayer ?? NOOP;
  const safeMoveLayerOutOfGroup = onMoveLayerOutOfGroup ?? NOOP;
  const safeToggleGroupExpand = onToggleGroupExpand ?? NOOP;

  // Emptiness counts every layer: a map whose only layer is a terrain-mode DEM
  // has a manageable data row (its editor holds the terrain controls), so it
  // must not show the "add data" empty state.
  const isEmpty = visibleStackLayers.length === 0;

  // Whether a search query is active. When true, drag is disabled for all rows
  // so reordering a filtered subset can't corrupt sort_order. The count Badge
  // always shows the total, not the filtered count, since the filtered view is
  // transient.
  const isSearchActive = layerSearch.trim() !== '';

  // The row-skip decisions below use the SAME helper MapBuilderPage uses for
  // selectableRowIds, so what is rendered and what is range-selectable can't
  // drift (search matching, group collapse and child filtering all live in
  // computeSelectableRowIds).
  const renderedRowIds = useMemo(
    () => new Set(computeSelectableRowIds(visibleStackLayers, groupMeta, layerSearch)),
    [visibleStackLayers, groupMeta, layerSearch],
  );

  // A filter that matches nothing needs an explanation instead of a blank
  // panel. renderedRowIds covers DATA rows only (the basemap row is exempt from
  // filtering and always renders), so size === 0 while a search is active means
  // exactly "no layer matches"; the basemap row stays visible below the
  // message.
  const noSearchMatches = !isEmpty && isSearchActive && renderedRowIds.size === 0;

  // Basemap dock row, rendered in both empty and populated states. In the empty
  // state it sits below the EmptyStackState content with a "BASEMAP" eyebrow
  // label; in the populated state there is no eyebrow.
  function renderBasemapDockRow(showEyebrow: boolean) {
    if (!basemapGroup) return null;
    return (
      <div
        data-testid="basemap-dock"
        className={cn(showEyebrow && 'border-t border-[var(--border)]')}
      >
        {showEyebrow && (
          <span
            aria-hidden="true"
            className={cn(eyebrowClassName, 'px-3 pt-1 pb-0')}
          >
            {t('unifiedStack.basemapEyebrow', { defaultValue: 'BASEMAP' })}
          </span>
        )}
        <BasemapGroupRowWrapper
          key={`bm-${basemapGroup.id}`}
          group={basemapGroup}
          selected={basemapGroup.id === selectedLayerId}
          isExpanded={isBasemapExpanded}
          // Real toggle wired to the session-local basemap-visibility state in
          // MapBuilderPage.
          onSelectGroup={onSelectLayer}
          onToggleExpand={safeToggleGroupExpand}
          onToggleVisibility={safeToggleBasemapVisibility}
          onSwapBasemap={safeSwapBasemap}
          onResetAppearance={safeResetBasemapAppearance}
          isMultiSelectionActive={isMultiSelectionActive}
        />
        {isBasemapExpanded && (
          <div
            id={`basemap-group-children-${basemapGroup.id}`}
            data-testid={`basemap-group-children-${basemapGroup.id}`}
            className="ms-7 border-s border-dashed border-[var(--border)] ps-3"
            role="list"
            aria-label={t('unifiedStack.basemapSublayers')}
          >
            {basemapGroup.sublayers.map((sub) => (
              <SublayerRow
                key={sub.id}
                sublayer={sub}
                selected={sub.id === selectedLayerId}
                onSelectLayer={onSelectLayer}
                onToggleSublayerVisibility={safeToggleSublayerVisibility}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between gap-2 shrink-0"
        style={{ padding: '16px 16px 8px' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <h2 className="text-sm font-semibold">
            {t('unifiedStack.title', { defaultValue: 'Layers' })}
          </h2>
          {visibleStackLayers.length > 0 && (
            <Badge variant="secondary" className="px-2 text-xs font-semibold">
              {visibleStackLayers.length}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label={t('unifiedStack.settings', { defaultValue: 'Settings' })}
                aria-pressed={isSettingsOpen}
                data-testid="settings-cog-btn"
                className={cn(
                  'flex h-8 w-8 items-center justify-center rounded-sm transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  isSettingsOpen
                    ? 'bg-primary-50 text-primary'
                    : 'text-muted-foreground hover:bg-[var(--surface-2)] hover:text-foreground',
                )}
                onClick={onSettingsClick}
              >
                <Settings className="h-[18px] w-[18px]" aria-hidden="true" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {t('unifiedStack.settings', { defaultValue: 'Settings' })}
            </TooltipContent>
          </Tooltip>
          <Button
            variant="default"
            size="sm"
            className="h-8 gap-1 px-2 text-xs"
            onClick={() => onAddDataClick()}
          >
            {/* Lucide <Plus /> is the sole visual plus; the locale strings
                carry no literal full-width U+FF0B. */}
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t('unifiedStack.addData', { defaultValue: 'Add data' })}
          </Button>
        </div>
      </div>

      {/* Search/filter input, shown only when there are stack rows to filter. A
          non-empty query narrows by display_name / dataset_name
          (case-insensitive substring) and disables drag to prevent sort_order
          corruption. */}
      {!isEmpty && (
        <div className="shrink-0 px-3 pb-2 relative" data-testid="layer-search-container">
          <Search
            className="absolute start-5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none"
            aria-hidden="true"
          />
          <input
            type="search"
            data-testid="layer-search-input"
            aria-label={t('unifiedStack.searchAriaLabel', { defaultValue: 'Filter layers by name' })}
            placeholder={t('unifiedStack.searchPlaceholder', { defaultValue: 'Filter layers…' })}
            value={layerSearch}
            onChange={(e) => handleLayerSearchChange(e.target.value)}
            className={cn(
              'w-full h-7 rounded-sm border border-[var(--border)] bg-[var(--surface-1,var(--background))]',
              'ps-7 pe-2 text-xs text-foreground placeholder:text-muted-foreground',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            )}
          />
        </div>
      )}

      {/* Scrollable layer list or empty state */}
      {/* Rows are not role="listbox"/"option": each row contains focusable
          controls (drag handle, eye toggle, kebab menu), which breaks the
          WAI-ARIA listbox/option contract (axe: nested-interactive +
          aria-required-children). The container is a labelled scroll region;
          rows are plain divs with tabIndex=0 for keyboard nav and aria-current
          for selection state. */}
      <div
        ref={stackPanelRef}
        className="flex-1 overflow-y-auto"
        aria-label={t('unifiedStack.listboxLabel', { defaultValue: 'Map layers' })}
      >
        {/* The ephemeral preview, pinned at the very top: the overlay paints
            above every layer on the map, so any other position would have the
            stack lying about what covers what. Rendered HERE, before the
            SortableContext opens, so its id is structurally incapable of
            reaching `sortableIds` (a "non-draggable" flag on the sortable
            wrapper would still leave a collection member with no layer behind
            it for handleDragEnd to resolve). Also outside the isEmpty branch,
            so a preview on a map with no layers still has a dismiss affordance. */}
        {preview && <EphemeralPreviewRow {...preview} />}
        {isEmpty ? (
          <>
            <EmptyStackState
              onOpenAddData={(q) => onAddDataClick(q)}
              onAddDataset={onAddDataset ?? (() => {})}
            />
            {/* Basemap dock always visible; eyebrow label shown in empty state */}
            {renderBasemapDockRow(true)}
          </>
        ) : (
          <>
            {/* "No layers match" empty state, announced via role="status" so
                screen readers hear the result count change. */}
            {noSearchMatches && (
              <p
                data-testid="layer-search-no-matches"
                role="status"
                className="px-3 py-4 text-center text-xs text-muted-foreground"
              >
                {t('unifiedStack.searchNoMatches', {
                  query: layerSearch.trim(),
                  defaultValue: 'No layers match “{{query}}”',
                })}
              </p>
            )}
            <SortableContext
              items={sortableIds}
              strategy={verticalListSortingStrategy}
            >
              {/* 1. Basemap group: position controlled by basemapPosition.
                  'top' renders it FIRST (visually above all data layers);
                  'bottom' renders it LAST. Reordering happens via the drag
                  handle on the basemap row; persistence via
                  MapBasemapConfig.basemap_position. */}
              {basemapPosition === 'top' && renderBasemapDockRow(false)}

              {/* 2. User folder groups + loose layers (in saved order). */}
              {visibleStackLayers.map((layer) => {
                // Skip child rows — they render inside their group container
                if (getParentGroupId(layer)) return null;

                if (isFolderGroupLayer(layer)) {
                  // Folder group row with children container when expanded.
                  // Show the group if its own name
                  // matches the query OR any of its children match.
                  const expanded = groupMeta[layer.id]?.expanded ?? false;
                  const children = childrenByGroup[layer.id] ?? [];
                  // The skip decision comes from the shared
                  // rendered-row set so selection can never target a row the
                  // search has hidden.
                  if (!renderedRowIds.has(layer.id)) return null;

                  // The group eye reflects the children
                  // AGGREGATE (on while ANY child is visible) — the synthetic
                  // row's own `visible` merely mirrors whichever child was
                  // first at hydration and goes stale on per-child toggles.
                  const groupEyeLayer = children.length > 0
                    ? { ...layer, visible: children.some((c) => c.visible !== false) }
                    : layer;

                  return (
                    <div key={layer.id}>
                      <FolderGroupRowWrapper
                        layer={groupEyeLayer}
                        selected={layer.id === selectedLayerId}
                        isExpanded={expanded}
                        onSelectGroup={onSelectLayer}
                        onToggleExpand={safeToggleGroupExpand}
                        onToggleVisibility={onToggleVisibility}
                        onRenameGroup={safeRenameGroup}
                        onAddLayer={safeAddLayerToGroup}
                        onUngroup={safeUngroup}
                        onDeleteGroup={safeDeleteGroup}
                        isMultiSelected={selectedIds.has(layer.id)}
                        isMultiSelectionActive={isMultiSelectionActive}
                        onCmdClick={onCmdClick}
                        onShiftClick={onShiftClick}
                        onCheckboxClick={onCheckboxClick}
                        dragDisabled={isSearchActive}
                      />
                      {expanded && (
                        <div
                          id={`folder-group-children-${layer.id}`}
                          data-testid={`folder-group-children-${layer.id}`}
                          className="ms-7 border-s border-dashed border-[var(--border)] ps-3"
                          role="list"
                        >
                          {children.map((child) => {
                            // Child visibility under search comes
                            // from the shared rendered-row set (a group-name
                            // match still shows every child).
                            if (!renderedRowIds.has(child.id)) return null;
                            return (
                              <SortableStackRow
                                key={child.id}
                                layer={child}
                                selected={child.id === selectedLayerId}
                                onSelectLayer={onSelectLayer}
                                onToggleVisibility={onToggleVisibility}
                                onRemove={onRemove}
                                onRename={onRename}
                                onDuplicate={onDuplicate}
                                onZoomToLayer={onZoomToLayer}
                                onAnalyzeLayer={onAnalyzeLayer}
                                onCopyStyle={onCopyStyle}
                                onPasteStyle={onPasteStyle}
                                canPasteStyle={
                                  copiedStyleGeometryClass !== null &&
                                  copiedStyleGeometryClass === geometryClassOf(child.dataset_geometry_type)
                                }
                                onKeyboardReorder={onKeyboardReorder}
                                onAnnounce={onAnnounce}
                                existingFolderGroups={existingFolderGroups}
                                parentGroupId={layer.id}
                                onAddToGroup={safeAddLayerToExistingGroup}
                                onCreateGroupWithLayer={safeCreateGroupWithLayer}
                                onMoveLayerOutOfGroup={safeMoveLayerOutOfGroup}
                                isMultiSelected={selectedIds.has(child.id)}
                                isMultiSelectionActive={isMultiSelectionActive}
                                onCmdClick={onCmdClick}
                                onShiftClick={onShiftClick}
                                onCheckboxClick={onCheckboxClick}
                                isFresh={child.id === freshLayerId}
                                // Deleting or moving out a group's LAST child
                                // dissolves the named group (the empty-group
                                // prune); tell the row so its confirms can say
                                // so.
                                dissolvesGroupName={
                                  children.length === 1
                                    ? (layer.display_name ?? layer.dataset_name)
                                    : null
                                }
                                disambiguationLabel={disambiguationLabels.get(child.id) ?? null}
                                audienceHidden={audienceHiddenLayerIds.has(child.id)}
                                drawsNothing={drawsNothingLayerIds?.has(child.id) ?? false}
                                dragDisabled={isSearchActive}
                              />
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                }

                // Loose-row visibility under search comes from the
                // shared rendered-row set.
                if (!renderedRowIds.has(layer.id)) return null;

                // Loose layer
                return (
                  <SortableStackRow
                    key={layer.id}
                    layer={layer}
                    selected={layer.id === selectedLayerId}
                    onSelectLayer={onSelectLayer}
                    onToggleVisibility={onToggleVisibility}
                    onRemove={onRemove}
                    onRename={onRename}
                    onDuplicate={onDuplicate}
                    onZoomToLayer={onZoomToLayer}
                    onAnalyzeLayer={onAnalyzeLayer}
                    onCopyStyle={onCopyStyle}
                    onPasteStyle={onPasteStyle}
                    canPasteStyle={
                      copiedStyleGeometryClass !== null &&
                      copiedStyleGeometryClass === geometryClassOf(layer.dataset_geometry_type)
                    }
                    onKeyboardReorder={onKeyboardReorder}
                    onAnnounce={onAnnounce}
                    existingFolderGroups={existingFolderGroups}
                    parentGroupId={getParentGroupId(layer)}
                    onAddToGroup={safeAddLayerToExistingGroup}
                    onCreateGroupWithLayer={safeCreateGroupWithLayer}
                    onMoveLayerOutOfGroup={safeMoveLayerOutOfGroup}
                    isMultiSelected={selectedIds.has(layer.id)}
                    isMultiSelectionActive={isMultiSelectionActive}
                    onCmdClick={onCmdClick}
                    onShiftClick={onShiftClick}
                    onCheckboxClick={onCheckboxClick}
                    isFresh={layer.id === freshLayerId}
                    disambiguationLabel={disambiguationLabels.get(layer.id) ?? null}
                    audienceHidden={audienceHiddenLayerIds.has(layer.id)}
                    drawsNothing={drawsNothingLayerIds?.has(layer.id) ?? false}
                    dragDisabled={isSearchActive}
                  />
                );
              })}

              {/* 3. Basemap group at BOTTOM when basemapPosition='bottom'. */}
              {basemapPosition === 'bottom' && renderBasemapDockRow(false)}
            </SortableContext>
            {/* DragOverlay: ghost follows pointer during drag */}
            {/* Branched — catalog drags render CatalogDragGhost pill;
                intra-stack drags render the existing StackRow ghost. */}
            <DragOverlay dropAnimation={null}>
              {(() => {
                // Read catalog data from the active drag item via useDndContext
                const catalogData = active?.data?.current as
                  | { source?: string; recordType?: string; name?: string }
                  | undefined;

                if (catalogData?.source === 'catalog') {
                  // Catalog drag: compact pill ghost
                  return (
                    <CatalogDragGhost
                      recordType={catalogData.recordType ?? 'vector_dataset'}
                      name={catalogData.name ?? ''}
                    />
                  );
                }

                // Intra-stack drag: existing StackRow ghost
                if (!activeDragId) return null;
                const activeLayer = layers.find((l) => l.id === activeDragId);
                return activeLayer ? (
                  <div className="opacity-40 scale-[0.98] pointer-events-none bg-[var(--surface-2)] rounded-sm shadow-md">
                    <StackRow
                      layer={activeLayer}
                      selected={false}
                      isDragging={true}
                      dragHandleProps={{ attributes: {} as DraggableAttributes, listeners: undefined, setActivatorNodeRef: NOOP }}
                      onSelectLayer={NOOP}
                      onToggleVisibility={NOOP}
                      onRemove={NOOP}
                      onRename={NOOP}
                      onDuplicate={NOOP}
                    />
                  </div>
                ) : null;
              })()}
            </DragOverlay>
          </>
        )}
      </div>

      {/* BulkActionBar: sticky footer, visible only when 2+ rows are selected
          and hidden while the global Settings scene is open. Selection persists
          in the parent (selectedIds), so the bar reappears unchanged when
          Settings closes. */}
      {/* Handler props are required (see interface above), so TypeScript
          enforces that the call site wires all five handlers. */}
      {!isSettingsOpen && selectedIds.size >= 2 && (
        <BulkActionBar
          selectedIds={selectedIds}
          layers={layers}
          onBulkVisibility={onBulkVisibility}
          onBulkOpacity={onBulkOpacity}
          onBulkGroup={onBulkGroup}
          onBulkUngroup={onBulkUngroup}
          onBulkDelete={onBulkDelete}
          onBulkApplyStyle={onBulkApplyStyle}
          isDeleting={isDeleting}
          deletingCount={deletingCount}
        />
      )}
    </div>
  );
});
