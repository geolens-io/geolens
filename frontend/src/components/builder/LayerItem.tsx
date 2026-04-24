import { useState, useEffect, useMemo, memo } from 'react';
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
import { cn } from '@/lib/utils';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { ColorizedGeometryIcon, getLayerColors, extractStyleHints } from '@/components/map/layer-icons';
import type { MapLayerResponse } from '@/types/api';

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
  isFirst: boolean;
  isLast: boolean;
  isExpanded: boolean;
  onToggleExpand: (id: string) => void;
  onToggleVisibility: (id: string) => void;
  onMoveUp: (id: string) => void;
  onMoveDown: (id: string) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onRemove: (id: string) => void;
  onZoomToLayer: (id: string) => void;
  onToggleLegend: (id: string) => void;
}

export const LayerItem = memo(function LayerItem({
  layer,
  isFirst,
  isLast,
  isExpanded,
  onToggleExpand,
  onToggleVisibility,
  onMoveUp,
  onMoveDown,
  onRename,
  onRemove,
  onZoomToLayer,
  onToggleLegend,
}: LayerItemProps) {
  const { t } = useTranslation('builder');
  const [editing, setEditing] = useState(false);
  const [nameValue, setNameValue] = useState(layer.display_name ?? layer.dataset_name);

  // L-09: Resync nameValue when canonical name changes externally (e.g. AI rename)
  useEffect(() => {
    if (!editing) {
      setNameValue(layer.display_name ?? layer.dataset_name);
    }
  }, [layer.display_name, layer.dataset_name, editing]);

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
    const trimmed = nameValue.trim();
    // L-12: If empty, revert to original name instead of persisting null
    const newName = trimmed || (layer.display_name ?? layer.dataset_name);
    if (newName !== layer.display_name) {
      onRename(layer.id, newName);
    }
    setNameValue(newName);
  }

  const layerColors = useMemo(() => getLayerColors(layer), [layer]);
  const styleHints = useMemo(
    () => extractStyleHints(
      layer.paint ?? {},
      layer.layout ?? {},
      layer.dataset_geometry_type,
      layer.opacity,
    ),
    [layer.paint, layer.layout, layer.dataset_geometry_type, layer.opacity],
  );
  const hasActiveFilter = layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0;
  const styleSummary = useMemo(() => getStyleSummary(layer, t), [layer, t]);
  const filterSummary = useMemo(() => hasActiveFilter ? getFilterSummary(layer) : null, [hasActiveFilter, layer]);
  const labelSummary = useMemo(() => getLabelSummary(layer), [layer]);
  const caps = useMemo(() => getLayerCapabilities(layer), [layer]);

  return (
    <div ref={setNodeRef} style={style} role="group" aria-label={layer.display_name ?? layer.dataset_name}>
      <div className={cn(
        'flex items-center gap-1.5 px-2 py-1.5 rounded hover:bg-accent/50 group transition-[opacity,background-color] duration-200',
        !layer.visible && 'opacity-50',
        isExpanded && 'bg-accent/40',
      )}>
        <div
          className="shrink-0 cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 rounded min-w-6 min-h-6 flex items-center justify-center"
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
            className="flex-1 text-sm truncate cursor-text flex items-center gap-1 min-w-0 min-h-[28px] py-0.5 rounded focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
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
          id={`layer-expand-${layer.id}`}
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
              className="h-8 w-8 shrink-0"
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
              disabled={isFirst}
            >
              <ArrowUp className="h-3.5 w-3.5 me-2" />
              {t('layerItem.moveUp')}
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => onMoveDown(layer.id)}
              disabled={isLast}
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
    </div>
  );
});
