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
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { BasemapPicker } from '@/components/builder/BasemapPicker';
import { BasemapAppearanceControls } from '@/components/builder/BasemapAppearanceControls';
import { TerrainControls } from '@/components/builder/TerrainControls';
import { MapStackItem } from '@/components/builder/MapStackItem';
import { MapStackSection } from '@/components/builder/MapStackSection';
import {
  buildMapStack,
  type MapStackEntry,
  type MapStackGroup,
} from '@/components/builder/map-stack';
import type { MapBasemapConfig, MapLayerResponse, MapTerrainConfig } from '@/types/api';

interface MapStackPanelProps {
  layers: MapLayerResponse[];
  expandedLayerId: string | null;
  basemapStyle: string;
  showBasemapLabels: boolean;
  basemapConfig: MapBasemapConfig | null;
  terrainConfig: MapTerrainConfig | null;
  widgets?: string[] | null;
  widgetSidebar?: React.ReactNode;
  onToggleExpand: (id: string) => void;
  onToggleVisibility: (id: string) => void;
  onMoveUp: (id: string) => void;
  onMoveDown: (id: string) => void;
  onReorder: (layers: MapLayerResponse[]) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onRemove: (id: string) => void;
  onZoomToLayer: (id: string) => void;
  onToggleLegend: (id: string) => void;
  onAddDataClick: () => void;
  onBasemapChange: (key: string) => void;
  onBasemapLabelsChange: (show: boolean) => void;
  onBasemapConfigChange: (value: MapBasemapConfig) => void;
  onTerrainChange: (value: MapTerrainConfig | null) => void;
}

interface SortableStackItemProps {
  entry: MapStackEntry;
  layer: MapLayerResponse;
  isActive: boolean;
  isFirst: boolean;
  isLast: boolean;
  actions: Pick<
    MapStackPanelProps,
    | 'onToggleVisibility'
    | 'onMoveUp'
    | 'onMoveDown'
    | 'onRename'
    | 'onRemove'
    | 'onZoomToLayer'
    | 'onToggleLegend'
    | 'onToggleExpand'
  >;
}

function isPrimaryLayerEntry(entry: MapStackEntry) {
  return entry.role === 'data-layer' || entry.role.startsWith('relief-');
}

function SortableStackItem({
  entry,
  layer,
  isActive,
  isFirst,
  isLast,
  actions,
}: SortableStackItemProps) {
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
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef}>
      <MapStackItem
        entry={entry}
        layer={layer}
        isActive={isActive}
        isFirst={isFirst}
        isLast={isLast}
        style={style}
        dragHandleProps={{ attributes, listeners, setActivatorNodeRef }}
        onToggleVisibility={actions.onToggleVisibility}
        onMoveUp={actions.onMoveUp}
        onMoveDown={actions.onMoveDown}
        onRename={actions.onRename}
        onRemove={actions.onRemove}
        onZoomToLayer={actions.onZoomToLayer}
        onToggleLegend={actions.onToggleLegend}
        onOpenInspector={actions.onToggleExpand}
      />
    </div>
  );
}

export const MapStackPanel = memo(function MapStackPanel({
  layers,
  expandedLayerId,
  basemapStyle,
  showBasemapLabels,
  basemapConfig,
  terrainConfig,
  widgets,
  widgetSidebar,
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
  onBasemapChange,
  onBasemapLabelsChange,
  onBasemapConfigChange,
  onTerrainChange,
}: MapStackPanelProps) {
  const { t } = useTranslation('builder');
  const stackGroups = useMemo(
    () => buildMapStack({
      basemap_style: basemapStyle,
      show_basemap_labels: showBasemapLabels,
      basemap_config: basemapConfig,
      terrain_config: terrainConfig,
      layers,
      widgets,
    }),
    [basemapConfig, basemapStyle, layers, showBasemapLabels, terrainConfig, widgets],
  );
  const layerById = useMemo(
    () => new Map(layers.map((layer) => [layer.id, layer])),
    [layers],
  );
  const sortableIds = useMemo(() => layers.map((layer) => layer.id), [layers]);
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = layers.findIndex((layer) => layer.id === active.id);
    const newIndex = layers.findIndex((layer) => layer.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;
    onReorder(arrayMove(layers, oldIndex, newIndex));
  }, [layers, onReorder]);

  const actions = useMemo(
    () => ({
      onToggleVisibility,
      onMoveUp,
      onMoveDown,
      onRename,
      onRemove,
      onZoomToLayer,
      onToggleLegend,
      onToggleExpand,
    }),
    [
      onMoveDown,
      onMoveUp,
      onRemove,
      onRename,
      onToggleExpand,
      onToggleLegend,
      onToggleVisibility,
      onZoomToLayer,
    ],
  );

  function renderEntry(group: MapStackGroup, entry: MapStackEntry) {
    const layerId = entry.metadata.sourceLayerId;
    const layer = layerId ? layerById.get(layerId) : undefined;
    const isPrimary = isPrimaryLayerEntry(entry);
    const layerIndex = layer ? layers.findIndex((candidate) => candidate.id === layer.id) : -1;

    if (isPrimary && layer) {
      return (
        <SortableStackItem
          key={entry.id}
          entry={entry}
          layer={layer}
          isActive={expandedLayerId === layer.id}
          isFirst={layerIndex <= 0}
          isLast={layerIndex === layers.length - 1}
          actions={actions}
        />
      );
    }

    return (
      <MapStackItem
        key={entry.id}
        entry={entry}
        layer={layer}
        isActive={Boolean(layer && expandedLayerId === layer.id)}
        onToggleVisibility={onToggleVisibility}
        onMoveUp={onMoveUp}
        onMoveDown={onMoveDown}
        onRename={onRename}
        onRemove={onRemove}
        onZoomToLayer={onZoomToLayer}
        onToggleLegend={onToggleLegend}
        onOpenInspector={onToggleExpand}
        onToggleBasemapLabels={entry.role === 'basemap-labels' ? onBasemapLabelsChange : undefined}
      />
    );
  }

  function renderSectionExtras(group: MapStackGroup) {
    if (group.id === 'surface') {
      return (
        <div className="px-2 pt-1">
          <TerrainControls
            layers={layers}
            value={terrainConfig}
            onChange={onTerrainChange}
          />
        </div>
      );
    }
    if (group.id === 'basemap') {
      return (
        <div className="px-2 pt-1">
          <BasemapPicker
            value={basemapStyle}
            onChange={onBasemapChange}
          />
          <BasemapAppearanceControls
            value={basemapConfig}
            showBasemapLabels={showBasemapLabels}
            onChange={onBasemapConfigChange}
            onShowBasemapLabelsChange={onBasemapLabelsChange}
          />
        </div>
      );
    }
    if (group.id === 'data' && group.entries.length === 0) {
      return (
        <div className="px-2 py-3">
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-full gap-1 text-xs"
            onClick={onAddDataClick}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            {t('layers.addData')}
          </Button>
        </div>
      );
    }
    if (group.id === 'interactions' && widgetSidebar) {
      return (
        <div className="px-2 pt-1">
          {widgetSidebar}
        </div>
      );
    }
    return null;
  }

  const totalEntries = stackGroups.reduce((sum, group) => sum + group.entries.length, 0);
  const title = t('mapStack.title', { defaultValue: 'Map Stack' });

  return (
    <div className="pb-3" aria-label={title}>
      <div className="flex h-11 items-center justify-between gap-2 px-2">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold">{title}</h2>
          <p className="sr-only">
            {t('mapStack.entryCount', {
              count: totalEntries,
              defaultValue: '{{count}} stack items',
            })}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-8 shrink-0 gap-1 text-xs"
          onClick={onAddDataClick}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          {t('layers.addData')}
        </Button>
      </div>

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
          {stackGroups.map((group) => (
            <MapStackSection
              key={group.id}
              group={group}
              entryCount={group.entries.length}
            >
              {group.entries.map((entry) => renderEntry(group, entry))}
              {renderSectionExtras(group)}
            </MapStackSection>
          ))}
        </SortableContext>
      </DndContext>
    </div>
  );
});
