import { memo, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft } from 'lucide-react';
import { LayerStyleEditor } from './LayerStyleEditor';
import { LayerFilterEditor } from './LayerFilterEditor';
import { LabelEditor } from './LabelEditor';
import { PopupConfigEditor } from './PopupConfigEditor';
import { RasterLayerControls } from './RasterLayerControls';
import { ColumnsReference } from './ColumnsReference';
import { cn } from '@/lib/utils';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { ColorizedGeometryIcon, getLayerColors, extractStyleHints } from '@/components/map/layer-icons';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, LabelConfig, PopupConfig, StyleConfig } from '@/types/api';

export interface LayerEditorHandlers {
  onTabChange: (layerId: string, tab: 'style' | 'filter' | 'labels' | 'popup') => void;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onFilterChange: (layerId: string, expression: FilterSpecification | null) => void;
  onLabelChange: (layerId: string, config: LabelConfig | null) => void;
  onPopupChange: (layerId: string, config: PopupConfig | null) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onRenderModeChange?: (layerId: string, mode: 'points' | 'heatmap' | 'symbol' | 'cluster') => void;
}

interface LayerEditorPanelProps {
  layer: MapLayerResponse;
  activeTab: 'style' | 'filter' | 'labels' | 'popup' | null;
  handlers: LayerEditorHandlers;
  onBack?: () => void;
}

export const LayerEditorPanel = memo(function LayerEditorPanel({
  layer,
  activeTab,
  handlers,
  onBack,
}: LayerEditorPanelProps) {
  const { t } = useTranslation('builder');
  const columns = layer.dataset_column_info ?? [];
  const caps = useMemo(() => getLayerCapabilities(layer), [layer]);
  const isRaster = caps.kind !== 'vector';
  const isHeatmap = layer.style_config?.render_mode === 'heatmap';
  const layerColors = useMemo(() => getLayerColors(layer), [layer]);
  const styleHints = useMemo(
    () => extractStyleHints(
      layer.paint ?? {},
      layer.layout ?? {},
      layer.dataset_geometry_type,
      layer.opacity,
      layer.style_config,
    ),
    [layer.paint, layer.layout, layer.dataset_geometry_type, layer.opacity, layer.style_config],
  );

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Layer identity header with back button */}
      <div className="flex items-center gap-1.5 px-2 py-2 border-b shrink-0">
        {onBack && (
          <button
            onClick={onBack}
            aria-label={t('layerItem.backToLayers', { defaultValue: 'Back to layers' })}
            title={t('layerItem.backToLayers', { defaultValue: 'Back to layers' })}
            className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronLeft className="h-4 w-4 rtl-mirror" />
          </button>
        )}
        <ColorizedGeometryIcon
          geometryType={layer.dataset_geometry_type}
          colors={layerColors}
          layerId={layer.id}
          layerType={caps.kind}
          styleHints={styleHints}
        />
        <span className="text-sm font-medium truncate">
          {layer.display_name ?? layer.dataset_name}
        </span>
      </div>

      {/* Raster: simple opacity control */}
      {isRaster && (
        <div className="flex-1 overflow-y-auto p-3">
          <RasterLayerControls
            paint={layer.paint ?? {}}
            onPaintChange={(nextPaint) => handlers.onPaintChange(layer.id, nextPaint)}
            opacity={layer.opacity ?? 1}
            onOpacityChange={(v) => handlers.onOpacityChange(layer.id, v)}
            isDem={layer.is_dem}
            styleConfig={layer.style_config}
            onStyleConfigChange={(nextConfig, nextPaint) => handlers.onStyleConfigChange(layer.id, nextConfig, nextPaint)}
          />
        </div>
      )}

      {/* Vector: tabbed editor */}
      {!isRaster && (
        <>
          <div className="flex gap-1 overflow-x-auto px-3.5 border-b shrink-0" role="tablist">
            {(['style', 'filter', 'labels', 'popup'] as const)
              .filter((tab) => {
                if (tab === 'filter') return caps.supportsFilterEditor;
                if (tab === 'labels') return caps.supportsLabelEditor && !isHeatmap;
                if (tab === 'popup') return caps.supportsFilterEditor || caps.supportsLabelEditor;
                return true;
              })
              .map((tab) => (
              <button
                key={tab}
                id={`tab-${layer.id}-${tab}`}
                role="tab"
                aria-selected={activeTab === tab}
                aria-controls={`tabpanel-${layer.id}-${tab}`}
                className={cn(
                  'h-9 shrink-0 cursor-pointer rounded-t-sm px-2.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                  activeTab === tab
                    ? 'text-foreground border-b-2 border-primary'
                    : 'text-muted-foreground hover:text-foreground'
                )}
                onClick={() => handlers.onTabChange(layer.id, tab)}
              >
                {t(`layerItem.${tab}Tab`)}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-3">
            {activeTab === 'style' && (
              <div role="tabpanel" id={`tabpanel-${layer.id}-style`} aria-labelledby={`tab-${layer.id}-style`}>
                <LayerStyleEditor
                  key={layer.id}
                  layer={layer}
                  onPaintChange={handlers.onPaintChange}
                  onOpacityChange={handlers.onOpacityChange}
                  onStyleConfigChange={handlers.onStyleConfigChange}
                  onLayoutChange={handlers.onLayoutChange}
                  onRenderModeChange={handlers.onRenderModeChange}
                />
                {columns.length > 0 && (
                  <ColumnsReference columns={columns} />
                )}
              </div>
            )}
            {activeTab === 'filter' && (
              <div role="tabpanel" id={`tabpanel-${layer.id}-filter`} aria-labelledby={`tab-${layer.id}-filter`}>
                <LayerFilterEditor
                  columnInfo={columns}
                  filter={layer.filter ?? null}
                  layerName={layer.display_name ?? layer.dataset_name}
                  onFilterChange={(expr) => handlers.onFilterChange(layer.id, expr)}
                />
              </div>
            )}
            {activeTab === 'labels' && (
              <div role="tabpanel" id={`tabpanel-${layer.id}-labels`} aria-labelledby={`tab-${layer.id}-labels`}>
                <LabelEditor
                  columns={columns}
                  labelConfig={layer.label_config ?? null}
                  onLabelChange={(config) => handlers.onLabelChange(layer.id, config)}
                  geometryType={layer.dataset_geometry_type}
                />
              </div>
            )}
            {activeTab === 'popup' && (
              <div role="tabpanel" id={`tabpanel-${layer.id}-popup`} aria-labelledby={`tab-${layer.id}-popup`}>
                <PopupConfigEditor
                  key={layer.id}
                  columns={columns}
                  popupConfig={layer.popup_config ?? null}
                  onPopupChange={(config) => handlers.onPopupChange(layer.id, config)}
                />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
});
