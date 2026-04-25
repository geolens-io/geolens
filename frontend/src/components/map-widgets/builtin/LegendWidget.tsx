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
import type { SwatchStyle } from '@/components/map/LegendEntries';
import type { StyleConfig } from '@/types/api';
import { MAP_COLORS } from '@/lib/map-colors';
import { parseStepOrInterpolate } from '@/lib/normalize-style-config';
import type { WidgetContext } from '../types';

/** Extract swatch style properties from layer paint based on geometry type. */
function getSwatchStyleFromPaint(
  paint: Record<string, unknown> | undefined,
  geometryType: string | null | undefined,
  masterOpacity: number,
): SwatchStyle {
  const gt = (geometryType ?? '').toUpperCase();
  const strokeDisabled = !!paint?.['_stroke-disabled'];

  const outlineColor = gt.includes('POINT')
    ? (typeof paint?.['circle-stroke-color'] === 'string' ? paint['circle-stroke-color'] as string : undefined)
    : (typeof paint?.['_outline-color'] === 'string' ? paint['_outline-color'] as string : undefined);

  const rawStrokeW = gt.includes('POINT') ? paint?.['circle-stroke-width'] : paint?.['_outline-width'];
  const strokeWidth = typeof rawStrokeW === 'number' ? rawStrokeW : undefined;

  const rawFillOp = gt.includes('POINT')
    ? paint?.['circle-opacity']
    : gt.includes('LINE')
      ? paint?.['line-opacity']
      : paint?.['fill-opacity'];
  const fillOpacity = typeof rawFillOp === 'number' ? rawFillOp : undefined;

  return { outlineColor, strokeDisabled, opacity: masterOpacity, fillOpacity, strokeWidth };
}

/** Extract colors and breaks from a paint color expression for the legend. */
function parsePaintColors(paintColorValue: unknown): { colors: string[]; breaks: number[] } | null {
  if (typeof paintColorValue === 'string' || !paintColorValue) return null;
  const parsed = parseStepOrInterpolate(paintColorValue);
  if (!parsed || !parsed.values.every((v) => typeof v === 'string')) return null;
  const colors = parsed.values as string[];
  // For interpolate, breaks already has the first stop dropped by parseStepOrInterpolate
  return { colors, breaks: parsed.breaks };
}

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
        const opacity = layer.opacity ?? 1;
        const swatchStyle = getSwatchStyleFromPaint(layer.paint, layer.dataset_geometry_type, opacity);
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

/** Picks the right graduated sub-legend based on target (color/radius/width). */
function GraduatedLegendSwitch({
  styleConfig,
  paint,
  style,
  geometryType,
}: {
  styleConfig: StyleConfig;
  paint: Record<string, unknown>;
  style: SwatchStyle;
  geometryType?: string | null;
}) {
  const breaks = styleConfig.breaks ?? [];

  if (styleConfig.target === 'radius' && styleConfig.sizes) {
    const raw = paint['circle-color'];
    const circleColor = (typeof raw === 'string' ? raw : undefined) ?? MAP_COLORS.fallback;
    // Extract colors + breaks from paint expression so legend matches
    // the actual map rendering (styleConfig may lack colors when the
    // DataDrivenStyleEditor saves radius-targeted graduated configs)
    const parsed = useMemo(() => parsePaintColors(raw), [raw]);
    const colors = styleConfig.colors ?? parsed?.colors;
    // Use paint-expression breaks when available — they match the actual
    // map rendering. Falls back to styleConfig.breaks for flat-color layers.
    const effectiveBreaks = parsed?.breaks ?? breaks;
    // Cap entries to color count to avoid duplicate "≥ max" rows
    const entryCount = colors ? Math.min(styleConfig.sizes.length, colors.length) : styleConfig.sizes.length;
    const cappedSizes = styleConfig.sizes.slice(0, entryCount);
    return (
      <GraduatedRadiusLegend
        sizes={cappedSizes}
        breaks={effectiveBreaks}
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
