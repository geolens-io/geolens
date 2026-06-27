// builder-audit #338 STACK-05: extracted from UnifiedStackPanel.tsx into a sibling
// file. Sortable wrapper for the basemap group row.
import { memo, useCallback } from 'react';
import { useDndContext } from '@dnd-kit/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { BasemapGroupRow } from '@/components/builder/BasemapGroupRow';
import type { BasemapGroupInfo } from '@/components/builder/stack-types';

interface BasemapGroupRowWrapperProps {
  group: BasemapGroupInfo;
  selected: boolean;
  isExpanded: boolean;
  onSelectGroup: (id: string | null) => void;
  onToggleExpand: (id: string) => void;
  onToggleVisibility: (id: string) => void;
  onSwapBasemap: () => void;
  onResetAppearance: () => void;
  // Phase 1041: boundary signal — shows cursor-not-allowed when multi-selection is active
  isMultiSelectionActive?: boolean;
}

// UX-03 (Phase 1051 Plan 06): basemap group is SORTABLE — was useDroppable-only
// in Phase 1040 (AUD-04 pinned it to bottom). Lifted to useSortable mirroring
// FolderGroupRowWrapper so the user can drag the basemap between top and bottom
// positions in the layer stack. The `data` option preserves the catalog
// drop-target semantics (handleDragEnd in MapBuilderPage still reads
// `over.id === basemapGroup.id` for catalog basemap-swap drops).
// Persistence: position is encoded in MapBasemapConfig.basemap_position (jsonb,
// no migration) and serialized via use-builder-save.ts.
export const BasemapGroupRowWrapper = memo(function BasemapGroupRowWrapper({
  group,
  selected,
  isExpanded,
  onSelectGroup,
  onToggleExpand,
  onToggleVisibility,
  onSwapBasemap,
  onResetAppearance,
  isMultiSelectionActive,
}: BasemapGroupRowWrapperProps) {
  // Phase 1051 Plan 13 (CTRL-01 gate-fix): when a NON-basemap catalog item is
  // being dragged, disable the basemap-group sortable so dnd-kit's collision
  // detection does not resolve to basemap-group via closestCenter fallback.
  // The shadcn Dialog backdrop (`fixed inset-0 z-50`) intercepts pointer events
  // over the sidebar listbox, which makes `pointerWithin` return empty hits and
  // forces the fallback to closestCenter — and closestCenter can rank the
  // basemap row as nearest even when the user pointer is clearly over an
  // overlay row. Since handleDragEnd in MapBuilderPage silent-rejects this
  // exact combo (Case 3), short-circuiting it here gives the same semantics but
  // allows dnd-kit to land the drop on the actual overlay row target. Basemap
  // catalog drags (recordType === 'basemap') still need basemap-group as a drop
  // target — keep the sortable enabled for those.
  const { active } = useDndContext();
  const activeData = active?.data?.current as
    | { source?: string; recordType?: string }
    | undefined;
  const disableForCatalogNonBasemap =
    activeData?.source === 'catalog' && activeData?.recordType !== 'basemap';

  const {
    attributes,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
    isDragging,
    isOver,
  } = useSortable({
    id: group.id,
    data: { source: 'stack', kind: 'basemap-group' },
    // Only disable the DROPPABLE side; keep draggable enabled so the basemap
    // row can still be dragged out (basemap reposition). When a non-basemap
    // catalog drag is active, this prevents dnd-kit from picking basemap-group
    // via the closestCenter fallback when shadcn Dialog's backdrop blocks
    // pointerWithin hits.
    disabled: {
      draggable: false,
      droppable: disableForCatalogNonBasemap,
    },
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const handleSelectGroup = useCallback(
    (id: string) => onSelectGroup(id),
    [onSelectGroup],
  );

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-basemap-drop-target={isOver ? 'true' : undefined}
      data-row-id={group.id}
    >
      <BasemapGroupRow
        groupId={group.id}
        presetName={group.presetName}
        providerLabel={group.providerLabel}
        visible={group.visible}
        selected={selected}
        isExpanded={isExpanded}
        isDragging={isDragging}
        dragHandleProps={{ attributes, listeners, setActivatorNodeRef }}
        onSelectGroup={handleSelectGroup}
        onToggleExpand={onToggleExpand}
        onToggleVisibility={onToggleVisibility}
        onSwapBasemap={onSwapBasemap}
        onResetAppearance={onResetAppearance}
        isMultiSelectionActive={isMultiSelectionActive}
      />
    </div>
  );
});
