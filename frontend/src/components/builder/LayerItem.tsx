import { useState, useMemo, memo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Eye,
  EyeOff,
  ArrowUp,
  ArrowDown,
  Trash2,
  GripVertical,
  ExternalLink,
  MoreVertical,
  Pencil,
  Locate,
  ChevronDown,
  ChevronUp,
  Filter,
  Type,
  Paintbrush,
} from 'lucide-react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { LayerStyleEditor } from './LayerStyleEditor';
import { LayerFilterEditor } from './LayerFilterEditor';
import { LabelEditor } from './LabelEditor';
import { RasterLayerControls } from './RasterLayerControls';
import { ColumnsReference } from './ColumnsReference';
import { cn } from '@/lib/utils';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { ColorizedGeometryIcon, getLayerColors, extractStyleHints } from '@/components/map/layer-icons';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, LabelConfig, StyleConfig } from '@/types/api';

/* ---------- Style summary badge helpers ---------- */

function getStyleSummary(layer: MapLayerResponse, t: (key: string, opts?: Record<string, unknown>) => string): string | null {
  const sc = layer.style_config;
  if (!sc?.column) return null;
  if (sc.target === 'radius') return t('style.radiusByColumn', { column: sc.column });
  if (sc.target === 'width') return t('style.widthByColumn', { column: sc.column });
  return t('style.styledBy', { column: sc.column });
}

function getFilterSummary(layer: MapLayerResponse): string | null {
  const f = layer.filter;
  if (!f || !Array.isArray(f) || f.length === 0) return null;
  if (typeof f[0] === 'string' && (f[0] === 'all' || f[0] === 'any')) {
    return `${f[0]} (${f.length - 1})`;
  }
  return '1 rule';
}

function getLabelSummary(layer: MapLayerResponse): string | null {
  const lc = layer.label_config;
  if (!lc?.column) return null;
  return lc.column;
}

interface LayerItemProps {
  layer: MapLayerResponse;
  index: number;
  totalLayers: number;
  isExpanded: boolean;
  activeTab: 'style' | 'filter' | 'labels' | null;
  onToggleExpand: (id: string) => void;
  onTabChange: (layerId: string, tab: 'style' | 'filter' | 'labels') => void;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onFilterChange: (layerId: string, expression: FilterSpecification | null) => void;
  onLabelChange: (layerId: string, config: LabelConfig | null) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onToggleVisibility: (id: string) => void;
  onMoveUp: (id: string) => void;
  onMoveDown: (id: string) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onRemove: (id: string) => void;
  onZoomToLayer: (id: string) => void;
  onToggleLegend: (id: string) => void;
  inspectorMode?: boolean;
}

export const LayerItem = memo(function LayerItem({
  layer,
  index,
  totalLayers,
  isExpanded,
  activeTab,
  onToggleExpand,
  onTabChange,
  onPaintChange,
  onOpacityChange,
  onFilterChange,
  onLabelChange,
  onStyleConfigChange,
  onLayoutChange,
  onToggleVisibility,
  onMoveUp,
  onMoveDown,
  onRename,
  onRemove,
  onZoomToLayer,
  onToggleLegend,
  inspectorMode,
}: LayerItemProps) {
  const { t } = useTranslation('builder');
  const [editing, setEditing] = useState(false);
  const [nameValue, setNameValue] = useState(layer.display_name ?? layer.dataset_name);

  const {
    attributes,
    listeners,
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

  function commit() {
    setEditing(false);
    const newName = nameValue.trim() || null;
    if (newName !== layer.display_name) {
      onRename(layer.id, newName);
    }
  }

  const columns = layer.dataset_column_info ?? [];
  const layerColors = useMemo(() => getLayerColors(layer), [layer]);
  const styleHints = useMemo(
    () => extractStyleHints(
      layer.paint ?? {},
      (layer.layout as Record<string, unknown>) ?? {},
      layer.dataset_geometry_type,
      layer.opacity,
    ),
    [layer.paint, layer.layout, layer.dataset_geometry_type, layer.opacity],
  );
  const hasActiveFilter = layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0;
  const styleSummary = useMemo(() => getStyleSummary(layer, t), [layer, t]);
  const filterSummary = hasActiveFilter ? getFilterSummary(layer) : null;
  const labelSummary = useMemo(() => getLabelSummary(layer), [layer]);
  const caps = useMemo(() => getLayerCapabilities(layer), [layer]);
  const isRaster = caps.kind !== 'vector';

  return (
    <div ref={setNodeRef} style={style} role="group" aria-label={layer.display_name ?? layer.dataset_name}>
      <div className={cn(
        'flex items-center gap-1.5 px-2 py-1.5 rounded hover:bg-accent/50 group transition-opacity duration-200',
        !layer.visible && 'opacity-50',
      )}>
        <div
          className="shrink-0 cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 rounded"
          {...attributes}
          {...listeners}
          aria-label={t('layerItem.dragToReorder')}
          aria-roledescription={t('layerItem.sortableLayer')}
        >
          <GripVertical className="h-3.5 w-3.5" />
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0 min-h-[44px] min-w-[44px]"
          onClick={() => onToggleVisibility(layer.id)}
          title={layer.visible ? t('layerItem.hideLayer') : t('layerItem.showLayer')}
          aria-label={layer.visible ? t('layerItem.hideLayer') : t('layerItem.showLayer')}
        >
          {layer.visible ? (
            <Eye className="h-3.5 w-3.5" />
          ) : (
            <EyeOff className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </Button>

        <div className="shrink-0">
          <ColorizedGeometryIcon geometryType={layer.dataset_geometry_type} colors={layerColors} layerId={layer.id} layerType={caps.kind} styleHints={styleHints} />
        </div>

        {editing ? (
          <input
            className="flex-1 text-sm bg-transparent border-b border-primary outline-none focus:ring-1 focus:ring-ring min-w-0"
            value={nameValue}
            onChange={(e) => setNameValue(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit();
              if (e.key === 'Escape') {
                setEditing(false);
                setNameValue(layer.display_name ?? layer.dataset_name);
              }
            }}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- intentional: user double-clicked to start inline rename
            autoFocus
          />
        ) : (
          <span
            role="button"
            tabIndex={0}
            className="flex-1 text-sm truncate cursor-text flex items-center gap-1 min-w-0 rounded focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
            onDoubleClick={() => setEditing(true)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === 'F2') setEditing(true); }}
            title={t('layerItem.renameHint')}
            aria-label={`${layer.display_name ?? layer.dataset_name} — ${t('layerItem.renameHint')}`}
          >
            <span className="truncate">{layer.display_name ?? layer.dataset_name}</span>
            {styleSummary && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Paintbrush className="h-3 w-3 shrink-0 text-primary" />
                </TooltipTrigger>
                <TooltipContent side="top" className="text-xs">
                  {styleSummary}
                </TooltipContent>
              </Tooltip>
            )}
            {hasActiveFilter && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Filter className="h-3 w-3 shrink-0 text-primary" />
                </TooltipTrigger>
                <TooltipContent side="top" className="text-xs">
                  {filterSummary}
                </TooltipContent>
              </Tooltip>
            )}
            {labelSummary && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Type className="h-3 w-3 shrink-0 text-primary" />
                </TooltipTrigger>
                <TooltipContent side="top" className="text-xs">
                  {labelSummary}
                </TooltipContent>
              </Tooltip>
            )}
          </span>
        )}

        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0 min-h-[44px] min-w-[44px]"
          onClick={() => onToggleExpand(layer.id)}
          aria-label={isExpanded ? t('layerItem.collapseOptions') : t('layerItem.expandOptions')}
        >
          {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 shrink-0 min-h-[44px] min-w-[44px]"
              aria-label={t('layerItem.moreActions')}
            >
              <MoreVertical className="h-3 w-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => setEditing(true)}>
              <Pencil className="h-3.5 w-3.5 me-2" />
              {t('layerItem.rename')}
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => onMoveUp(layer.id)}
              disabled={index === 0}
            >
              <ArrowUp className="h-3.5 w-3.5 me-2" />
              {t('layerItem.moveUp')}
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => onMoveDown(layer.id)}
              disabled={index === totalLayers - 1}
            >
              <ArrowDown className="h-3.5 w-3.5 me-2" />
              {t('layerItem.moveDown')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => onToggleLegend(layer.id)}>
              {layer.show_in_legend === false ? (
                <EyeOff className="h-3.5 w-3.5 me-2" />
              ) : (
                <Eye className="h-3.5 w-3.5 me-2" />
              )}
              {layer.show_in_legend === false
                ? t('layerItem.showInLegend', { defaultValue: 'Show in legend' })
                : t('layerItem.hideFromLegend', { defaultValue: 'Hide from legend' })}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onZoomToLayer(layer.id)}>
              <Locate className="h-3.5 w-3.5 me-2" />
              {t('layerItem.zoomToLayer')}
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <a
                href={`/datasets/${layer.dataset_id}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                <ExternalLink className="h-3.5 w-3.5 me-2" />
                {t('layerItem.openDataset')}
              </a>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onClick={() => onRemove(layer.id)}
            >
              <Trash2 className="h-3.5 w-3.5 me-2" />
              {t('layerItem.removeLayer')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {isExpanded && !inspectorMode && isRaster && (
        <div className="px-2 pb-2">
          <RasterLayerControls
            opacity={layer.opacity ?? 1}
            onOpacityChange={(v) => onOpacityChange(layer.id, v)}
          />
        </div>
      )}

      {isExpanded && !inspectorMode && !isRaster && (
        <div className="px-2 pb-2">
          <div className="flex gap-1 mb-2 border-b" role="tablist">
            {(['style', 'filter', 'labels'] as const).map((tab) => (
              <button
                key={tab}
                role="tab"
                aria-selected={activeTab === tab}
                className={cn(
                  'px-2 py-1.5 text-xs font-semibold transition-colors',
                  activeTab === tab
                    ? 'text-foreground border-b-2 border-primary'
                    : 'text-muted-foreground hover:text-foreground'
                )}
                onClick={() => onTabChange(layer.id, tab)}
              >
                {t(`layerItem.${tab}Tab`)}
              </button>
            ))}
          </div>
          {activeTab === 'style' && (
            <LayerStyleEditor
              layer={layer}
              onPaintChange={onPaintChange}
              onOpacityChange={onOpacityChange}
              onStyleConfigChange={onStyleConfigChange}
              onLayoutChange={onLayoutChange}
            />
          )}
          {activeTab === 'style' && columns.length > 0 && (
            <ColumnsReference columns={columns} />
          )}
          {activeTab === 'filter' && (
            <LayerFilterEditor
              columnInfo={columns}
              filter={layer.filter ?? null}
              onFilterChange={(expr) => onFilterChange(layer.id, expr)}
            />
          )}
          {activeTab === 'labels' && (
            <LabelEditor
              columns={columns}
              labelConfig={layer.label_config ?? null}
              onLabelChange={(config) => onLabelChange(layer.id, config)}
              geometryType={layer.dataset_geometry_type}
            />
          )}
        </div>
      )}
    </div>
  );
});
