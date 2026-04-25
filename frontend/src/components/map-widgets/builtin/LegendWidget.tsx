import { memo, useMemo } from 'react';
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
import type { MapLayerResponse, StyleConfig } from '@/types/api';
import { MAP_COLORS } from '@/lib/map-colors';
import { parseStepOrInterpolate } from '@/lib/normalize-style-config';
import { inferGeometryType } from '@/lib/geo-utils';
import type { WidgetContext } from '../types';

/** Extract swatch style properties from layer paint based on geometry type. */
function getSwatchStyleFromPaint(
  paint: Record<string, unknown> | undefined,
  geometryType: string | null | undefined,
  masterOpacity: number,
): SwatchStyle {
  const gt = (inferGeometryType(paint, geometryType) ?? '').toUpperCase();
  const strokeDisabled = !!paint?.['_stroke-disabled'];

  const rawOutline = gt.includes('POINT') ? paint?.['circle-stroke-color'] : paint?.['_outline-color'];
  const outlineColor = typeof rawOutline === 'string' ? rawOutline : undefined;

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
      {legendLayers.map((layer, idx) => (
        <LegendLayerEntry
          key={layer.id}
          layer={layer}
          idx={idx}
          isLast={idx === legendLayers.length - 1}
        />
      ))}
    </div>
  );
}

/** Per-layer legend entry. Memoized and wrapped in try/catch for resilience. */
const LegendLayerEntry = memo(function LegendLayerEntry({
  layer,
  idx,
  isLast,
}: {
  layer: MapLayerResponse;
  idx: number;
  isLast: boolean;
}) {
  const { t } = useTranslation('builder');

  try {
    const opacity = layer.opacity ?? 1;
    const effectiveGeom = inferGeometryType(layer.paint, layer.dataset_geometry_type);
    const swatchStyle = getSwatchStyleFromPaint(layer.paint, effectiveGeom, opacity);
    const weightCol = layer.paint?.['_heatmap-weight-column'] as string | undefined;

    return (
      <div>
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
                  geometryType={effectiveGeom}
                  style={swatchStyle}
                />
              )}

              {layer.style_config.mode === 'graduated' &&
                layer.style_config.breaks && (
                  <GraduatedLegendSwitch
                    styleConfig={layer.style_config}
                    paint={layer.paint ?? {}}
                    style={swatchStyle}
                    geometryType={effectiveGeom}
                  />
                )}
            </>
          ) : (
            <div className="flex items-center gap-1.5">
              <ColorizedGeometryIcon
                geometryType={effectiveGeom}
                colors={getLayerColors({
                  dataset_geometry_type: effectiveGeom,
                  paint: layer.paint ?? {},
                  style_config: layer.style_config,
                })}
                layerId={`legend-widget-${idx}`}
                layerType={layer.layer_type ?? undefined}
                styleHints={extractStyleHints(
                  layer.paint ?? {},
                  layer.layout ?? {},
                  effectiveGeom,
                  opacity,
                  layer.style_config,
                )}
              />
              <span className="font-medium text-foreground truncate">
                {layer.display_name ?? layer.dataset_name}
              </span>
            </div>
          )}
        </div>
        {!isLast && <div className="border-b" />}
      </div>
    );
  } catch (err) {
    if (import.meta.env.DEV) console.error(`[LegendWidget] Failed to render layer "${layer.display_name ?? layer.dataset_name}":`, err);
    return (
      <div>
        <div className="p-1 text-xs">
          <span className="font-medium text-foreground truncate">
            {layer.display_name ?? layer.dataset_name}
          </span>
          <span className="text-muted-foreground italic ml-1">
            {t('widgets.legend.unavailable', { defaultValue: '(legend unavailable)' })}
          </span>
        </div>
        {!isLast && <div className="border-b" />}
      </div>
    );
  }
});

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

  // Parse circle-color expression unconditionally (Rules of Hooks)
  const rawCircleColor = paint['circle-color'];
  const parsedCircleColor = useMemo(() => parsePaintColors(rawCircleColor), [rawCircleColor]);

  if (styleConfig.target === 'radius' && styleConfig.sizes) {
    const circleColor = (typeof rawCircleColor === 'string' ? rawCircleColor : undefined) ?? MAP_COLORS.fallback;
    const colors = styleConfig.colors ?? parsedCircleColor?.colors;
    const effectiveBreaks = parsedCircleColor?.breaks ?? breaks;
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
