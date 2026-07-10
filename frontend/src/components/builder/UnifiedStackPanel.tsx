import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
// builder-audit #338 STACK-05: sortable wrappers + the catalog drag ghost moved to
// sibling files so this panel module stays focused on the list orchestration.
import { SortableStackRow } from '@/components/builder/SortableStackRow';
import { BasemapGroupRowWrapper } from '@/components/builder/BasemapGroupRowWrapper';
import { FolderGroupRowWrapper } from '@/components/builder/FolderGroupRowWrapper';
import { CatalogDragGhost } from '@/components/builder/CatalogDragGhost';
import { EmptyStackState, eyebrowClassName } from '@/components/builder/EmptyStackState';
import { BulkActionBar } from '@/components/builder/BulkActionBar';
// builder-audit #338 STACK-01: use the single typed helper instead of a local
// `as unknown as` re-implementation.
import { getParentGroupId } from '@/components/builder/folder-groups';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { cn } from '@/lib/utils';
import type { MapLayerResponse } from '@/types/api';
import type { BasemapGroupInfo, BasemapSublayerInfo } from '@/components/builder/stack-types';
import { isDemTerrainVisualSuppressed } from './map-sync';
import { computeDisambiguationLabels, isLayerHiddenFromMapAudience } from './map-stack';
import { geometryClassOf, type GeometryStyleClass } from '@/lib/builder/layer-style-clipboard';

// builder-audit #338 STACK-05: re-exported so existing imports
// (`import { CatalogDragGhost } from '@/components/builder/UnifiedStackPanel'`)
// keep working after the component moved to its own file.
export { CatalogDragGhost };

// ---------------------------------------------------------------------------
// Stable noop — created once at module scope so optional-prop fallbacks never
// produce new function references on each render, which would defeat memo() on
// children (BasemapGroupRowWrapper, FolderGroupRowWrapper, SortableStackRow).
// ---------------------------------------------------------------------------
const NOOP = () => {};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface UnifiedStackPanelProps {
  layers: MapLayerResponse[];
  /**
   * fix(#430 V-17): the map's own visibility, used to compute per-layer
   * audience-hidden badges (a private dataset added to a public/shared map is
   * silently filtered out for anonymous/other-audience viewers). Optional so
   * existing call sites (and tests) that don't care about this warning keep
   * compiling; a private default means "no audience beyond the owner" — the
   * safest no-warning default.
   */
  mapVisibility?: 'private' | 'internal' | 'public';
  selectedLayerId: string | null;
  onSelectLayer: (id: string | null) => void;
  onToggleVisibility: (id: string) => void;
  /** @deprecated builder-audit #338 STACK-05: inert in this component (drag-reorder is
   *  lifted to MapBuilderPage). Retained only for call-site compatibility. */
  onReorder: (layers: MapLayerResponse[]) => void;
  /** @deprecated builder-audit #338 STACK-05: inert in this component (opacity editing
   *  moved to the LayerEditorPanel flyout). Retained only for call-site compatibility. */
  onOpacityChange: (layerId: string, opacity: number) => void;
  onRemove: (id: string) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onDuplicate: (id: string) => void;
  // Phase 1201-01 (ENH-01/ENH-02/ENH-03): authoring actions threaded to the kebab
  // + bulk bar.
  onZoomToLayer?: (id: string) => void;
  onCopyStyle?: (id: string) => void;
  onPasteStyle?: (id: string) => void;
  onBulkApplyStyle?: (ids: Set<string>) => void;
  /** Geometry class of the currently-copied style (null = nothing copied). Used
   *  to enable "Paste style" only on geometry-compatible rows. */
  copiedStyleGeometryClass?: GeometryStyleClass | null;
  onKeyboardReorder?: (layerId: string, direction: 'up' | 'down') => void;
  onAddDataClick: (initialQuery?: string) => void;
  onAddDataset?: (datasetId: string) => void;
  onSettingsClick: () => void;
  isSettingsOpen?: boolean;
  /** Phase 1040: id of the item currently being dragged (from the lifted drag context in MapBuilderPage) */
  activeDragId?: string | null;
  // Phase 1035 new props
  groupMeta?: Record<string, { expanded: boolean }>;
  onToggleGroupExpand?: (groupId: string) => void;
  basemapGroup?: BasemapGroupInfo | null;
  isBasemapExpanded?: boolean;
  onToggleSublayerVisibility?: (sublayerId: string) => void;
  /** @deprecated builder-audit #338 STACK-05: inert in this component (per-sublayer
   *  opacity moved to the LayerEditorPanel flyout). Retained for call-site compatibility. */
  onSublayerOpacityChange?: (sublayerId: string, opacity: number) => void;
  onSwapBasemap?: () => void;
  onResetBasemapAppearance?: () => void;
  /** Phase 1199 STACK-02: session-local basemap show/hide toggle (no backend change). */
  onToggleBasemapVisibility?: () => void;
  onRenameGroup?: (groupId: string, name: string) => void;
  onAddLayerToGroup?: (groupId: string) => void;
  onUngroup?: (groupId: string) => void;
  onDeleteGroup?: (groupId: string) => void;
  onAddLayerToExistingGroup?: (layerId: string, groupId: string) => void;
  onCreateGroupWithLayer?: (layerId: string) => void;
  onMoveLayerOutOfGroup?: (layerId: string) => void;
  existingFolderGroups?: Array<{ id: string; name: string }>;
  // Phase 1041: multi-selection props (lifted to MapBuilderPage — see decision in SUMMARY)
  selectedIds?: Set<string>;
  isMultiSelectionActive?: boolean;
  selectableRowIds?: string[];
  onCmdClick?: (id: string) => void;
  onShiftClick?: (id: string) => void;
  onCheckboxClick?: (id: string) => void;
  /** Called when outside-click or Escape should clear the multi-selection set */
  onClearSelection?: () => void;
  // Phase 1041-02: bulk action handlers (no-op stubs in MapBuilderPage until Plan 03 wires real ops)
  // Phase 1051 WR-02: required so a partial wiring at the call site fails at
  // compile-time instead of silently unmounting the BulkActionBar at runtime.
  onBulkVisibility: (ids: Set<string>) => void;
  onBulkOpacity: (ids: Set<string>, opacity: number) => void;
  onBulkGroup: (ids: Set<string>) => void;
  onBulkUngroup: (ids: Set<string>) => void;
  onBulkDelete: (ids: Set<string>) => void;
  /** Phase 1047-04 (PERF-03): forwarded from useBuilderLayers.isDeleting */
  isDeleting?: boolean;
  // Phase 1042 POL-15: freshLayerId — id of most recently added layer for entry animation
  freshLayerId?: string | null;
  /** Phase 1051 UX-03: basemap position in the unified stack. 'top' renders
   *  basemap row above data layers; 'bottom' (default) renders below. Persisted
   *  via MapBasemapConfig.basemap_position. */
  basemapPosition?: 'top' | 'bottom';
}

// ---------------------------------------------------------------------------
// builder-audit #338 STACK-05: SortableStackRow, BasemapGroupRowWrapper, and
// FolderGroupRowWrapper were extracted to sibling files (imported above).
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// SublayerRow — basemap sublayer row (useSortable disabled — cannot be dragged)
// ---------------------------------------------------------------------------

interface SublayerRowProps {
  sublayer: BasemapSublayerInfo;
  selected: boolean;
  onSelectLayer: (id: string | null) => void;
  onToggleSublayerVisibility: (sublayerId: string) => void;
}

// Phase 1051 UX-02: per-row opacity slider removed in favour of
// SublayerConfigIndicators. Opacity editing now lives exclusively in the
// LayerEditorPanel flyout (BasemapSublayerEditorScene opacity slider).
// Cell 6 grid column kept at 76px (was 60px) to fit up to 4 × 16px badges
// + 3 × 4px gaps without truncation. SublayerRow no longer consumes
// onSublayerOpacityChange — the prop survives on UnifiedStackPanelProps for
// the LayerEditorPanel flyout consumer (BasemapGroupEditorScene + MapBuilderPage).
/* eslint-disable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex -- Phase 1111 LINT-01: basemap sublayer rows are composite focus targets with nested controls, so role="button"/listbox roles are intentionally avoided. */
const SublayerRow = memo(function SublayerRow({
  sublayer,
  selected,
  onSelectLayer,
  onToggleSublayerVisibility,
}: SublayerRowProps) {
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
        selected && 'bg-[var(--primary-50,theme(colors.accent.DEFAULT))] shadow-[inset_2px_0_0_var(--primary)]',
      )}
      onClick={() => onSelectLayer(sublayer.id)}
      onKeyDown={(e) => {
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

      {/* Cell 3: Eye visibility toggle (SP-10: aria-pressed reflects state) */}
      <button
        type="button"
        aria-label={`Toggle visibility for ${sublayer.name}`}
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

      {/* Cell 6: Config-state indicators slot (Phase 1051 UX-02 — replaces opacity slider).
          builder-audit #338 DEAD-02: SublayerConfigIndicators was always rendered with
          layer={null} here (BasemapSublayerInfo only carries id/name/visible/opacity/kind,
          not the full MapLayerResponse the indicators derive from), so its entire logic was
          unreachable in production. The always-null render is removed; this slot stays empty.
          Deferred enhancement: plumb the full layer through and re-add the indicator strip
          once basemap sublayers gain user-editable filter/label config — see
          SublayerConfigIndicators.tsx. */}
      <div className="flex items-center" aria-hidden="true" />

      {/* Cell 7: Kebab — hidden for basemap sublayers (per UI-SPEC) */}
      <span aria-hidden="true" style={{ visibility: 'hidden' }} className="h-[22px] w-[22px]" />
    </div>
  );
});
/* eslint-enable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex */

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export const UnifiedStackPanel = memo(function UnifiedStackPanel({
  layers,
  mapVisibility = 'private',
  selectedLayerId,
  onSelectLayer,
  onToggleVisibility,
  // builder-audit #338 STACK-05: onReorder / onOpacityChange / onSublayerOpacityChange
  // are deliberately NOT destructured here — drag-reorder is lifted to
  // MapBuilderPage and all opacity editing moved to the LayerEditorPanel flyout.
  // The props remain on UnifiedStackPanelProps only for call-site compatibility
  // (MapBuilderPage still passes them through to other scenes); they are inert in
  // this component.
  onRemove,
  onRename,
  onDuplicate,
  onZoomToLayer,
  onCopyStyle,
  onPasteStyle,
  onBulkApplyStyle,
  copiedStyleGeometryClass = null,
  onKeyboardReorder,
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
  freshLayerId = null,
  basemapPosition = 'bottom',
}: UnifiedStackPanelProps) {
  const { t } = useTranslation('builder');

  // Phase 1201-02 (ENH-07): search/filter state. An empty query shows all rows
  // and preserves drag/reorder. A non-empty query narrows visible rows to those
  // whose display name contains the query (case-insensitive substring) and
  // disables drag so reordering a filtered subset cannot corrupt sort_order.
  const [layerSearch, setLayerSearch] = useState('');

  // Phase 1040 Plan 04: read the active drag item from the lifted DndContext so the
  // DragOverlay can branch between an intra-stack StackRow ghost and a catalog drag pill.
  // This is a second call to useDndContext — the first lives inside FolderGroupRowWrapper.
  // Both coexist safely; @dnd-kit supports multiple consumers of the same context.
  const { active } = useDndContext();

  // Phase 1041: ref for the scrollable stack panel element — used for outside-click guard
  // and Shift+Arrow focus management. (Phase 1052: was the listbox; now a labelled scroll
  // region after listbox/option pattern was dropped per axe nested-interactive.)
  const stackPanelRef = useRef<HTMLDivElement>(null);

  // Phase 1041 POL-10: outside-click clears selection.
  // Guard: stackPanelRef.contains so row clicks (handled by row onClick) are
  // NOT cleared here.
  //
  // SP-01 (Phase 1045): also skip the clear when the click lands inside the
  // BulkActionBar overflow DropdownMenu — Radix portals that content out of
  // the panel subtree, so without this guard a menuitem click would clear
  // the selection before the click's onSelect handler reads it (which would
  // unmount the BulkActionBar via the `selectedIds.size >= 2` gate before
  // Delete's confirmation dialog can appear).
  //
  // SF-01 (Phase 1049): also skip the clear when the click lands inside the
  // BulkActionBar itself. stackPanelRef points to the inner listbox only; the
  // BulkActionBar is rendered as a sticky sibling below it. Without this guard,
  // mousedown on the inline "Delete N layers" confirm button clears selection
  // BEFORE the React click handler fires, so onBulkDelete sees an empty Set
  // and silently no-ops (bulk-delete completely broken in the UI). The bar's
  // own onPointerDown stopPropagation does NOT help because document-level
  // listeners fire in capture phase regardless.
  //
  // Effect mounts only when selection is non-empty (keyed on size > 0 via early-return).
  useEffect(() => {
    if (selectedIds.size === 0) return;
    function handleMouseDown(e: MouseEvent) {
      const target = e.target as Node;
      if (stackPanelRef.current?.contains(target)) return;
      // Portal-rendered bulk-action overflow menu — treat as in-bounds.
      if ((target as Element | null)?.closest?.('[data-bulk-action-menu="true"]')) return;
      // BulkActionBar sticky footer (sibling of the listbox) — treat as in-bounds.
      if ((target as Element | null)?.closest?.('[data-bulk-action-bar="true"]')) return;
      onClearSelection?.();
    }
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [selectedIds.size, onClearSelection]);

  // Phase 1041 POL-10 + POL-06: Escape clears selection; Shift+ArrowUp/Down extends selection.
  // Both listeners are scoped to the stack panel element (stackPanelRef) so that Escape
  // pressed outside the panel (e.g. inside a flyout input or a Radix dropdown) does NOT
  // clear the selection. Only keyboard events that bubble up through the listbox div fire.
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
        // Find the currently focused row's id via data-row-id attribute
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
        // Move DOM focus to the adjacent row
        const adjacentEl = stackPanelRef.current?.querySelector<HTMLElement>(`[data-row-id="${adjacentId}"]`);
        adjacentEl?.focus();
      }
    }
    el.addEventListener('keydown', handleKeyDown);
    return () => el.removeEventListener('keydown', handleKeyDown);
  }, [selectedIds.size, selectableRowIds, onClearSelection, onShiftClick]);

  // Filter out terrain-mode DEM layers from the stack UI — the map-sync layer
  // render already suppresses them (map-sync.ts:1014); this aligns the stack
  // display with what the map actually renders. Reorder/bulk/drag paths still
  // see the full `layers` prop so their persistence logic is unaffected.
  const visibleStackLayers = useMemo(
    () => layers.filter((l) => !isDemTerrainVisualSuppressed(l)),
    [layers],
  );

  // Phase 1199 STACK-01: per-layer "Copy N of M" disambiguation labels for the
  // LIVE stack rows. map-stack.ts already computes these for the derived/legend
  // path; this reuses the same exported helper so the live badge and the legend
  // badge can never drift. Computed over the full `layers` set (sorted by
  // sort_order to match the derived-stack occurrence numbering), not just
  // visibleStackLayers, so a duplicate hidden behind a suppressed terrain row is
  // still counted consistently.
  const disambiguationLabels = useMemo(() => {
    const ordered = [...layers].sort((a, b) => a.sort_order - b.sort_order);
    return computeDisambiguationLabels(ordered);
  }, [layers]);

  // fix(#430 V-17): per-layer audience-visibility mismatch — a private/unpublished
  // dataset added to a public/shared map is silently filtered out for
  // anonymous/other-audience viewers server-side. Flag it on the stack row.
  const audienceHiddenLayerIds = useMemo(() => {
    const ids = new Set<string>();
    for (const layer of layers) {
      if (isLayerHiddenFromMapAudience(layer, mapVisibility)) ids.add(layer.id);
    }
    return ids;
  }, [layers, mapVisibility]);

  // SortableContext items: all layer ids + the basemap-group id.
  // UX-03 (Phase 1051 Plan 06): basemap is no longer excluded — it participates
  // in the sortable list so the user can drag it between 'top' and 'bottom'
  // positions. Insert order matches the render order: basemap at position 0 when
  // basemap_position='top' (renders first), at end when 'bottom' (renders last).
  // handleDragEnd in MapBuilderPage detects basemap drags via the special id and
  // updates basemap_position on MapBasemapConfig instead of mutating localLayers.
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

  // Noop fallbacks for optional handlers — use module-level NOOP so references
  // are stable and do not defeat memo() on children.
  const safeToggleSublayerVisibility = onToggleSublayerVisibility ?? NOOP;
  // safeSublayerOpacityChange removed — Phase 1051 UX-02 (see destructure comment above).
  const safeSwapBasemap = onSwapBasemap ?? NOOP;
  const safeResetBasemapAppearance = onResetBasemapAppearance ?? NOOP;
  // Phase 1199 STACK-02: session-local basemap visibility toggle.
  const safeToggleBasemapVisibility = onToggleBasemapVisibility ?? NOOP;
  const safeRenameGroup = onRenameGroup ?? NOOP;
  const safeAddLayerToGroup = onAddLayerToGroup ?? NOOP;
  const safeUngroup = onUngroup ?? NOOP;
  const safeDeleteGroup = onDeleteGroup ?? NOOP;
  const safeAddLayerToExistingGroup = onAddLayerToExistingGroup ?? NOOP;
  const safeCreateGroupWithLayer = onCreateGroupWithLayer ?? NOOP;
  const safeMoveLayerOutOfGroup = onMoveLayerOutOfGroup ?? NOOP;
  const safeToggleGroupExpand = onToggleGroupExpand ?? NOOP;

  // BLDR-03: emptiness is measured over visibleStackLayers (terrain-mode DEM
  // rows are suppressed because terrain is a map-level setting, not a data row).
  // A map whose only layer is a terrain-mode DEM therefore intentionally shows
  // the "add data" empty state — there are no data layers to manage in the stack;
  // terrain is configured via the map-level terrain controls.
  const isEmpty = visibleStackLayers.length === 0;

  // Phase 1201-02 (ENH-07): whether a search query is currently active.
  // When true, drag is disabled for all rows so reordering a filtered subset
  // cannot corrupt sort_order. The count Badge always reflects the total (not
  // the filtered count) to avoid confusion — the filtered view is transient.
  const isSearchActive = layerSearch.trim() !== '';

  // Case-insensitive substring match on display_name falling back to dataset_name.
  // An empty (or whitespace-only) query always returns true.
  const matchesSearch = useCallback(
    (layer: MapLayerResponse): boolean => {
      const q = layerSearch.trim();
      if (q === '') return true;
      const name = (layer.display_name ?? layer.dataset_name ?? '').toLowerCase();
      return name.includes(q.toLowerCase());
    },
    [layerSearch],
  );

  // ---------------------------------------------------------------------------
  // Basemap dock row — rendered in both empty and populated states.
  // In empty state it sits below the EmptyStackState content with a "BASEMAP"
  // eyebrow label for disambiguation. In populated state no eyebrow is shown.
  // ---------------------------------------------------------------------------
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
          // Phase 1199 STACK-02: the eye is a real, enabled toggle wired to the
          // session-local basemap-visibility state in MapBuilderPage. (builder-audit
          // STACK-06 removed the dead visibilityDisabled locked-eye branch.)
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
            style={{ marginLeft: '28px', paddingLeft: '12px', borderLeft: '1px dashed var(--border)' }}
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
            <Badge variant="secondary" className="rounded-full px-2 text-xs font-semibold">
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
                    ? 'bg-[var(--primary-50,oklch(0.97_0.02_250))] text-primary'
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
            {/* SP-17: Lucide <Plus /> replaces the full-width U+FF0B character that
                lived inside the i18n default. The literal "＋" has been stripped
                from the locale strings; the icon is the sole visual plus. */}
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t('unifiedStack.addData', { defaultValue: 'Add data' })}
          </Button>
        </div>
      </div>

      {/* Phase 1201-02 (ENH-07): search/filter input — shown only when there are
          stack rows to filter. Empty query shows all rows; non-empty narrows by
          display_name / dataset_name (case-insensitive substring). Drag is
          disabled while a query is active to prevent sort_order corruption. */}
      {!isEmpty && (
        <div className="shrink-0 px-3 pb-2 relative" data-testid="layer-search-container">
          <Search
            className="absolute left-5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none"
            aria-hidden="true"
          />
          <input
            type="search"
            data-testid="layer-search-input"
            aria-label={t('unifiedStack.searchAriaLabel', { defaultValue: 'Filter layers by name' })}
            placeholder={t('unifiedStack.searchPlaceholder', { defaultValue: 'Filter layers…' })}
            value={layerSearch}
            onChange={(e) => setLayerSearch(e.target.value)}
            className={cn(
              'w-full h-7 rounded-sm border border-[var(--border)] bg-[var(--surface-1,var(--background))]',
              'pl-7 pr-2 text-xs text-foreground placeholder:text-muted-foreground',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            )}
          />
        </div>
      )}

      {/* Scrollable layer list or empty state */}
      {/* Phase 1052: dropped role="listbox" + role="option" from rows — they don't
          match the WAI-ARIA listbox/option contract because each row contains
          focusable controls (drag handle, eye toggle, kebab menu). axe flags
          this as nested-interactive + aria-required-children. Container is now
          a labelled scroll region; rows are plain divs with tabIndex=0 for
          keyboard nav + aria-current for selection state. */}
      <div
        ref={stackPanelRef}
        className="flex-1 overflow-y-auto"
        aria-label={t('unifiedStack.listboxLabel', { defaultValue: 'Map layers' })}
      >
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
            <SortableContext
              items={sortableIds}
              strategy={verticalListSortingStrategy}
            >
              {/* 1. Basemap group — UX-03: position controlled by basemapPosition.
                  When 'top' (default historically 'bottom' was hard-coded), the
                  basemap row renders FIRST (visually above all data layers in
                  the stack); when 'bottom', it renders LAST (below all data
                  layers). Reordering happens via the drag handle on the basemap
                  row; persistence via MapBasemapConfig.basemap_position. */}
              {basemapPosition === 'top' && renderBasemapDockRow(false)}

              {/* 2. User folder groups + loose layers (in saved order).
                  Terrain-mode DEM layers are excluded via visibleStackLayers so
                  the stack agrees with the map's existing render suppression
                  (map-sync.ts:919). The raw `layers` prop is still forwarded to
                  BulkActionBar and used for drag-overlay lookup so those paths
                  see the full layer set. */}
              {visibleStackLayers.map((layer) => {
                // Skip child rows — they render inside their group container
                if (getParentGroupId(layer)) return null;

                if (isFolderGroupLayer(layer)) {
                  // Folder group row with children container when expanded.
                  // Phase 1201-02 (ENH-07): show the group if its own name
                  // matches the query OR any of its children match.
                  const expanded = groupMeta[layer.id]?.expanded ?? false;
                  const children = childrenByGroup[layer.id] ?? [];
                  const groupNameMatches = matchesSearch(layer);
                  const anyChildMatches = children.some((c) => matchesSearch(c));
                  if (isSearchActive && !groupNameMatches && !anyChildMatches) return null;

                  // fix(#394) LM-04: the group eye reflects the children
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
                          style={{ marginLeft: '28px', paddingLeft: '12px', borderLeft: '1px dashed var(--border)' }}
                          role="list"
                        >
                          {children.map((child) => {
                            // Phase 1201-02: when the group itself matches, show all
                            // its children; otherwise filter children by name.
                            if (isSearchActive && !groupNameMatches && !matchesSearch(child)) return null;
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
                                onCopyStyle={onCopyStyle}
                                onPasteStyle={onPasteStyle}
                                canPasteStyle={
                                  copiedStyleGeometryClass !== null &&
                                  copiedStyleGeometryClass === geometryClassOf(child.dataset_geometry_type)
                                }
                                onKeyboardReorder={onKeyboardReorder}
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
                                disambiguationLabel={disambiguationLabels.get(child.id) ?? null}
                                audienceHidden={audienceHiddenLayerIds.has(child.id)}
                                dragDisabled={isSearchActive}
                              />
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                }

                // Phase 1201-02 (ENH-07): skip loose layers that don't match the query.
                if (isSearchActive && !matchesSearch(layer)) return null;

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
                    onCopyStyle={onCopyStyle}
                    onPasteStyle={onPasteStyle}
                    canPasteStyle={
                      copiedStyleGeometryClass !== null &&
                      copiedStyleGeometryClass === geometryClassOf(layer.dataset_geometry_type)
                    }
                    onKeyboardReorder={onKeyboardReorder}
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
                    dragDisabled={isSearchActive}
                  />
                );
              })}

              {/* 3. Basemap group at BOTTOM when basemapPosition='bottom'
                  (default + legacy behaviour). */}
              {basemapPosition === 'bottom' && renderBasemapDockRow(false)}
            </SortableContext>
            {/* DragOverlay: ghost follows pointer during drag (BSR-24 VIS-01) */}
            {/* Plan 04: branched — catalog drags render CatalogDragGhost pill;
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

      {/* Phase 1041-02: BulkActionBar — sticky footer, visible only when 2+ rows selected.
          SP-15: also hide when the global Settings scene is open. Selection state persists
          in the parent (selectedIds), so when Settings closes the bar reappears unchanged. */}
      {/* Phase 1051 WR-02: handler props are now required (see interface above),
          so the runtime presence checks have been dropped — TypeScript enforces
          that the call site wires all five handlers. */}
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
        />
      )}
    </div>
  );
});
