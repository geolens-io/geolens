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
  arrayMove,
} from '@dnd-kit/sortable';
import { useTranslation } from 'react-i18next';
import { Plus } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { LayerItem } from './LayerItem';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, LabelConfig, StyleConfig } from '@/types/api';

interface LayerPanelProps {
  layers: MapLayerResponse[];
  expandedLayerId: string | null;
  activeTab: 'style' | 'filter' | 'labels' | null;
  onToggleExpand: (id: string) => void;
  onTabChange: (layerId: string, tab: 'style' | 'filter' | 'labels') => void;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onFilterChange: (layerId: string, expression: FilterSpecification | null) => void;
  onLabelChange: (layerId: string, config: LabelConfig | null) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onToggleVisibility: (id: string) => void;
  onMoveUp: (id: string) => void;
  onMoveDown: (id: string) => void;
  onReorder: (layers: MapLayerResponse[]) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onRemove: (id: string) => void;
  onZoomToLayer: (id: string) => void;
  onAddDataClick?: () => void;
}

export function LayerPanel({
  layers,
  expandedLayerId,
  activeTab,
  onToggleExpand,
  onTabChange,
  onPaintChange,
  onOpacityChange,
  onFilterChange,
  onLabelChange,
  onStyleConfigChange,
  onToggleVisibility,
  onMoveUp,
  onMoveDown,
  onReorder,
  onRename,
  onRemove,
  onZoomToLayer,
  onAddDataClick,
}: LayerPanelProps) {
  const { t } = useTranslation('builder');
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor),
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = layers.findIndex((l) => l.id === active.id);
    const newIndex = layers.findIndex((l) => l.id === over.id);
    onReorder(arrayMove(layers, oldIndex, newIndex));
  }

  return (
    <div>
      <div className="flex items-center justify-between px-2 mb-2">
        <div className="flex items-center gap-1.5">
          <h3 className="text-sm font-medium">{t('layers.title')}</h3>
          <Badge variant="secondary" className="text-xs">
            {layers.length}
          </Badge>
        </div>
        {onAddDataClick && (
          <Button
            variant="outline"
            size="sm"
            className="h-6 text-xs gap-1"
            onClick={onAddDataClick}
          >
            <Plus className="h-3 w-3" />
            {t('layers.addData')}
          </Button>
        )}
      </div>

      {layers.length === 0 ? (
        <p className="text-xs text-muted-foreground px-2">
          {t('layers.emptyState')}
        </p>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={() => onToggleExpand('')}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={layers.map((l) => l.id)}
            strategy={verticalListSortingStrategy}
          >
            <div className="space-y-0.5 max-h-[28rem] overflow-y-auto">
              {layers.map((layer, idx) => (
                <LayerItem
                  key={layer.id}
                  layer={layer}
                  index={idx}
                  totalLayers={layers.length}
                  isExpanded={expandedLayerId === layer.id}
                  activeTab={expandedLayerId === layer.id ? activeTab : null}
                  onToggleExpand={onToggleExpand}
                  onTabChange={onTabChange}
                  onPaintChange={onPaintChange}
                  onOpacityChange={onOpacityChange}
                  onFilterChange={onFilterChange}
                  onLabelChange={onLabelChange}
                  onStyleConfigChange={onStyleConfigChange}
                  onToggleVisibility={onToggleVisibility}
                  onMoveUp={onMoveUp}
                  onMoveDown={onMoveDown}
                  onRename={onRename}
                  onRemove={onRemove}
                  onZoomToLayer={onZoomToLayer}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}
    </div>
  );
}
