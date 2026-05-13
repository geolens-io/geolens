import { memo, useCallback, useMemo } from 'react';
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type { DragEndEvent } from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useTranslation } from 'react-i18next';
import { Plus, Settings } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { StackRow } from '@/components/builder/StackRow';
import type { MapLayerResponse } from '@/types/api';

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
  onAddDataClick: () => void;
  onSettingsClick: () => void; // TODO Phase 1036: wire to settings affordance
}

interface SortableStackRowProps {
  layer: MapLayerResponse;
  selected: boolean;
  onSelectLayer: (id: string | null) => void;
  onToggleVisibility: (id: string) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onRemove: (id: string) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onDuplicate: (id: string) => void;
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
}: SortableStackRowProps) {
  const {
    attributes,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
    isDragging,
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
    <div ref={setNodeRef} style={style}>
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
      />
    </div>
  );
});

export const UnifiedStackPanel = memo(function UnifiedStackPanel({
  layers,
  selectedLayerId,
  onSelectLayer,
  onToggleVisibility,
  onReorder,
  onOpacityChange,
  onRemove,
  onRename,
  onDuplicate,
  onAddDataClick,
  onSettingsClick,
}: UnifiedStackPanelProps) {
  const { t } = useTranslation('builder');

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // px — drag only after moving >= 8px from pointerdown origin
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const sortableIds = useMemo(() => layers.map((l) => l.id), [layers]);

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = layers.findIndex((layer) => layer.id === active.id);
    const newIndex = layers.findIndex((layer) => layer.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;
    onReorder(arrayMove(layers, oldIndex, newIndex));
  }, [layers, onReorder]);

  const handleDragStart = useCallback(() => {
    onSelectLayer(null);
  }, [onSelectLayer]);

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
            <Badge variant="secondary" className="rounded-full px-2 text-xs font-medium">
              {layers.length}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            aria-label={t('unifiedStack.settings', { defaultValue: 'Settings' })}
            className="flex h-[22px] w-[22px] items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={onSettingsClick}
          >
            <Settings className="h-4 w-4" aria-hidden="true" />
          </button>
          <Button
            variant="default"
            size="sm"
            className="h-7 gap-1 px-2 text-xs"
            onClick={onAddDataClick}
          >
            <Plus className="h-3 w-3" aria-hidden="true" />
            {t('unifiedStack.addData', { defaultValue: '＋ Add data' })}
          </Button>
        </div>
      </div>

      {/* Scrollable layer list or empty state */}
      <div
        className="flex-1 overflow-y-auto"
        role="listbox"
        aria-label={t('unifiedStack.title', { defaultValue: 'Layers' })}
        aria-multiselectable="false"
      >
        {layers.length === 0 ? (
          <div className="flex items-center justify-center h-24">
            <p className="text-sm text-muted-foreground">
              {t('unifiedStack.emptyState', { defaultValue: 'No layers yet' })}
            </p>
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={sortableIds}
              strategy={verticalListSortingStrategy}
            >
              {layers.map((layer) => (
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
                />
              ))}
            </SortableContext>
          </DndContext>
        )}
      </div>
    </div>
  );
});
