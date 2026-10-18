// Sortable wrapper for folder group rows.
import { memo, useCallback, useMemo } from 'react';
import { useDndContext } from '@dnd-kit/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { FolderGroupRow } from '@/components/builder/FolderGroupRow';
import type { MapLayerResponse } from '@/types/api';

interface FolderGroupRowWrapperProps {
  layer: MapLayerResponse;
  selected: boolean;
  isExpanded: boolean;
  onSelectGroup: (id: string | null) => void;
  onToggleExpand: (id: string) => void;
  onToggleVisibility: (id: string) => void;
  onRenameGroup: (id: string, name: string) => void;
  onAddLayer: (id: string) => void;
  onUngroup: (id: string) => void;
  onDeleteGroup: (id: string) => void;
  // Multi-selection
  isMultiSelected?: boolean;
  isMultiSelectionActive?: boolean;
  onCmdClick?: (id: string) => void;
  onShiftClick?: (id: string) => void;
  onCheckboxClick?: (id: string) => void;
  // Disable drag while search is active.
  dragDisabled?: boolean;
}

export const FolderGroupRowWrapper = memo(function FolderGroupRowWrapper({
  layer,
  selected,
  isExpanded,
  onSelectGroup,
  onToggleExpand,
  onToggleVisibility,
  onRenameGroup,
  onAddLayer,
  onUngroup,
  onDeleteGroup,
  isMultiSelected,
  isMultiSelectionActive,
  onCmdClick,
  onShiftClick,
  onCheckboxClick,
  dragDisabled = false,
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
  } = useSortable({ id: layer.id, disabled: dragDisabled });

  // Folder group is a drop target for catalog drags.
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

  // A fresh object literal here would re-break the row memo on every wrapper
  // render even when the drag state is unchanged.
  const dragHandleProps = useMemo(
    () => ({ attributes, listeners, setActivatorNodeRef }),
    [attributes, listeners, setActivatorNodeRef],
  );

  const displayName = layer.display_name ?? layer.dataset_name;

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
        selected={selected}
        isExpanded={isExpanded}
        isDragging={isDragging}
        dragHandleProps={dragHandleProps}
        onSelectGroup={handleSelectGroup}
        onToggleExpand={onToggleExpand}
        onToggleVisibility={onToggleVisibility}
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
