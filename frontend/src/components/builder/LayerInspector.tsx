import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Settings2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { LayerStyleEditor } from './LayerStyleEditor';
import { LayerFilterEditor } from './LayerFilterEditor';
import { LabelEditor } from './LabelEditor';
import { RasterLayerControls } from './RasterLayerControls';
import { ColumnsReference } from './ColumnsReference';
import { StyleSpecView } from './StyleSpecView';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { cn } from '@/lib/utils';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, LabelConfig, StyleConfig } from '@/types/api';

const ADVANCED_KEY = 'geolens-inspector-advanced';

interface LayerInspectorProps {
  layer: MapLayerResponse;
  activeTab: 'style' | 'filter' | 'labels' | null;
  onTabChange: (layerId: string, tab: 'style' | 'filter' | 'labels') => void;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onFilterChange: (layerId: string, expression: FilterSpecification | null) => void;
  onLabelChange: (layerId: string, config: LabelConfig | null) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onRenderModeChange?: (layerId: string, mode: 'points' | 'heatmap') => void;
  onClose: () => void;
}

export function LayerInspector({
  layer,
  activeTab,
  onTabChange,
  onPaintChange,
  onOpacityChange,
  onFilterChange,
  onLabelChange,
  onStyleConfigChange,
  onLayoutChange,
  onRenderModeChange,
  onClose,
}: LayerInspectorProps) {
  const { t } = useTranslation('builder');
  const columns = layer.dataset_column_info ?? [];
  const caps = getLayerCapabilities(layer);
  const isRaster = caps.kind !== 'vector';
  const effectiveTab = activeTab ?? 'style';

  const [advanced, setAdvanced] = useState(() => {
    try { return localStorage.getItem(ADVANCED_KEY) === '1'; } catch { return false; }
  });

  function toggleAdvanced() {
    const next = !advanced;
    setAdvanced(next);
    try { localStorage.setItem(ADVANCED_KEY, next ? '1' : '0'); } catch { /* noop */ }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-3 border-b flex items-center justify-between shrink-0">
        <div className="min-w-0">
          <h2 className="text-sm font-medium truncate">{layer.display_name ?? layer.dataset_name}</h2>
          <span className="text-xs text-muted-foreground">{t('inspector.title')}</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {!isRaster && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant={advanced ? 'default' : 'ghost'}
                  size="icon-xs"
                  onClick={toggleAdvanced}
                  aria-label={t('inspector.toggleAdvanced')}
                >
                  <Settings2 className="h-3.5 w-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-xs">
                {advanced ? t('inspector.basicMode') : t('inspector.advancedMode')}
              </TooltipContent>
            </Tooltip>
          )}
          <Button variant="ghost" size="icon-xs" onClick={onClose} aria-label={t('inspector.close')}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Tabs */}
      {!isRaster && (
        <div className="flex border-b shrink-0" role="tablist" aria-label={t('inspector.title')}>
          {(['style', 'filter', 'labels'] as const).map((tab) => (
            <button
              key={tab}
              id={`inspector-tab-${tab}`}
              role="tab"
              aria-selected={effectiveTab === tab}
              aria-controls="inspector-tabpanel"
              className={cn(
                'flex-1 px-2 py-2 text-xs font-semibold transition-colors',
                effectiveTab === tab
                  ? 'text-foreground border-b-2 border-primary'
                  : 'text-muted-foreground hover:text-foreground'
              )}
              onClick={() => onTabChange(layer.id, tab)}
            >
              {t(`layerItem.${tab}Tab`)}
            </button>
          ))}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3" {...(!isRaster ? { role: 'tabpanel', id: 'inspector-tabpanel', 'aria-labelledby': `inspector-tab-${effectiveTab}` } : {})}>
        {isRaster && (
          <RasterLayerControls
            opacity={layer.opacity ?? 1}
            onOpacityChange={(v) => onOpacityChange(layer.id, v)}
          />
        )}

        {!isRaster && effectiveTab === 'style' && (
          <>
            <LayerStyleEditor
              layer={layer}
              onPaintChange={onPaintChange}
              onOpacityChange={onOpacityChange}
              onStyleConfigChange={onStyleConfigChange}
              onLayoutChange={onLayoutChange}
              onRenderModeChange={onRenderModeChange}
              showAdvanced={advanced}
            />
            {columns.length > 0 && (
              <ColumnsReference columns={columns} defaultOpen={advanced} />
            )}
            {advanced && <StyleSpecView layer={layer} />}
          </>
        )}

        {!isRaster && effectiveTab === 'filter' && (
          <LayerFilterEditor
            columnInfo={columns}
            filter={layer.filter ?? null}
            onFilterChange={(expr) => onFilterChange(layer.id, expr)}
          />
        )}

        {!isRaster && effectiveTab === 'labels' && (
          <LabelEditor
            columns={columns}
            labelConfig={layer.label_config ?? null}
            onLabelChange={(config) => onLabelChange(layer.id, config)}
            geometryType={layer.dataset_geometry_type}
          />
        )}
      </div>
    </div>
  );
}
