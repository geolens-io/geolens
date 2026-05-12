import { memo, useCallback, useMemo, useState } from 'react';
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
import { ChevronDown, ChevronRight, Plus, RefreshCcw, Shuffle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { BasemapAppearanceControls } from '@/components/builder/BasemapAppearanceControls';
import { TerrainControls } from '@/components/builder/TerrainControls';
import { MapStackItem } from '@/components/builder/MapStackItem';
import { MapStackSection } from '@/components/builder/MapStackSection';
import {
  buildMapStack,
  type MapStackEntry,
  type MapStackGroup,
} from '@/components/builder/map-stack';
import type { RenderAsId } from '@/components/builder/renderAs';
import { useBasemaps } from '@/hooks/use-settings';
import { basemapThumbnail, BLANK_BASEMAP_ID, normalizeBasemapConfig } from '@/lib/basemap-utils';
import type { BasemapEntry } from '@/api/settings';
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
  onOpacityChange: (layerId: string, opacity: number) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onRenderAsChange: (layerId: string, renderAs: RenderAsId) => void;
  onDuplicateRendering: (layerId: string) => void;
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
    | 'onOpacityChange'
    | 'onLayoutChange'
    | 'onRenderAsChange'
    | 'onDuplicateRendering'
  > & {
    onUseAsTerrain: (layerId: string) => void;
  };
}

interface DatasetRenderingHeaderModel {
  datasetId: string;
  datasetName: string;
  recordType: string | null;
  geometryType: string | null;
  featureCount: number | null;
  entries: MapStackEntry[];
}

type DataRenderBlock =
  | { kind: 'entry'; entry: MapStackEntry }
  | { kind: 'dataset'; dataset: DatasetRenderingHeaderModel };

function isPrimaryLayerEntry(entry: MapStackEntry) {
  return entry.role === 'data-layer' || entry.role.startsWith('relief-');
}

function visibleDemReliefLayerCount(layers: MapLayerResponse[]) {
  return layers.filter((layer) => layer.is_dem === true && layer.visible).length;
}

function canUseLayerAsTerrain(layer: MapLayerResponse) {
  return layer.is_dem === true
    && (layer.dataset_record_type === 'raster_dataset' || layer.dataset_record_type === 'vrt_dataset')
    && Boolean(layer.dataset_id);
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
        onOpacityChange={actions.onOpacityChange}
        onLayoutChange={actions.onLayoutChange}
        onRenderAsChange={actions.onRenderAsChange}
        onDuplicateRendering={actions.onDuplicateRendering}
        onUseAsTerrain={actions.onUseAsTerrain}
        onOpenInspector={actions.onToggleExpand}
      />
    </div>
  );
}

function formatRecordType(value: string | null) {
  if (!value) return 'Dataset';
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatFeatureCount(value: number | null) {
  if (value === null) return null;
  return `${value.toLocaleString()} features`;
}

function buildDataRenderBlocks(entries: MapStackEntry[]): DataRenderBlock[] {
  const byDataset = new Map<string, MapStackEntry[]>();
  for (const entry of entries) {
    const datasetId = entry.metadata.sourceDatasetId;
    if (!datasetId) continue;
    const matches = byDataset.get(datasetId) ?? [];
    matches.push(entry);
    byDataset.set(datasetId, matches);
  }

  const consumed = new Set<string>();
  const blocks: DataRenderBlock[] = [];
  for (const entry of entries) {
    const datasetId = entry.metadata.sourceDatasetId;
    const datasetEntries = datasetId ? byDataset.get(datasetId) ?? [] : [];
    if (!datasetId || datasetEntries.length < 2) {
      blocks.push({ kind: 'entry', entry });
      continue;
    }
    if (consumed.has(datasetId)) continue;

    consumed.add(datasetId);
    const first = datasetEntries[0];
    blocks.push({
      kind: 'dataset',
      dataset: {
        datasetId,
        datasetName: first.metadata.datasetName ?? first.title,
        recordType: first.metadata.datasetRecordType ?? null,
        geometryType: first.metadata.geometryType ?? null,
        featureCount: first.metadata.datasetFeatureCount ?? null,
        entries: datasetEntries,
      },
    });
  }
  return blocks;
}

function DatasetRenderingHeader({
  dataset,
  open,
  onOpenChange,
  children,
}: {
  dataset: DatasetRenderingHeaderModel;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}) {
  const featureCount = formatFeatureCount(dataset.featureCount);

  return (
    <Collapsible open={open} onOpenChange={onOpenChange}>
      <div
        className="mx-2 mt-1 rounded-md border border-border/70 bg-muted/30"
        data-testid={`dataset-rendering-group-${dataset.datasetId}`}
      >
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex min-h-10 w-full items-center gap-2 px-2 py-1.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`${dataset.datasetName}, ${dataset.entries.length} renderings`}
          >
            {open ? (
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-semibold text-foreground">{dataset.datasetName}</div>
              <div className="mt-0.5 flex min-w-0 items-center gap-1 overflow-hidden">
                <Badge variant="outline" className="h-4 shrink-0 rounded px-1.5 text-[10px] leading-3">
                  {formatRecordType(dataset.recordType)}
                </Badge>
                {dataset.geometryType && (
                  <Badge variant="outline" className="h-4 shrink-0 rounded px-1.5 text-[10px] leading-3">
                    {dataset.geometryType}
                  </Badge>
                )}
                {featureCount && (
                  <span className="truncate text-[10px] text-muted-foreground">{featureCount}</span>
                )}
              </div>
            </div>
            <Badge variant="secondary" className="h-5 shrink-0 rounded px-2 text-[10px]">
              {dataset.entries.length} renderings
            </Badge>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="border-t border-border/60 py-1">
            {children}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

function makeBlankBasemap(label: string): BasemapEntry {
  return {
    id: BLANK_BASEMAP_ID,
    label,
    url: BLANK_BASEMAP_ID,
    enabled: true,
    is_preset: false,
  };
}

function currentBasemapEntry(options: BasemapEntry[], basemapStyle: string) {
  return options.find((entry) => entry.id === basemapStyle) ?? {
    id: basemapStyle,
    label: basemapStyle || 'Basemap',
    url: basemapStyle,
    enabled: true,
    is_preset: false,
  };
}

function BasemapInlineControls({
  basemapStyle,
  showBasemapLabels,
  basemapConfig,
  options,
  onBasemapChange,
  onBasemapLabelsChange,
  onBasemapConfigChange,
}: {
  basemapStyle: string;
  showBasemapLabels: boolean;
  basemapConfig: MapBasemapConfig | null;
  options: BasemapEntry[];
  onBasemapChange: (key: string) => void;
  onBasemapLabelsChange: (show: boolean) => void;
  onBasemapConfigChange: (value: MapBasemapConfig) => void;
}) {
  const { t } = useTranslation('builder');
  const current = currentBasemapEntry(options, basemapStyle);
  const normalizedConfig = useMemo(
    () => normalizeBasemapConfig(basemapConfig, showBasemapLabels),
    [basemapConfig, showBasemapLabels],
  );

  function handleSwap(entry: BasemapEntry) {
    const nextConfig = normalizeBasemapConfig(normalizedConfig, showBasemapLabels);
    onBasemapChange(entry.id);
    onBasemapLabelsChange(nextConfig.label_mode !== 'hidden');
    onBasemapConfigChange(nextConfig);
  }

  function handleReset() {
    const resetConfig = normalizeBasemapConfig(null, true);
    onBasemapLabelsChange(true);
    onBasemapConfigChange(resetConfig);
  }

  return (
    <div
      className="mx-2 mb-2 rounded-md border border-border/70 bg-muted/20 py-2"
      data-testid="basemap-inline-controls"
    >
      <BasemapAppearanceControls
        value={normalizedConfig}
        showBasemapLabels={showBasemapLabels}
        onChange={onBasemapConfigChange}
        onShowBasemapLabelsChange={onBasemapLabelsChange}
      />
      <div className="mt-3 flex items-center justify-between gap-2 border-t border-border/60 px-2 pt-2">
        <div className="flex min-w-0 items-center gap-2">
          <img
            src={basemapThumbnail(current.id)}
            alt=""
            aria-hidden="true"
            className="h-7 w-7 shrink-0 rounded border object-cover"
          />
          <span className="truncate text-xs text-muted-foreground">{current.label}</span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Popover>
            <PopoverTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 gap-1 px-2 text-xs"
                aria-label={t('basemap.swap', { defaultValue: 'Swap basemap' })}
              >
                <Shuffle className="h-3.5 w-3.5" aria-hidden="true" />
                {t('basemap.swapShort', { defaultValue: 'Swap' })}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-64 p-2">
              <div className="grid grid-cols-2 gap-2">
                {options.map((entry) => (
                  <Button
                    key={entry.id}
                    type="button"
                    variant={entry.id === basemapStyle ? 'secondary' : 'ghost'}
                    className="h-auto min-h-16 justify-start gap-2 rounded p-2 text-left"
                    aria-label={`Swap to ${entry.label}`}
                    disabled={entry.id === basemapStyle}
                    onClick={() => handleSwap(entry)}
                  >
                    <img
                      src={basemapThumbnail(entry.id)}
                      alt=""
                      aria-hidden="true"
                      className="h-9 w-9 shrink-0 rounded border object-cover"
                    />
                    <span className="min-w-0 truncate text-xs">{entry.label}</span>
                  </Button>
                ))}
              </div>
            </PopoverContent>
          </Popover>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-xs"
            aria-label={t('basemap.resetAppearance', { defaultValue: 'Reset basemap appearance' })}
            onClick={handleReset}
          >
            <RefreshCcw className="h-3.5 w-3.5" aria-hidden="true" />
            {t('common.reset', { defaultValue: 'Reset' })}
          </Button>
        </div>
      </div>
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
  onOpacityChange,
  onLayoutChange,
  onRenderAsChange,
  onDuplicateRendering,
  onAddDataClick,
  onBasemapChange,
  onBasemapLabelsChange,
  onBasemapConfigChange,
  onTerrainChange,
}: MapStackPanelProps) {
  const { t } = useTranslation('builder');
  const { data: basemaps } = useBasemaps();
  const basemapOptions = useMemo(() => {
    const blank = makeBlankBasemap(t('basemap.blank', { defaultValue: 'No basemap' }));
    const enabled = (basemaps ?? []).filter((entry) => entry.enabled);
    return [blank, ...enabled];
  }, [basemaps, t]);
  const basemapLabel = currentBasemapEntry(basemapOptions, basemapStyle).label;
  const stackGroups = useMemo(
    () => buildMapStack({
      basemap_style: basemapStyle,
      basemap_label: basemapLabel,
      show_basemap_labels: showBasemapLabels,
      basemap_config: basemapConfig,
      terrain_config: terrainConfig,
      layers,
      widgets,
    }),
    [basemapConfig, basemapLabel, basemapStyle, layers, showBasemapLabels, terrainConfig, widgets],
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

  const handleUseAsTerrain = useCallback((layerId: string) => {
    const layer = layers.find((candidate) => candidate.id === layerId);
    if (!layer || !canUseLayerAsTerrain(layer)) return;
    onTerrainChange({
      enabled: true,
      source_dataset_id: layer.dataset_id,
      exaggeration: terrainConfig?.exaggeration ?? 1,
    });
  }, [layers, onTerrainChange, terrainConfig?.exaggeration]);

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
      onOpacityChange,
      onLayoutChange,
      onRenderAsChange,
      onDuplicateRendering,
      onUseAsTerrain: handleUseAsTerrain,
    }),
    [
      handleUseAsTerrain,
      onDuplicateRendering,
      onLayoutChange,
      onMoveDown,
      onMoveUp,
      onOpacityChange,
      onRemove,
      onRename,
      onToggleExpand,
      onToggleLegend,
      onToggleVisibility,
      onRenderAsChange,
      onZoomToLayer,
    ],
  );

  function renderEntry(entry: MapStackEntry) {
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
        onOpacityChange={onOpacityChange}
        onLayoutChange={onLayoutChange}
        onRenderAsChange={onRenderAsChange}
        onDuplicateRendering={onDuplicateRendering}
        onUseAsTerrain={handleUseAsTerrain}
        onOpenInspector={onToggleExpand}
        onToggleBasemapLabels={entry.role === 'basemap-labels' ? onBasemapLabelsChange : undefined}
      />
    );
  }

  function renderSectionExtras(group: MapStackGroup) {
    if (group.id === 'relief') {
      const visibleReliefCount = visibleDemReliefLayerCount(layers);
      return (
        <div className="space-y-2 px-2 pb-2 pt-1">
          <TerrainControls
            layers={layers}
            value={terrainConfig}
            onChange={onTerrainChange}
          />
          <div className="px-2 text-xs leading-snug text-muted-foreground">
            {visibleReliefCount > 0
              ? t('mapStack.reliefStatus.active', {
                count: visibleReliefCount,
                defaultValue: visibleReliefCount === 1
                  ? '{{count}} visible DEM-derived relief layer'
                  : '{{count}} visible DEM-derived relief layers',
              })
              : t('mapStack.reliefStatus.empty', {
                defaultValue: 'No visible DEM-derived relief layer',
              })}
          </div>
        </div>
      );
    }
    if (group.id === 'basemap') {
      return (
        <BasemapInlineControls
          basemapStyle={basemapStyle}
          showBasemapLabels={showBasemapLabels}
          basemapConfig={basemapConfig}
          options={basemapOptions}
          onBasemapChange={onBasemapChange}
          onBasemapLabelsChange={onBasemapLabelsChange}
          onBasemapConfigChange={onBasemapConfigChange}
        />
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
  const hasUserLayers = layers.length > 0;
  const title = t('mapStack.title', { defaultValue: 'Map Stack' });
  const [collapsedDatasets, setCollapsedDatasets] = useState<Set<string>>(() => new Set());

  function renderDataGroupEntries(group: MapStackGroup) {
    return buildDataRenderBlocks(group.entries).map((block) => {
      if (block.kind === 'entry') return renderEntry(block.entry);

      const { dataset } = block;
      const open = !collapsedDatasets.has(dataset.datasetId);
      return (
        <DatasetRenderingHeader
          key={`dataset:${dataset.datasetId}`}
          dataset={dataset}
          open={open}
          onOpenChange={(nextOpen) => {
            setCollapsedDatasets((prev) => {
              const next = new Set(prev);
              if (nextOpen) next.delete(dataset.datasetId);
              else next.add(dataset.datasetId);
              return next;
            });
          }}
        >
          {dataset.entries.map((entry) => renderEntry(entry))}
        </DatasetRenderingHeader>
      );
    });
  }

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

      {!hasUserLayers && (
        <section
          aria-label={t('mapStack.empty.title', { defaultValue: 'Start with data' })}
          data-testid="map-stack-empty-data-first"
          className="mx-2 mb-2 rounded-md border border-dashed border-primary/40 bg-primary/5 p-3"
        >
          <h3 className="text-sm font-semibold text-foreground">
            {t('mapStack.empty.title', { defaultValue: 'Start with data' })}
          </h3>
          <p className="mt-1 text-xs leading-snug text-muted-foreground">
            {t('mapStack.empty.description', {
              defaultValue: 'Add a dataset first, then tune terrain, basemap, labels, and interactions around it.',
            })}
          </p>
          <Button
            variant="default"
            size="sm"
            className="mt-3 h-9 w-full gap-1 text-xs"
            onClick={onAddDataClick}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            {t('layers.addData')}
          </Button>
        </section>
      )}

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
              {group.id === 'data'
                ? renderDataGroupEntries(group)
                : group.entries.map((entry) => renderEntry(entry))}
              {renderSectionExtras(group)}
            </MapStackSection>
          ))}
        </SortableContext>
      </DndContext>
    </div>
  );
});
