import { memo, useCallback, useEffect, useMemo, useRef } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  DragOverlay,
  useDndContext,
  useDroppable,
} from '@dnd-kit/core';
import type { DraggableAttributes } from '@dnd-kit/core';
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, GripVertical, Plus, Settings } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { StackRow } from '@/components/builder/StackRow';
import { BasemapGroupRow } from '@/components/builder/BasemapGroupRow';
import { FolderGroupRow } from '@/components/builder/FolderGroupRow';
import { EmptyStackState, eyebrowClassName } from '@/components/builder/EmptyStackState';
import { BulkActionBar } from '@/components/builder/BulkActionBar';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { cn } from '@/lib/utils';
import type { MapLayerResponse } from '@/types/api';

// ---------------------------------------------------------------------------
// Stable noop — created once at module scope so optional-prop fallbacks never
// produce new function references on each render, which would defeat memo() on
// children (BasemapGroupRowWrapper, FolderGroupRowWrapper, SortableStackRow).
// ---------------------------------------------------------------------------
const NOOP = () => {};

// ---------------------------------------------------------------------------
// Helper utilities
// ---------------------------------------------------------------------------

function getParentGroupId(layer: MapLayerResponse): string | null {
  // In-memory `parent_group_id` set by use-builder-layers folder handlers
  return (layer as unknown as { parent_group_id?: string | null }).parent_group_id ?? null;
}

// ---------------------------------------------------------------------------
// Sub-interfaces
// ---------------------------------------------------------------------------

interface BasemapSublayerInfo {
  id: string;
  name: string;
  visible: boolean;
  opacity: number;
  kind: 'vector' | 'raster';
}

interface BasemapGroupInfo {
  id: string;
  presetName: string;
  providerLabel?: string;
  visible: boolean;
  opacity: number;
  sublayers: BasemapSublayerInfo[];
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface UnifiedStackPanelProps {
  layers: MapLayerResponse[];
  selectedLayerId: string | null;
  onSelectLayer: (id: string | null) => void;
  onToggleVisibility: (id: string) => void;
  onReorder: (layers: MapLayerResponse[]) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onRemove: (id: string) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onDuplicate: (id: string) => void;
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
  onSublayerOpacityChange?: (sublayerId: string, opacity: number) => void;
  onSwapBasemap?: () => void;
  onResetBasemapAppearance?: () => void;
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
  onBulkVisibility?: (ids: Set<string>) => void;
  onBulkOpacity?: (ids: Set<string>, opacity: number) => void;
  onBulkGroup?: (ids: Set<string>) => void;
  onBulkUngroup?: (ids: Set<string>) => void;
  onBulkDelete?: (ids: Set<string>) => void;
  // Phase 1042 POL-15: freshLayerId — id of most recently added layer for entry animation
  freshLayerId?: string | null;
}

// ---------------------------------------------------------------------------
// SortableStackRow — loose layer or folder-group child row
// ---------------------------------------------------------------------------

interface SortableStackRowProps {
  layer: MapLayerResponse;
  selected: boolean;
  onSelectLayer: (id: string | null) => void;
  onToggleVisibility: (id: string) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onRemove: (id: string) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onDuplicate: (id: string) => void;
  existingFolderGroups?: Array<{ id: string; name: string }>;
  parentGroupId?: string | null;
  onAddToGroup?: (layerId: string, groupId: string) => void;
  onCreateGroupWithLayer?: (layerId: string) => void;
  onMoveLayerOutOfGroup?: (layerId: string) => void;
  // Phase 1041: multi-selection
  isMultiSelected?: boolean;
  isMultiSelectionActive?: boolean;
  onCmdClick?: (id: string) => void;
  onShiftClick?: (id: string) => void;
  onCheckboxClick?: (id: string) => void;
  // Phase 1042 POL-15: entry animation
  isFresh?: boolean;
}

const SortableStackRow = memo(function SortableStackRow({
  layer,
  selected,
  onSelectLayer,
  onToggleVisibility,
  onOpacityChange,
  onRemove,
  onRename,
  onDuplicate,
  existingFolderGroups,
  parentGroupId,
  onAddToGroup,
  onCreateGroupWithLayer,
  onMoveLayerOutOfGroup,
  isMultiSelected,
  isMultiSelectionActive,
  onCmdClick,
  onShiftClick,
  onCheckboxClick,
  isFresh,
}: SortableStackRowProps) {
  const {
    attributes,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
    isDragging,
    isOver,
  } = useSortable({ id: layer.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const handleSelectLayer = useCallback(
    (id: string) => onSelectLayer(id),
    [onSelectLayer],
  );

  return (
    <div ref={setNodeRef} style={style} data-dnd-over={isOver ? 'true' : undefined} data-row-id={layer.id}>
      <StackRow
        layer={layer}
        selected={selected}
        isDragging={isDragging}
        dragHandleProps={{ attributes, listeners, setActivatorNodeRef }}
        onSelectLayer={handleSelectLayer}
        onToggleVisibility={onToggleVisibility}
        onOpacityChange={onOpacityChange}
        onRemove={onRemove}
        onRename={onRename}
        onDuplicate={onDuplicate}
        existingFolderGroups={existingFolderGroups}
        parentGroupId={parentGroupId}
        onAddToGroup={onAddToGroup}
        onCreateGroupWithLayer={onCreateGroupWithLayer}
        onMoveLayerOutOfGroup={onMoveLayerOutOfGroup}
        isMultiSelected={isMultiSelected}
        isMultiSelectionActive={isMultiSelectionActive}
        onCmdClick={onCmdClick}
        onShiftClick={onShiftClick}
        onCheckboxClick={onCheckboxClick}
        isFresh={isFresh}
      />
    </div>
  );
});

// ---------------------------------------------------------------------------
// BasemapGroupRowWrapper — sortable wrapper for the basemap group row
// ---------------------------------------------------------------------------

interface BasemapGroupRowWrapperProps {
  group: BasemapGroupInfo;
  selected: boolean;
  isExpanded: boolean;
  /** When true, the eye button is rendered as aria-disabled. Pass true when the toggle is not yet wired. */
  visibilityDisabled?: boolean;
  onSelectGroup: (id: string | null) => void;
  onToggleExpand: (id: string) => void;
  onToggleVisibility: (id: string) => void;
  onOpacityChange: (id: string, opacity: number) => void;
  onSwapBasemap: () => void;
  onResetAppearance: () => void;
  // Phase 1041: boundary signal — shows cursor-not-allowed when multi-selection is active
  isMultiSelectionActive?: boolean;
}

// Basemap group is a drop target only — Phase 1040 replaced the no-op useSortable
// with useDroppable per AUD-04. Drag-out of basemap is intentionally not supported
// (basemap is pinned). The basemap row was previously registered via useSortable but
// excluded from sortableIds, making drag attempts a silent no-op. useDroppable gives
// it proper drop-target semantics for catalog basemap drops in Plan 02.
const BasemapGroupRowWrapper = memo(function BasemapGroupRowWrapper({
  group,
  selected,
  isExpanded,
  visibilityDisabled = false,
  onSelectGroup,
  onToggleExpand,
  onToggleVisibility,
  onOpacityChange,
  onSwapBasemap,
  onResetAppearance,
  isMultiSelectionActive,
}: BasemapGroupRowWrapperProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: group.id,
    data: { source: 'stack', kind: 'basemap-group' },
  });

  const handleSelectGroup = useCallback(
    (id: string) => onSelectGroup(id),
    [onSelectGroup],
  );

  return (
    <div ref={setNodeRef} data-basemap-drop-target={isOver ? 'true' : undefined}>
      <BasemapGroupRow
        groupId={group.id}
        presetName={group.presetName}
        providerLabel={group.providerLabel}
        visible={group.visible}
        opacity={group.opacity}
        selected={selected}
        isExpanded={isExpanded}
        isDragging={false}
        visibilityDisabled={visibilityDisabled}
        dragHandleProps={{ attributes: {} as DraggableAttributes, listeners: undefined, setActivatorNodeRef: NOOP }}
        onSelectGroup={handleSelectGroup}
        onToggleExpand={onToggleExpand}
        onToggleVisibility={onToggleVisibility}
        onOpacityChange={onOpacityChange}
        onSwapBasemap={onSwapBasemap}
        onResetAppearance={onResetAppearance}
        isMultiSelectionActive={isMultiSelectionActive}
      />
    </div>
  );
});

// ---------------------------------------------------------------------------
// FolderGroupRowWrapper — sortable wrapper for folder group rows
// ---------------------------------------------------------------------------

interface FolderGroupRowWrapperProps {
  layer: MapLayerResponse;
  selected: boolean;
  isExpanded: boolean;
  onSelectGroup: (id: string | null) => void;
  onToggleExpand: (id: string) => void;
  onToggleVisibility: (id: string) => void;
  onOpacityChange: (id: string, opacity: number) => void;
  onRenameGroup: (id: string, name: string) => void;
  onAddLayer: (id: string) => void;
  onUngroup: (id: string) => void;
  onDeleteGroup: (id: string) => void;
  // Phase 1041: multi-selection
  isMultiSelected?: boolean;
  isMultiSelectionActive?: boolean;
  onCmdClick?: (id: string) => void;
  onShiftClick?: (id: string) => void;
  onCheckboxClick?: (id: string) => void;
}

const FolderGroupRowWrapper = memo(function FolderGroupRowWrapper({
  layer,
  selected,
  isExpanded,
  onSelectGroup,
  onToggleExpand,
  onToggleVisibility,
  onOpacityChange,
  onRenameGroup,
  onAddLayer,
  onUngroup,
  onDeleteGroup,
  isMultiSelected,
  isMultiSelectionActive,
  onCmdClick,
  onShiftClick,
  onCheckboxClick,
}: FolderGroupRowWrapperProps) {
  const {
    attributes,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
    isDragging,
    isOver,
  } = useSortable({ id: layer.id });

  // Phase 1040 POL-03: folder group is a drop target for catalog drags.
  // data-group-drop-target activates only when a catalog drag is in flight,
  // so intra-stack reorder visuals (insertion line) remain the affordance for
  // intra-stack drags.
  const { active } = useDndContext();
  const isCatalogDragActive = (active?.data?.current as { source?: string } | undefined)?.source === 'catalog';

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const handleSelectGroup = useCallback(
    (id: string) => onSelectGroup(id),
    [onSelectGroup],
  );

  const displayName = layer.display_name ?? layer.dataset_name;
  const opacity = typeof layer.opacity === 'number' && Number.isFinite(layer.opacity) ? layer.opacity : 1;

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-group-drop-target={isOver && isCatalogDragActive ? 'true' : undefined}
      data-row-id={layer.id}
    >
      <FolderGroupRow
        groupId={layer.id}
        groupName={displayName}
        visible={layer.visible}
        opacity={opacity}
        selected={selected}
        isExpanded={isExpanded}
        isDragging={isDragging}
        dragHandleProps={{ attributes, listeners, setActivatorNodeRef }}
        onSelectGroup={handleSelectGroup}
        onToggleExpand={onToggleExpand}
        onToggleVisibility={onToggleVisibility}
        onOpacityChange={onOpacityChange}
        onRenameGroup={onRenameGroup}
        onAddLayer={onAddLayer}
        onUngroup={onUngroup}
        onDeleteGroup={onDeleteGroup}
        isMultiSelected={isMultiSelected}
        isMultiSelectionActive={isMultiSelectionActive}
        onCmdClick={onCmdClick}
        onShiftClick={onShiftClick}
        onCheckboxClick={onCheckboxClick}
      />
    </div>
  );
});

// ---------------------------------------------------------------------------
// SublayerRow — basemap sublayer row (useSortable disabled — cannot be dragged)
// ---------------------------------------------------------------------------

interface SublayerRowProps {
  sublayer: BasemapSublayerInfo;
  selected: boolean;
  onSelectLayer: (id: string | null) => void;
  onToggleSublayerVisibility: (sublayerId: string) => void;
  onSublayerOpacityChange: (sublayerId: string, opacity: number) => void;
}

const SublayerRow = memo(function SublayerRow({
  sublayer,
  selected,
  onSelectLayer,
  onToggleSublayerVisibility,
  onSublayerOpacityChange,
}: SublayerRowProps) {
  // Basemap sublayers CANNOT be dragged out of the group — useSortable disabled
  const { setNodeRef } = useSortable({ id: sublayer.id, disabled: true });

  const safeOpacity = typeof sublayer.opacity === 'number' && Number.isFinite(sublayer.opacity) ? sublayer.opacity : 1;

  return (
    <div
      ref={setNodeRef}
      id={`stack-row-${sublayer.id}`}
      role="option"
      aria-selected={selected}
      tabIndex={0}
      className={cn(
        'group/row grid grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2 items-center py-2 px-2 cursor-pointer select-none',
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

      {/* Cell 3: Eye visibility toggle */}
      <button
        type="button"
        aria-label={`Toggle visibility for ${sublayer.name}`}
        className="flex items-center justify-center h-[22px] w-[22px] rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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

      {/* Cell 6: Opacity slider */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
      <div
        className="flex items-center"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        <Slider
          aria-label={`Opacity for ${sublayer.name}`}
          aria-valuetext={`${Math.round(safeOpacity * 100)}%`}
          value={[safeOpacity]}
          min={0}
          max={1}
          step={0.05}
          className="w-[60px]"
          onValueChange={([value]) => {
            onSublayerOpacityChange(sublayer.id, Number((value ?? safeOpacity).toFixed(2)));
          }}
        />
      </div>

      {/* Cell 7: Kebab — hidden for basemap sublayers (per UI-SPEC) */}
      <span aria-hidden="true" style={{ visibility: 'hidden' }} className="h-[22px] w-[22px]" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// CatalogDragGhost — compact pill shown in DragOverlay during a catalog drag.
// Rendered instead of the intra-stack StackRow ghost so the overlay accurately
// represents a "new-dataset-to-be-added" rather than an existing stack row.
// Exported so vitest can import and assert on it directly.
// ---------------------------------------------------------------------------

export function CatalogDragGhost({
  recordType,
  name,
}: {
  recordType: string;
  name: string;
}) {
  // Type-icon swatch palette per UI-SPEC section 2.
  // Basemap → primary-50/primary-700; raster/vrt → type-raster-bg/type-raster; default (vector) → type-vector-bg/type-vector.
  let swatchBg: string;
  let swatchColor: string;
  let swatchGlyph: string;
  if (recordType === 'basemap') {
    swatchBg = 'var(--primary-50, oklch(0.97 0.02 250))';
    swatchColor = 'var(--primary-700, oklch(0.40 0.15 250))';
    swatchGlyph = 'B';
  } else if (recordType === 'raster_dataset' || recordType === 'vrt_dataset') {
    swatchBg = 'var(--type-raster-bg, oklch(0.95 0.04 60))';
    swatchColor = 'var(--type-raster, oklch(0.55 0.12 60))';
    swatchGlyph = 'R';
  } else {
    // vector_dataset or unknown
    swatchBg = 'var(--type-vector-bg, oklch(0.95 0.04 145))';
    swatchColor = 'var(--type-vector, oklch(0.45 0.12 145))';
    swatchGlyph = 'V';
  }

  return (
    <div
      data-testid="catalog-ghost"
      className="pointer-events-none flex items-center gap-2 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 cursor-grabbing"
      style={{
        boxShadow: '0 4px 12px oklch(0 0 0 / 15%)',
        maxWidth: 260,
        minHeight: 36,
      }}
    >
      {/* Type swatch */}
      <span
        aria-hidden="true"
        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded"
        style={{ background: swatchBg, color: swatchColor }}
      >
        <span className="text-[10px] font-semibold uppercase">{swatchGlyph}</span>
      </span>
      {/* Dataset name */}
      <span className="truncate text-sm" style={{ maxWidth: 200 }}>{name}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export const UnifiedStackPanel = memo(function UnifiedStackPanel({
  layers,
  selectedLayerId,
  onSelectLayer,
  onToggleVisibility,
  // onReorder is intentionally not destructured here — Phase 1040 lifted DragEnd
  // to MapBuilderPage which calls layers.handleReorder directly. The prop is kept
  // in the interface for call-site compatibility (MapBuilderPage still passes it).
  onOpacityChange,
  onRemove,
  onRename,
  onDuplicate,
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
  onSublayerOpacityChange,
  onSwapBasemap,
  onResetBasemapAppearance,
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
  freshLayerId = null,
}: UnifiedStackPanelProps) {
  const { t } = useTranslation('builder');

  // Phase 1040 Plan 04: read the active drag item from the lifted DndContext so the
  // DragOverlay can branch between an intra-stack StackRow ghost and a catalog drag pill.
  // This is a second call to useDndContext — the first lives inside FolderGroupRowWrapper.
  // Both coexist safely; @dnd-kit supports multiple consumers of the same context.
  const { active } = useDndContext();

  // Phase 1041: ref for the scrollable listbox element — used for outside-click guard
  // and Shift+Arrow focus management.
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
  // Effect mounts only when selection is non-empty (keyed on size > 0 via early-return).
  useEffect(() => {
    if (selectedIds.size === 0) return;
    function handleMouseDown(e: MouseEvent) {
      const target = e.target as Node;
      if (stackPanelRef.current?.contains(target)) return;
      // Portal-rendered bulk-action overflow menu — treat as in-bounds.
      if ((target as Element | null)?.closest?.('[data-bulk-action-menu="true"]')) return;
      onClearSelection?.();
    }
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- selectedIds.size is the only reactive dep; onClearSelection is stable from useCallback
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
  // eslint-disable-next-line react-hooks/exhaustive-deps -- selectedIds.size + selectableRowIds trigger remount; callbacks are stable
  }, [selectedIds.size, selectableRowIds, onClearSelection, onShiftClick]);

  // SortableContext items: all layer ids only.
  // basemapGroup is excluded: it is pinned at the top and cannot be reordered.
  // Including it previously made the row visually draggable but the drag was a
  // silent no-op because handleDragEnd searches only the layers array.
  const sortableIds = useMemo(() => {
    const ids: string[] = [];
    for (const l of layers) ids.push(l.id);
    return ids;
  }, [layers]);

  // Build the render plan: group children by parent for O(N) pass
  const childrenByGroup = useMemo(() => {
    const map: Record<string, MapLayerResponse[]> = {};
    for (const layer of layers) {
      const parent = getParentGroupId(layer);
      if (parent) {
        (map[parent] ??= []).push(layer);
      }
    }
    return map;
  }, [layers]);

  // Noop fallbacks for optional handlers — use module-level NOOP so references
  // are stable and do not defeat memo() on children.
  const safeToggleSublayerVisibility = onToggleSublayerVisibility ?? NOOP;
  const safeSublayerOpacityChange = onSublayerOpacityChange ?? NOOP;
  const safeSwapBasemap = onSwapBasemap ?? NOOP;
  const safeResetBasemapAppearance = onResetBasemapAppearance ?? NOOP;
  const safeRenameGroup = onRenameGroup ?? NOOP;
  const safeAddLayerToGroup = onAddLayerToGroup ?? NOOP;
  const safeUngroup = onUngroup ?? NOOP;
  const safeDeleteGroup = onDeleteGroup ?? NOOP;
  const safeAddLayerToExistingGroup = onAddLayerToExistingGroup ?? NOOP;
  const safeCreateGroupWithLayer = onCreateGroupWithLayer ?? NOOP;
  const safeMoveLayerOutOfGroup = onMoveLayerOutOfGroup ?? NOOP;
  const safeToggleGroupExpand = onToggleGroupExpand ?? NOOP;

  const isEmpty = layers.length === 0;

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
          visibilityDisabled // basemap visibility via eye not wired in v1; disables eye button
          onSelectGroup={onSelectLayer}
          onToggleExpand={safeToggleGroupExpand}
          onToggleVisibility={() => {}}
          onOpacityChange={() => {}} // opacity via master slider in Scene B editor
          onSwapBasemap={safeSwapBasemap}
          onResetAppearance={safeResetBasemapAppearance}
          isMultiSelectionActive={isMultiSelectionActive}
        />
        {isBasemapExpanded && (
          <div
            id={`basemap-group-children-${basemapGroup.id}`}
            data-testid={`basemap-group-children-${basemapGroup.id}`}
            style={{ marginLeft: '28px', paddingLeft: '12px', borderLeft: '1px dashed var(--border)' }}
            role="listbox"
            aria-label="Basemap sublayers"
          >
            {basemapGroup.sublayers.map((sub) => (
              <SublayerRow
                key={sub.id}
                sublayer={sub}
                selected={sub.id === selectedLayerId}
                onSelectLayer={onSelectLayer}
                onToggleSublayerVisibility={safeToggleSublayerVisibility}
                onSublayerOpacityChange={safeSublayerOpacityChange}
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
          {layers.length > 0 && (
            <Badge variant="secondary" className="rounded-full px-2 text-xs font-semibold">
              {layers.length}
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
                  'flex h-8 w-8 items-center justify-center rounded transition-colors',
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
            <Plus className="h-3 w-3" aria-hidden="true" />
            {t('unifiedStack.addData', { defaultValue: '＋ Add data' })}
          </Button>
        </div>
      </div>

      {/* Scrollable layer list or empty state */}
      {/* Phase 1041: aria-multiselectable="true" (POL-07); stackPanelRef for outside-click + Shift+Arrow */}
      <div
        ref={stackPanelRef}
        className="flex-1 overflow-y-auto"
        role="listbox"
        aria-label={t('unifiedStack.listboxLabel', { defaultValue: 'Map layers' })}
        aria-multiselectable="true"
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
              {/* 1. Basemap group (always at top when present) */}
              {renderBasemapDockRow(false)}

              {/* 2. User folder groups + loose layers (in saved order) */}
              {layers.map((layer) => {
                // Skip child rows — they render inside their group container
                if (getParentGroupId(layer)) return null;

                if (isFolderGroupLayer(layer)) {
                  // Folder group row with children container when expanded
                  const expanded = groupMeta[layer.id]?.expanded ?? false;
                  const children = childrenByGroup[layer.id] ?? [];
                  return (
                    <div key={layer.id}>
                      <FolderGroupRowWrapper
                        layer={layer}
                        selected={layer.id === selectedLayerId}
                        isExpanded={expanded}
                        onSelectGroup={onSelectLayer}
                        onToggleExpand={safeToggleGroupExpand}
                        onToggleVisibility={onToggleVisibility}
                        onOpacityChange={onOpacityChange}
                        onRenameGroup={safeRenameGroup}
                        onAddLayer={safeAddLayerToGroup}
                        onUngroup={safeUngroup}
                        onDeleteGroup={safeDeleteGroup}
                        isMultiSelected={selectedIds.has(layer.id)}
                        isMultiSelectionActive={isMultiSelectionActive}
                        onCmdClick={onCmdClick}
                        onShiftClick={onShiftClick}
                        onCheckboxClick={onCheckboxClick}
                      />
                      {expanded && (
                        <div
                          id={`folder-group-children-${layer.id}`}
                          data-testid={`folder-group-children-${layer.id}`}
                          style={{ marginLeft: '28px', paddingLeft: '12px', borderLeft: '1px dashed var(--border)' }}
                          role="list"
                        >
                          {children.map((child) => (
                            <SortableStackRow
                              key={child.id}
                              layer={child}
                              selected={child.id === selectedLayerId}
                              onSelectLayer={onSelectLayer}
                              onToggleVisibility={onToggleVisibility}
                              onOpacityChange={onOpacityChange}
                              onRemove={onRemove}
                              onRename={onRename}
                              onDuplicate={onDuplicate}
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
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  );
                }

                // Loose layer
                return (
                  <SortableStackRow
                    key={layer.id}
                    layer={layer}
                    selected={layer.id === selectedLayerId}
                    onSelectLayer={onSelectLayer}
                    onToggleVisibility={onToggleVisibility}
                    onOpacityChange={onOpacityChange}
                    onRemove={onRemove}
                    onRename={onRename}
                    onDuplicate={onDuplicate}
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
                  />
                );
              })}
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
                  <div className="opacity-40 scale-[0.98] pointer-events-none bg-[var(--surface-2)] rounded shadow-md">
                    <StackRow
                      layer={activeLayer}
                      selected={false}
                      isDragging={true}
                      dragHandleProps={{ attributes: {} as DraggableAttributes, listeners: undefined, setActivatorNodeRef: NOOP }}
                      onSelectLayer={NOOP}
                      onToggleVisibility={NOOP}
                      onOpacityChange={NOOP}
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

      {/* Phase 1041-02: BulkActionBar — sticky footer, visible only when 2+ rows selected */}
      {selectedIds.size >= 2 && onBulkVisibility && onBulkOpacity && onBulkGroup && onBulkUngroup && onBulkDelete && (
        <BulkActionBar
          selectedIds={selectedIds}
          layers={layers}
          onBulkVisibility={onBulkVisibility}
          onBulkOpacity={onBulkOpacity}
          onBulkGroup={onBulkGroup}
          onBulkUngroup={onBulkUngroup}
          onBulkDelete={onBulkDelete}
        />
      )}
    </div>
  );
});
