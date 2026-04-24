import { memo, useCallback, useMemo } from 'react';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type { DragEndEvent } from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
  sortableKeyboardCoordinates,
  arrayMove,
} from '@dnd-kit/sortable';
import { useTranslation } from 'react-i18next';
import { Plus } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { LayerItem } from './LayerItem';
import type { MapLayerResponse } from '@/types/api';

interface LayerPanelProps {
  layers: MapLayerResponse[];
  expandedLayerId: string | null;
  onToggleExpand: (id: string) => void;
  onToggleVisibility: (id: string) => void;
  onMoveUp: (id: string) => void;
  onMoveDown: (id: string) => void;
  onReorder: (layers: MapLayerResponse[]) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onRemove: (id: string) => void;
  onZoomToLayer: (id: string) => void;
  onToggleLegend: (id: string) => void;
  onAddDataClick?: () => void;
}

export const LayerPanel = memo(function LayerPanel({
  layers,
  expandedLayerId,
  onToggleExpand,
  onToggleVisibility,
  onMoveUp,
  onMoveDown,
  onReorder,
  onRename,
  onRemove,
  onZoomToLayer,
  onToggleLegend,
  onAddDataClick,
}: LayerPanelProps) {
  const { t } = useTranslation('builder');
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const sortableIds = useMemo(() => layers.map((l) => l.id), [layers]);

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = layers.findIndex((l) => l.id === active.id);
    const newIndex = layers.findIndex((l) => l.id === over.id);
    onReorder(arrayMove(layers, oldIndex, newIndex));
  }, [layers, onReorder]);

  return (
    <div>
      <div className="flex items-center justify-between px-2 mb-2">
        <div className="flex items-center gap-1.5">
          <h2 className="text-sm font-medium">{t('layers.title')}</h2>
          <Badge variant="secondary" className="text-xs">
            {layers.length}
          </Badge>
        </div>
        {onAddDataClick && (
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs gap-1"
            onClick={onAddDataClick}
          >
            <Plus className="h-3 w-3" />
            {t('layers.addData')}
          </Button>
        )}
      </div>

      {layers.length === 0 ? (
        <div className="px-2 py-6 space-y-2 graticule-fine rounded">
          <p className="text-xs text-muted-foreground text-center">
            {t('layers.emptyState')}
          </p>
          {onAddDataClick && (
            <Button
              variant="outline"
              size="sm"
              className="w-full gap-1 text-xs"
              onClick={onAddDataClick}
            >
              <Plus className="h-3.5 w-3.5" />
              {t('layers.addData')}
            </Button>
          )}
        </div>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={() => onToggleExpand('')}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={sortableIds}
            strategy={verticalListSortingStrategy}
          >
            <div className="space-y-0.5 max-h-[calc(100dvh-22rem)] overflow-y-auto" role="list" aria-label={t('layers.title')}>
              {layers.map((layer, idx) => (
                <LayerItem
                  key={layer.id}
                  layer={layer}
                  isFirst={idx === 0}
                  isLast={idx === layers.length - 1}
                  isExpanded={expandedLayerId === layer.id}
                  onToggleExpand={onToggleExpand}
                  onToggleVisibility={onToggleVisibility}
                  onMoveUp={onMoveUp}
                  onMoveDown={onMoveDown}
                  onRename={onRename}
                  onRemove={onRemove}
                  onZoomToLayer={onZoomToLayer}
                  onToggleLegend={onToggleLegend}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}
    </div>
  );
});
