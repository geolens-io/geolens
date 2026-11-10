// Sortable wrapper for the basemap group row.
import { memo, useCallback, useMemo } from 'react';
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
  // Boundary signal — shows cursor-not-allowed when multi-selection is active
  isMultiSelectionActive?: boolean;
}

// The basemap group is sortable (useSortable, like FolderGroupRowWrapper) so the
// user can drag the basemap between top and bottom positions in the layer stack.
// The `data` option preserves the catalog drop-target semantics (handleDragEnd
// in MapBuilderPage reads `over.id === basemapGroup.id` for catalog basemap-swap
// drops). Position is encoded in MapBasemapConfig.basemap_position (jsonb) and
// serialized via use-builder-save.ts.
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
  // While a non-basemap catalog item is dragged, disable the basemap-group
  // sortable so dnd-kit's collision detection doesn't resolve to it via the
  // closestCenter fallback. The shadcn Dialog backdrop (`fixed inset-0 z-50`)
  // intercepts pointer events over the sidebar listbox, so `pointerWithin`
  // returns no hits and closestCenter can rank the basemap row nearest even when
  // the pointer is over an overlay row. handleDragEnd in MapBuilderPage
  // silent-rejects this combo (Case 3); short-circuiting here lets the drop land
  // on the overlay row. Basemap catalog drags (recordType === 'basemap') still
  // need basemap-group as a drop target, so the sortable stays enabled for them.
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
    // Disable only the droppable side; the draggable stays enabled so the
    // basemap row can still be dragged out (reposition).
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

  // A fresh object literal here re-breaks the row memo on every wrapper render
  // even when the drag state is unchanged.
  const dragHandleProps = useMemo(
    () => ({ attributes, listeners, setActivatorNodeRef }),
    [attributes, listeners, setActivatorNodeRef],
  );

  return (
    // tabIndex=-1: a programmatic focus target (the page returns focus to the
    // first remaining row when a layer is removed while its table is open)
    // without joining the tab order; the row body keeps its own tabIndex.
    <div
      ref={setNodeRef}
      style={style}
      tabIndex={-1}
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
        dragHandleProps={dragHandleProps}
        onSelectGroup={handleSelectGroup}
        onToggleExpand={onToggleExpand}
        onToggleVisibility={onToggleVisibility}
        onSwapBasemap={onSwapBasemap}
        onResetAppearance={onResetAppearance}
        hasCustomAppearance={group.hasCustomAppearance}
        isMultiSelectionActive={isMultiSelectionActive}
      />
    </div>
  );
});
