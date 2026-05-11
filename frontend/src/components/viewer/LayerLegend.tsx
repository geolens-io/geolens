import { useEffect, useMemo, useRef } from 'react';
import type { SharedLayerResponse, StyleConfig } from '@/types/api';
import { useTranslation } from 'react-i18next';
import { getLayerColors } from '@/components/map/layer-icons';
import {
  CategoricalLegend,
  GeometrySwatch,
  GraduatedColorLegend,
  GraduatedRadiusLegend,
  GraduatedWidthLegend,
  HeatmapLegend,
} from '@/components/map/LegendEntries';
import type { SwatchStyle } from '@/components/map/LegendEntries';
import { Eye, EyeOff, Layers, X } from 'lucide-react';
import { parseStepOrInterpolate } from '@/lib/normalize-style-config';
import { MAP_COLORS } from '@/lib/map-colors';

interface LayerLegendProps {
  layers: SharedLayerResponse[];
  visibleLayers: Set<number>;
  onToggleVisibility: (sortOrder: number) => void;
  isOpen: boolean;
  onToggle: () => void;
}

/** Build SwatchStyle from viewer layer paint for consistent legend rendering. */
function viewerSwatchStyle(layer: SharedLayerResponse): SwatchStyle {
  const rawOutline = layer.paint?.['_outline-color'];
  const outlineColor = typeof rawOutline === 'string' ? rawOutline : undefined;
  const rawStrokeW = layer.paint?.['circle-stroke-width'] ?? layer.paint?.['_outline-width'];
  const strokeWidth = typeof rawStrokeW === 'number' ? rawStrokeW : undefined;
  const gt = (layer.geometry_type ?? '').toUpperCase();
  const rawFillOp = gt.includes('POINT')
    ? layer.paint?.['circle-opacity']
    : gt.includes('LINE') ? layer.paint?.['line-opacity'] : layer.paint?.['fill-opacity'];
  const fillOpacity = typeof rawFillOp === 'number' ? rawFillOp : undefined;
  return { outlineColor, opacity: layer.opacity ?? 1, fillOpacity, strokeWidth };
}

function parsePaintColors(paintColorValue: unknown): { colors: string[]; breaks: number[] } | null {
  if (typeof paintColorValue === 'string' || !paintColorValue) return null;
  const parsed = parseStepOrInterpolate(paintColorValue);
  if (!parsed || !parsed.values.every((v) => typeof v === 'string')) return null;
  return { colors: parsed.values as string[], breaks: parsed.breaks };
}

function expressionColumn(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  if (value[0] === 'get' && typeof value[1] === 'string') return value[1];
  for (const entry of value) {
    const column = expressionColumn(entry);
    if (column) return column;
  }
  return null;
}

function displayColumn(value: string | undefined): string {
  if (!value) return 'value';
  return value
    .replace(/^_+/, '')
    .replace(/_/g, ' ')
    .replace(/\bmhi\b/i, 'income')
    .replace(/\bkm\b/i, 'km');
}

function colorPaintKey(geometryType: string | null | undefined): string {
  const gt = (geometryType ?? '').toUpperCase();
  if (gt.includes('POINT')) return 'circle-color';
  if (gt.includes('LINE')) return 'line-color';
  return 'fill-color';
}

function GraduatedLegend({
  layer,
  styleConfig,
  swatchStyle,
}: {
  layer: SharedLayerResponse;
  styleConfig: StyleConfig;
  swatchStyle: SwatchStyle;
}) {
  const paint = layer.paint ?? {};
  const breaks = styleConfig.breaks ?? [];
  const metricLabel = styleConfig.sizeLabel ?? displayColumn(styleConfig.column);
  const rawColor = paint[colorPaintKey(layer.geometry_type)];
  const parsedColor = parsePaintColors(rawColor);
  const colorColumn = expressionColumn(rawColor);

  if (styleConfig.target === 'radius' && styleConfig.sizes) {
    return (
      <div className="space-y-1">
        <div className="text-[11px] font-medium text-muted-foreground">
          Size: {metricLabel}
        </div>
        <GraduatedRadiusLegend
          sizes={styleConfig.sizes}
          breaks={breaks}
          circleColor={parsedColor?.colors[0] ?? MAP_COLORS.fallback}
          style={swatchStyle}
        />
        {parsedColor && colorColumn && colorColumn !== styleConfig.column && (
          <>
            <div className="pt-1 text-[11px] font-medium text-muted-foreground">
              Color: {styleConfig.colorLabel ?? displayColumn(colorColumn)}
            </div>
            <GraduatedColorLegend
              colors={parsedColor.colors}
              breaks={parsedColor.breaks}
              geometryType={layer.geometry_type}
              style={swatchStyle}
            />
          </>
        )}
      </div>
    );
  }

  if (styleConfig.target === 'width' && styleConfig.sizes) {
    const rawLineColor = paint['line-color'];
    return (
      <div className="space-y-1">
        <div className="text-[11px] font-medium text-muted-foreground">
          Width: {metricLabel}
        </div>
        <GraduatedWidthLegend
          sizes={styleConfig.sizes}
          breaks={breaks}
          lineColor={(typeof rawLineColor === 'string' ? rawLineColor : undefined) ?? MAP_COLORS.fallback}
          style={swatchStyle}
        />
      </div>
    );
  }

  if (!styleConfig.colors) return null;
  return (
    <GraduatedColorLegend
      colors={styleConfig.colors}
      breaks={breaks}
      geometryType={layer.geometry_type}
      style={swatchStyle}
    />
  );
}

export function LayerLegend({
  layers,
  visibleLayers,
  onToggleVisibility,
  isOpen,
  onToggle,
}: LayerLegendProps) {
  const { t } = useTranslation('common');
  const panelRef = useRef<HTMLDivElement>(null);

  const sorted = useMemo(
    () =>
      [...layers]
        .filter((l) => l.show_in_legend !== false)
        .sort((a, b) => a.sort_order - b.sort_order),
    [layers],
  );

  // Dismiss on Escape
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onToggle();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onToggle]);

  return (
    <>
      {/* Toggle button — always visible */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-controls="layer-legend-panel"
        aria-label={isOpen ? t('viewer.legend.hide') : t('viewer.legend.show')}
        className="absolute left-3 top-3 z-20 flex items-center justify-center w-8 h-8 rounded-md bg-background/80 backdrop-blur-sm border border-border/50 shadow-sm text-foreground hover:bg-background transition-colors"
      >
        {isOpen ? <X className="w-4 h-4" aria-hidden="true" /> : <Layers className="w-4 h-4" aria-hidden="true" />}
      </button>

      {/* Legend panel — shown when open */}
      <div
        ref={panelRef}
        id="layer-legend-panel"
        role="region"
        aria-label={t('viewer.legend.title')}
        className={`absolute left-3 top-14 z-10 w-64 max-h-[calc(100vh-5rem)] overflow-y-auto bg-background/90 backdrop-blur-md rounded-lg shadow-lg border border-border/50 transition-[opacity,transform] duration-200 ease-out ${
          isOpen
            ? 'opacity-100 translate-y-0'
            : 'opacity-0 -translate-y-2 pointer-events-none'
        }`}
      >
        <div className="p-3 border-b border-border/50">
          <h3 className="text-sm font-semibold text-foreground">{t('viewer.legend.title')}</h3>
        </div>
        <ul className="divide-y divide-border/50">
          {sorted.map((layer) => {
            const isVisible = visibleLayers.has(layer.sort_order);
            const sc = layer.style_config;
            const isHeatmap = sc?.render_mode === 'heatmap';
            const color = isHeatmap ? null : getLayerColors({
              dataset_geometry_type: layer.geometry_type ?? null,
              paint: layer.paint ?? {},
              style_config: sc,
            })[0];
            const layerName = layer.display_name || layer.dataset_name;
            return (
              <li key={layer.sort_order} className="px-3 py-2 hover:bg-accent/50">
                <div className="flex items-center gap-2">
                  {color && (
                    <GeometrySwatch geometryType={layer.geometry_type} color={color} />
                  )}
                  <span className="text-sm text-foreground flex-1 line-clamp-2" title={layerName}>
                    {layerName}
                  </span>
                  <button
                    type="button"
                    onClick={() => onToggleVisibility(layer.sort_order)}
                    className="flex-shrink-0 p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                    aria-label={isVisible
                      ? t('viewer.legend.hideLayer', { name: layerName })
                      : t('viewer.legend.showLayer', { name: layerName })}
                  >
                    {isVisible ? <Eye className="w-4 h-4" aria-hidden="true" /> : <EyeOff className="w-4 h-4" aria-hidden="true" />}
                  </button>
                </div>

                {/* Data-driven legend entries */}
                {sc?.column && isVisible && (
                  sc?.render_mode === 'heatmap' ? (
                    <div className="mt-1.5 ms-6">
                      <HeatmapLegend
                        name=""
                        rampName={(layer.paint?.['_heatmap-ramp'] as string) ?? sc.ramp ?? 'YlOrRd'}
                        opacity={layer.opacity ?? 1}
                        lowLabel={t('viewer.heatmapLow')}
                        highLabel={t('viewer.heatmapHigh')}
                      />
                    </div>
                  ) : (
                    <div className="mt-1.5 ms-6">
                      {sc.mode === 'categorical' && sc.categories && (
                        <CategoricalLegend categories={sc.categories} geometryType={layer.geometry_type} style={viewerSwatchStyle(layer)} />
                      )}
                      {sc.mode === 'graduated' && (sc.colors || sc.sizes) && (
                        <GraduatedLegend
                          layer={layer}
                          styleConfig={sc}
                          swatchStyle={viewerSwatchStyle(layer)}
                        />
                      )}
                    </div>
                  )
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}
