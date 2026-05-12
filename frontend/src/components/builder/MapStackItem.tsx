import { memo, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core';
import {
  ArrowDown,
  ArrowUp,
  Box,
  ChevronRight,
  ExternalLink,
  Eye,
  EyeOff,
  GripVertical,
  Layers,
  Locate,
  Lock,
  Map,
  MoreVertical,
  Mountain,
  MousePointer2,
  Pencil,
  Tags,
  Trash2,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { ColorizedGeometryIcon, extractStyleHints, getLayerColors } from '@/components/map/layer-icons';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { cn } from '@/lib/utils';
import type { MapStackBadgeTone, MapStackEntry } from '@/components/builder/map-stack';
import type { MapLayerResponse } from '@/types/api';

type DisplayBadge = { label: string; tone: MapStackBadgeTone };

interface DragHandleProps {
  attributes: DraggableAttributes;
  listeners?: DraggableSyntheticListeners;
  setActivatorNodeRef?: (node: HTMLButtonElement | null) => void;
}

interface MapStackItemProps {
  entry: MapStackEntry;
  layer?: MapLayerResponse;
  isActive?: boolean;
  isFirst?: boolean;
  isLast?: boolean;
  dragHandleProps?: DragHandleProps;
  style?: CSSProperties;
  onToggleVisibility: (id: string) => void;
  onMoveUp: (id: string) => void;
  onMoveDown: (id: string) => void;
  onRename: (layerId: string, newName: string | null) => void;
  onRemove: (id: string) => void;
  onZoomToLayer: (id: string) => void;
  onToggleLegend: (id: string) => void;
  onOpenInspector: (id: string) => void;
  onToggleBasemapLabels?: (show: boolean) => void;
}

const BADGE_TONE_CLASSES: Record<MapStackBadgeTone, string> = {
  neutral: 'border-border/60 bg-background text-muted-foreground',
  muted: 'border-border/50 bg-muted text-muted-foreground',
  info: 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-300',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300',
  warning: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300',
  danger: 'border-destructive/40 bg-destructive/10 text-destructive',
};

function primaryLayerTitle(layer: MapLayerResponse) {
  return layer.display_name || layer.dataset_name || layer.dataset_table_name || 'Untitled layer';
}

function isPrimaryLayerEntry(entry: MapStackEntry) {
  return entry.role === 'data-layer' || entry.role.startsWith('relief-');
}

function canOpenInspector(entry: MapStackEntry, layer?: MapLayerResponse) {
  return Boolean(
    layer
      && (
        isPrimaryLayerEntry(entry)
        || entry.role === 'data-labels'
        || entry.role === 'interaction-popups'
      ),
  );
}

function translatedEntryTitle(
  entry: MapStackEntry,
  layer: MapLayerResponse | undefined,
  t: (key: string, options?: Record<string, unknown>) => string,
) {
  if (isPrimaryLayerEntry(entry) && layer) return primaryLayerTitle(layer);
  if (entry.role === 'data-labels' && layer) {
    return t('mapStack.entries.dataLabels', {
      name: primaryLayerTitle(layer),
      defaultValue: '{{name}} labels',
    });
  }
  if (entry.role === 'interaction-popups' && layer) {
    return t('mapStack.entries.layerPopup', {
      name: primaryLayerTitle(layer),
      defaultValue: '{{name}} popup',
    });
  }

  const keyByRole: Partial<Record<MapStackEntry['role'], { key: string; defaultValue: string }>> = {
    'surface-background': { key: 'mapStack.entries.baseBackground', defaultValue: entry.title },
    'surface-terrain': {
      key: entry.metadata.terrain?.sourceStatus === 'missing'
        ? 'mapStack.entries.terrainMissing'
        : 'mapStack.entries.terrainSource',
      defaultValue: entry.title,
    },
    'basemap-preset': { key: 'mapStack.entries.basemapPreset', defaultValue: 'Preset' },
    'basemap-labels': { key: 'mapStack.entries.basemapLabels', defaultValue: 'Place labels' },
    'interaction-widgets': { key: 'mapStack.entries.mapWidgets', defaultValue: entry.title },
  };
  const translation = keyByRole[entry.role];
  return translation ? t(translation.key, { defaultValue: translation.defaultValue }) : entry.title;
}

function translatedSubtitle(
  entry: MapStackEntry,
  t: (key: string, options?: Record<string, unknown>) => string,
) {
  if (!entry.subtitle) return null;
  if (entry.role === 'basemap-labels') {
    return entry.visible
      ? t('mapStack.subtitles.basemapLabelsVisible', { defaultValue: 'Above data geometry' })
      : t('mapStack.subtitles.hiddenByMap', { defaultValue: 'Hidden by map setting' });
  }
  if (entry.role === 'surface-background') {
    return t('mapStack.subtitles.surfaceBackground', { defaultValue: 'Foundation' });
  }
  if (entry.role === 'interaction-popups') {
    return t('mapStack.subtitles.featureClick', { defaultValue: 'Feature click' });
  }
  return entry.subtitle;
}

function translateBadgeLabel(
  label: string,
  t: (key: string, options?: Record<string, unknown>) => string,
) {
  const copyMatch = /^Copy (\d+) of (\d+)$/i.exec(label);
  if (copyMatch) {
    return t('mapStack.badges.copy', {
      index: copyMatch[1],
      count: copyMatch[2],
      defaultValue: 'Copy {{index}} of {{count}}',
    });
  }
  const widgetMatch = /^(\d+) widgets?$/i.exec(label);
  if (widgetMatch) {
    const count = Number(widgetMatch[1]);
    return t('mapStack.badges.widgets', {
      count,
      defaultValue: count === 1 ? '{{count}} widget' : '{{count}} widgets',
    });
  }

  const known: Record<string, string> = {
    background: 'background',
    terrain: 'terrain',
    'fallback source': 'fallbackSource',
    'missing source': 'missingSource',
    hillshade: 'hillshade',
    heatmap: 'heatmap',
    symbol: 'symbol',
    dem: 'dem',
    hidden: 'hidden',
    'legend hidden': 'legendHidden',
    labels: 'labels',
    popup: 'popup',
    'data labels': 'dataLabels',
    'hidden layer': 'hiddenLayer',
    preset: 'preset',
    raster: 'raster',
    layer: 'layer',
    selected: 'selected',
    locked: 'locked',
    disabled: 'disabled',
    unsupported: 'unsupported',
    'needs attention': 'needsAttention',
  };
  const key = known[label.trim().toLowerCase()];
  return key ? t(`mapStack.badges.${key}`, { defaultValue: label }) : label;
}

function RoleIcon({
  entry,
  layer,
}: {
  entry: MapStackEntry;
  layer?: MapLayerResponse;
}) {
  const layerColors = useMemo(() => layer ? getLayerColors(layer) : null, [layer]);
  const caps = useMemo(() => layer ? getLayerCapabilities(layer) : null, [layer]);
  const styleHints = useMemo(
    () => layer
      ? extractStyleHints(
        layer.paint ?? {},
        layer.layout ?? {},
        layer.dataset_geometry_type,
        layer.opacity,
        layer.style_config,
      )
      : null,
    [layer],
  );

  if (layer && layerColors && caps && styleHints) {
    return (
      <ColorizedGeometryIcon
        geometryType={layer.dataset_geometry_type}
        colors={layerColors}
        layerId={layer.id}
        layerType={caps.kind}
        styleHints={styleHints}
      />
    );
  }

  const iconClass = 'h-4 w-4 text-muted-foreground';
  if (entry.role === 'surface-terrain') return <Mountain className={iconClass} aria-hidden="true" />;
  if (entry.role === 'basemap-preset') return <Map className={iconClass} aria-hidden="true" />;
  if (entry.role === 'basemap-labels' || entry.role === 'data-labels') return <Tags className={iconClass} aria-hidden="true" />;
  if (entry.role === 'interaction-popups') return <MousePointer2 className={iconClass} aria-hidden="true" />;
  if (entry.role === 'interaction-widgets') return <Box className={iconClass} aria-hidden="true" />;
  return <Layers className={iconClass} aria-hidden="true" />;
}

export const MapStackItem = memo(function MapStackItem({
  entry,
  layer,
  isActive = false,
  isFirst = false,
  isLast = false,
  dragHandleProps,
  style,
  onToggleVisibility,
  onMoveUp,
  onMoveDown,
  onRename,
  onRemove,
  onZoomToLayer,
  onToggleLegend,
  onOpenInspector,
  onToggleBasemapLabels,
}: MapStackItemProps) {
  const { t } = useTranslation('builder');
  const primaryLayer = isPrimaryLayerEntry(entry) && layer ? layer : null;
  const [editing, setEditing] = useState(false);
  const displayTitle = translatedEntryTitle(entry, layer, t);
  const subtitle = translatedSubtitle(entry, t);
  const [nameValue, setNameValue] = useState(displayTitle);
  const showInspectorButton = canOpenInspector(entry, layer);
  const capabilities = useMemo(() => primaryLayer ? getLayerCapabilities(primaryLayer) : null, [primaryLayer]);
  const isUnsupported = Boolean(
    primaryLayer
      && capabilities
      && capabilities.kind === 'vector'
      && !capabilities.supportsStyleEditor,
  );
  const terrainStatus = entry.metadata.terrain?.sourceStatus;
  const isDisabled = terrainStatus === 'disabled';
  const needsAttention = terrainStatus === 'missing';

  useEffect(() => {
    if (!editing) setNameValue(displayTitle);
  }, [displayTitle, editing]);

  function commitRename() {
    if (!primaryLayer) return;
    setEditing(false);
    const trimmed = nameValue.trim();
    const nextName = trimmed || primaryLayerTitle(primaryLayer);
    if (nextName !== primaryLayer.display_name) {
      onRename(primaryLayer.id, nextName);
    }
    setNameValue(nextName);
  }

  const translatedBadges = entry.badges.map((badge) => ({
    ...badge,
    label: translateBadgeLabel(badge.label, t),
  }));
  const stateBadges: Array<DisplayBadge | null> = [
    isActive ? { label: translateBadgeLabel('Selected', t), tone: 'info' as const } : null,
    entry.locked ? { label: translateBadgeLabel('Locked', t), tone: 'muted' as const } : null,
    isDisabled ? { label: translateBadgeLabel('Disabled', t), tone: 'muted' as const } : null,
    isUnsupported ? { label: translateBadgeLabel('Unsupported', t), tone: 'warning' as const } : null,
    needsAttention ? { label: translateBadgeLabel('Needs attention', t), tone: 'danger' as const } : null,
  ];
  const allBadges = [...stateBadges.filter((badge): badge is DisplayBadge => badge !== null), ...translatedBadges];
  const visibleBadges = allBadges.slice(0, 3);
  const hiddenBadgeCount = Math.max(allBadges.length - visibleBadges.length, 0);
  const hideLayerLabel = t('layerItem.hideLayer', { defaultValue: 'Hide layer' });
  const showLayerLabel = t('layerItem.showLayer', { defaultValue: 'Show layer' });
  const openInspectorLabel = t('layerItem.expandOptions', { defaultValue: 'Expand options' });
  const showOrderLabel = Boolean(primaryLayer);
  const rowLabel = [
    displayTitle,
    entry.orderLabel,
    ...allBadges.map((badge) => badge.label),
  ].filter(Boolean).join(', ');
  const canRename = Boolean(primaryLayer);
  const rowState = needsAttention
    ? 'error'
    : isUnsupported
      ? 'unsupported'
      : isDisabled
        ? 'disabled'
        : isActive
          ? 'selected'
          : !entry.visible
            ? 'hidden'
            : entry.locked
              ? 'locked'
              : 'normal';

  return (
    <div
      style={style}
      role="group"
      aria-label={rowLabel}
      data-state={rowState}
      data-locked={entry.locked ? 'true' : undefined}
      data-visible={entry.visible ? 'true' : 'false'}
      data-testid={primaryLayer ? `layer-item-${primaryLayer.id}` : 'map-stack-item'}
      className={cn(
        'group/map-stack-row px-2 transition-[opacity,background-color] duration-200',
        !entry.visible && 'opacity-60',
      )}
    >
      <div
        className={cn(
          'grid min-h-[56px] grid-cols-[1.5rem_1.75rem_minmax(0,1fr)_auto] items-center gap-1.5 rounded-md border py-1.5 pe-1.5 transition-colors focus-within:ring-2 focus-within:ring-ring',
          isActive ? 'border-primary/50 bg-accent/70' : 'border-transparent hover:bg-accent/40',
          needsAttention && 'border-destructive/40 bg-destructive/5',
          isUnsupported && 'border-amber-300/60 bg-amber-50/50 dark:border-amber-900/60 dark:bg-amber-950/20',
        )}
      >
        {dragHandleProps ? (
          <button
            ref={dragHandleProps.setActivatorNodeRef}
            type="button"
            {...dragHandleProps.attributes}
            {...dragHandleProps.listeners}
            className="flex h-7 w-6 cursor-grab items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring active:cursor-grabbing"
            aria-label={t('layerItem.dragToReorder')}
            aria-roledescription={t('layerItem.sortableLayer')}
          >
            <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        ) : entry.locked ? (
          <span className="flex h-7 w-6 items-center justify-center text-muted-foreground">
            <Lock className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
        ) : (
          <span className="h-7 w-6" aria-hidden="true" />
        )}

        {primaryLayer ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => onToggleVisibility(primaryLayer.id)}
                aria-label={entry.visible ? hideLayerLabel : showLayerLabel}
              >
                {entry.visible ? (
                  <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                  <EyeOff className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top" className="text-xs">
              {entry.visible ? hideLayerLabel : showLayerLabel}
            </TooltipContent>
          </Tooltip>
        ) : (
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-muted/60">
            <RoleIcon entry={entry} layer={layer} />
          </span>
        )}

        <div className="flex min-w-0 items-center gap-2">
          {primaryLayer && (
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted/60">
              <RoleIcon entry={entry} layer={primaryLayer} />
            </span>
          )}
          <div className="min-w-0 flex-1">
            {editing && primaryLayer ? (
              <input
                className="h-6 w-full min-w-0 border-b border-primary bg-transparent text-sm outline-none focus:ring-1 focus:ring-ring"
                value={nameValue}
                onChange={(event) => setNameValue(event.target.value)}
                onBlur={commitRename}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') commitRename();
                  if (event.key === 'Escape') {
                    setEditing(false);
                    setNameValue(displayTitle);
                  }
                }}
                // eslint-disable-next-line jsx-a11y/no-autofocus -- triggered by explicit rename action
                autoFocus
              />
            ) : (
              <span
                role={canRename ? 'button' : undefined}
                tabIndex={canRename ? 0 : undefined}
                className={cn(
                  'block truncate text-sm font-medium leading-5 text-foreground',
                  canRename && 'cursor-text rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                )}
                title={canRename ? `${displayTitle} - ${t('layerItem.renameHint')}` : displayTitle}
                aria-label={canRename ? `${displayTitle} - ${t('layerItem.renameHint')}` : undefined}
                onDoubleClick={() => { if (canRename) setEditing(true); }}
                onKeyDown={(event) => {
                  if (canRename && (event.key === 'Enter' || event.key === 'F2')) setEditing(true);
                }}
              >
                {displayTitle}
              </span>
            )}
            <div className="flex h-5 min-w-0 items-center gap-1 overflow-hidden">
              {subtitle && (
                <span className="truncate text-xs text-muted-foreground">
                  {subtitle}
                </span>
              )}
              {showOrderLabel && (
                <span className="shrink-0 text-[10px] uppercase tracking-normal text-muted-foreground/80">
                  {entry.orderLabel}
                </span>
              )}
              {visibleBadges.map((badge) => (
                <Badge
                  key={`${badge.label}-${badge.tone}`}
                  variant="outline"
                  className={cn(
                    'h-4 max-w-24 truncate rounded border px-1.5 text-[10px] leading-3',
                    BADGE_TONE_CLASSES[badge.tone],
                  )}
                >
                  {badge.label}
                </Badge>
              ))}
              {hiddenBadgeCount > 0 && (
                <Badge
                  variant="outline"
                  className="h-4 rounded border border-border/60 bg-muted px-1.5 text-[10px] leading-3 text-muted-foreground"
                >
                  +{hiddenBadgeCount}
                </Badge>
              )}
            </div>
          </div>
        </div>

        <div className="flex h-8 shrink-0 items-center gap-0.5">
          {entry.role === 'basemap-labels' && onToggleBasemapLabels && (
            <Switch
              size="sm"
              checked={entry.visible}
              onCheckedChange={onToggleBasemapLabels}
              aria-label={t('mapStack.actions.toggleBasemapLabels', { defaultValue: 'Toggle basemap labels' })}
            />
          )}
          {showInspectorButton && layer && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  id={`layer-expand-${layer.id}`}
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => onOpenInspector(layer.id)}
                  aria-label={openInspectorLabel}
                  aria-pressed={isActive}
                >
                  <ChevronRight className="h-3.5 w-3.5 rtl-mirror" aria-hidden="true" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top" className="text-xs">
                {openInspectorLabel}
              </TooltipContent>
            </Tooltip>
          )}
          {primaryLayer && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  aria-label={t('layerItem.moreActions')}
                >
                  <MoreVertical className="h-3.5 w-3.5" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setEditing(true)}>
                  <Pencil className="me-2 h-3.5 w-3.5" aria-hidden="true" />
                  {t('layerItem.rename')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => onMoveUp(primaryLayer.id)}
                  disabled={isFirst}
                >
                  <ArrowUp className="me-2 h-3.5 w-3.5" aria-hidden="true" />
                  {t('layerItem.moveUp')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => onMoveDown(primaryLayer.id)}
                  disabled={isLast}
                >
                  <ArrowDown className="me-2 h-3.5 w-3.5" aria-hidden="true" />
                  {t('layerItem.moveDown')}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => onToggleLegend(primaryLayer.id)}>
                  {primaryLayer.show_in_legend === false ? (
                    <EyeOff className="me-2 h-3.5 w-3.5" aria-hidden="true" />
                  ) : (
                    <Eye className="me-2 h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {primaryLayer.show_in_legend === false
                    ? t('layerItem.showInLegend', { defaultValue: 'Show in legend' })
                    : t('layerItem.hideFromLegend', { defaultValue: 'Hide from legend' })}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onZoomToLayer(primaryLayer.id)}>
                  <Locate className="me-2 h-3.5 w-3.5" aria-hidden="true" />
                  {t('layerItem.zoomToLayer')}
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <a
                    href={`/datasets/${primaryLayer.dataset_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ExternalLink className="me-2 h-3.5 w-3.5" aria-hidden="true" />
                    {t('layerItem.openDataset')}
                  </a>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onClick={() => onRemove(primaryLayer.id)}
                >
                  <Trash2 className="me-2 h-3.5 w-3.5" aria-hidden="true" />
                  {t('layerItem.removeLayer')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>
    </div>
  );
});
