// Sortable wrapper for a loose layer or a folder-group child row.
import { memo, useCallback, useMemo } from 'react';
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
  // Kebab authoring actions threaded to StackRow.
  onZoomToLayer?: (id: string) => void;
  /** Opens the Analysis panel prefilled with this layer. */
  onAnalyzeLayer?: (id: string) => void;
  /** Opens the read-only attribute-table drawer for this layer. */
  onOpenAttributeTable?: (id: string) => void;
  onCopyStyle?: (id: string) => void;
  onPasteStyle?: (id: string) => void;
  canPasteStyle?: boolean;
  onKeyboardReorder?: (layerId: string, direction: 'up' | 'down') => boolean | void;
  /** Shared aria-live announcer for the keyboard reorder mode. */
  onAnnounce?: (text: string) => void;
  existingFolderGroups?: Array<{ id: string; name: string }>;
  parentGroupId?: string | null;
  onAddToGroup?: (layerId: string, groupId: string) => void;
  onCreateGroupWithLayer?: (layerId: string) => void;
  onMoveLayerOutOfGroup?: (layerId: string) => void;
  // Multi-selection
  isMultiSelected?: boolean;
  isMultiSelectionActive?: boolean;
  onCmdClick?: (id: string) => void;
  onShiftClick?: (id: string) => void;
  onCheckboxClick?: (id: string) => void;
  // Entry animation
  isFresh?: boolean;
  // "Copy N of M" duplicate label, null when not a duplicate
  disambiguationLabel?: string | null;
  /**
   * Non-null when this row is the LAST child of the named group: deleting it or
   * moving it out dissolves the group, so the row's confirms must say so.
   */
  dissolvesGroupName?: string | null;
  // True when this layer's dataset would be filtered out for the
  // map's audience (private/unpublished dataset on a public/shared map).
  audienceHidden?: boolean;
  // DEM overlay off + not the active terrain source → draws nothing.
  drawsNothing?: boolean;
  // Disable drag while search is active to prevent
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
  onAnalyzeLayer,
  onOpenAttributeTable,
  onCopyStyle,
  onPasteStyle,
  canPasteStyle,
  onKeyboardReorder,
  onAnnounce,
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
  dissolvesGroupName,
  audienceHidden,
  drawsNothing,
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

  // A fresh object literal here would re-break StackRow's memo on every wrapper
  // render even when the drag state is unchanged.
  const dragHandleProps = useMemo(
    () => ({ attributes, listeners, setActivatorNodeRef }),
    [attributes, listeners, setActivatorNodeRef],
  );

  return (
    // tabIndex=-1: a programmatic focus target (the page returns focus to the
    // first remaining row when a layer is removed while its table is open)
    // without joining the tab order; the row body keeps its own tabIndex.
    <div ref={setNodeRef} style={style} tabIndex={-1} data-dnd-over={isOver ? 'true' : undefined} data-row-id={layer.id}>
      <StackRow
        layer={layer}
        selected={selected}
        isDragging={isDragging}
        dragHandleProps={dragHandleProps}
        onSelectLayer={handleSelectLayer}
        onToggleVisibility={onToggleVisibility}
        onRemove={onRemove}
        onRename={onRename}
        onDuplicate={onDuplicate}
        onZoomToLayer={onZoomToLayer}
        onAnalyzeLayer={onAnalyzeLayer}
        onOpenAttributeTable={onOpenAttributeTable}
        onCopyStyle={onCopyStyle}
        onPasteStyle={onPasteStyle}
        canPasteStyle={canPasteStyle}
        onKeyboardReorder={onKeyboardReorder}
        onAnnounce={onAnnounce}
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
        dissolvesGroupName={dissolvesGroupName}
        audienceHidden={audienceHidden}
        drawsNothing={drawsNothing}
      />
    </div>
  );
});
