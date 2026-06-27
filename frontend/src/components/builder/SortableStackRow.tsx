// builder-audit #338 STACK-05: extracted from UnifiedStackPanel.tsx into a sibling
// file. Sortable wrapper for a loose layer or a folder-group child row.
import { memo, useCallback } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { StackRow } from '@/components/builder/StackRow';
import type { MapLayerResponse } from '@/types/api';

interface SortableStackRowProps {
  layer: MapLayerResponse;
  selected: boolean;
  onSelectLayer: (id: string | null) => void;
  onToggleVisibility: (id: string) => void;
  onRemove: (id: string) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onDuplicate: (id: string) => void;
  // Phase 1201-01 (ENH-01/ENH-02): kebab authoring actions threaded to StackRow.
  onZoomToLayer?: (id: string) => void;
  onCopyStyle?: (id: string) => void;
  onPasteStyle?: (id: string) => void;
  canPasteStyle?: boolean;
  onKeyboardReorder?: (layerId: string, direction: 'up' | 'down') => void;
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
  // Phase 1199 STACK-01: "Copy N of M" duplicate label, null when not a duplicate
  disambiguationLabel?: string | null;
  // Phase 1201-02 (ENH-07): disable drag while search is active to prevent
  // sort_order corruption when only a filtered subset is visible.
  dragDisabled?: boolean;
}

export const SortableStackRow = memo(function SortableStackRow({
  layer,
  selected,
  onSelectLayer,
  onToggleVisibility,
  onRemove,
  onRename,
  onDuplicate,
  onZoomToLayer,
  onCopyStyle,
  onPasteStyle,
  canPasteStyle,
  onKeyboardReorder,
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
  disambiguationLabel,
  dragDisabled = false,
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
  } = useSortable({ id: layer.id, disabled: dragDisabled });

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
        onRemove={onRemove}
        onRename={onRename}
        onDuplicate={onDuplicate}
        onZoomToLayer={onZoomToLayer}
        onCopyStyle={onCopyStyle}
        onPasteStyle={onPasteStyle}
        canPasteStyle={canPasteStyle}
        onKeyboardReorder={onKeyboardReorder}
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
        disambiguationLabel={disambiguationLabel}
      />
    </div>
  );
});
