import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { ColorizedGeometryIcon, getLayerColors, extractStyleHints } from '@/components/map/layer-icons';
import {
  CategoricalLegend,
  GraduatedColorLegend,
  GraduatedRadiusLegend,
  GraduatedWidthLegend,
  HeatmapLegend,
} from '@/components/map/LegendEntries';
import { MAP_COLORS } from '@/lib/map-colors';
import type { WidgetContext } from '../types';

export function LegendWidget({ ctx }: { ctx: WidgetContext }) {
  const { t } = useTranslation('builder');

  const legendLayers = useMemo(
    () => ctx.layers.filter((l) => l.visible && l.show_in_legend !== false),
    [ctx.layers],
  );

  if (legendLayers.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">{t('widgets.legend.noLayers')}</p>
    );
  }

  return (
    <div className="space-y-0 min-w-44">
      {legendLayers.map((layer, idx) => {
        const outlineColor = layer.paint?.['_outline-color'] as string | undefined;
        const strokeDisabled = !!layer.paint?.['_stroke-disabled'];
        const opacity = layer.opacity ?? 1;
        const swatchStyle = { outlineColor, strokeDisabled, opacity };
        const weightCol = layer.paint?.['_heatmap-weight-column'] as string | undefined;

        return (
          <div key={layer.id}>
            <div className="p-1 text-xs">
              {layer.style_config?.render_mode === 'heatmap' ? (
                <HeatmapLegend
                  name={layer.display_name ?? layer.dataset_name}
                  rampName={(layer.paint?.['_heatmap-ramp'] as string) ?? 'YlOrRd'}
                  weightColumn={weightCol}
                  opacity={opacity}
                  lowLabel={t('widgets.legend.low')}
                  highLabel={t('widgets.legend.high')}
                  weightedByLabel={weightCol ? t('widgets.legend.weightedBy', { column: weightCol }) : undefined}
                />
              ) : layer.style_config?.column ? (
                <>
                  <div className="font-medium text-foreground mb-1 truncate">
                    {layer.display_name ?? layer.dataset_name}
                  </div>

                  {layer.style_config.mode === 'categorical' && layer.style_config.categories && (
                    <CategoricalLegend
                      categories={layer.style_config.categories}
                      geometryType={layer.dataset_geometry_type}
                      style={swatchStyle}
                    />
                  )}

                  {layer.style_config.mode === 'graduated' &&
                    layer.style_config.breaks && (
                      <GraduatedLegendSwitch
                        styleConfig={layer.style_config}
                        paint={layer.paint ?? {}}
                        style={swatchStyle}
                        geometryType={layer.dataset_geometry_type}
                      />
                    )}
                </>
              ) : (
                <div className="flex items-center gap-1.5">
                  <ColorizedGeometryIcon
                    geometryType={layer.dataset_geometry_type ?? null}
                    colors={getLayerColors({
                      dataset_geometry_type: layer.dataset_geometry_type ?? null,
                      paint: layer.paint ?? {},
                      style_config: layer.style_config,
                    })}
                    layerId={`legend-widget-${idx}`}
                    layerType={layer.layer_type ?? undefined}
                    styleHints={extractStyleHints(
                      layer.paint ?? {},
                      layer.layout ?? {},
                      layer.dataset_geometry_type ?? null,
                      opacity,
                    )}
                  />
                  <span className="font-medium text-foreground truncate">
                    {layer.display_name ?? layer.dataset_name}
                  </span>
                </div>
              )}
            </div>
            {idx < legendLayers.length - 1 && <div className="border-b" />}
          </div>
        );
      })}
    </div>
  );
}

/** Extract color strings from a MapLibre step/match/interpolate expression. */
function extractColorsFromExpression(expr: unknown): string[] | null {
  if (!Array.isArray(expr) || expr.length < 4) return null;
  if (expr[0] === 'step') {
    // ["step", input, initial, stop1, val1, ...] — values at even positions starting from [2]
    const colors: string[] = [];
    if (typeof expr[2] === 'string') colors.push(expr[2]);
    for (let i = 4; i < expr.length; i += 2) {
      if (typeof expr[i] === 'string') colors.push(expr[i]);
    }
    return colors.length > 0 ? colors : null;
  }
  if (expr[0] === 'interpolate') {
    // ["interpolate", interp, input, stop0, val0, stop1, val1, ...]
    const colors: string[] = [];
    for (let i = 4; i < expr.length; i += 2) {
      if (typeof expr[i] === 'string') colors.push(expr[i]);
    }
    return colors.length > 0 ? colors : null;
  }
  return null;
}

/** Picks the right graduated sub-legend based on target (color/radius/width). */
function GraduatedLegendSwitch({
  styleConfig,
  paint,
  style,
  geometryType,
}: {
  styleConfig: { breaks?: number[]; target?: string; sizes?: number[]; colors?: string[] };
  paint: Record<string, unknown>;
  style: { outlineColor?: string; strokeDisabled: boolean; opacity: number };
  geometryType?: string | null;
}) {
  const breaks = styleConfig.breaks!;

  if (styleConfig.target === 'radius' && styleConfig.sizes) {
    const raw = paint['circle-color'];
    const circleColor = (typeof raw === 'string' ? raw : undefined) ?? MAP_COLORS.fallback;
    // Extract per-class colors from paint expression (styleConfig.colors may be
    // absent when DataDrivenStyleEditor saves radius-targeted graduated configs)
    const colors = styleConfig.colors ?? extractColorsFromExpression(raw);
    return (
      <GraduatedRadiusLegend
        sizes={styleConfig.sizes}
        breaks={breaks}
        circleColor={circleColor}
        colors={colors ?? undefined}
        style={style}
      />
    );
  }

  if (styleConfig.target === 'width' && styleConfig.sizes) {
    const raw = paint['line-color'];
    const lineColor = (typeof raw === 'string' ? raw : undefined) ?? MAP_COLORS.fallback;
    return (
      <GraduatedWidthLegend
        sizes={styleConfig.sizes}
        breaks={breaks}
        lineColor={lineColor}
        style={style}
      />
    );
  }

  if (!styleConfig.colors) return null;
  return (
    <GraduatedColorLegend
      colors={styleConfig.colors}
      breaks={breaks}
      geometryType={geometryType}
      style={style}
    />
  );
}

