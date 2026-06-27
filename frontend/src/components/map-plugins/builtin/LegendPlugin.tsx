import { memo, useMemo, useState } from 'react';
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
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { Mountain, Pencil, Check } from 'lucide-react';
import {
  deriveTerrainLegendEntry,
  isDemTerrainVisualSuppressed,
  terrainSourceIsShownAsLayer,
} from '@/components/builder/terrain-legend';
import type { PluginContext } from '../types';

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

export function expressionColumn(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  if (value[0] === 'get' && typeof value[1] === 'string') return value[1];
  for (const entry of value) {
    const column = expressionColumn(entry);
    if (column) return column;
  }
  return null;
}

export function displayColumn(value: string | undefined): string {
  if (!value) return 'value';
  return value
    .replace(/^_+/, '')
    .replace(/_/g, ' ')
    .replace(/\bmhi\b/i, 'income')
    .replace(/\bkm\b/i, 'km');
}

type LegendLabelStyleConfig = StyleConfig & {
  sizeLabel?: string;
  colorLabel?: string;
};

/**
 * Effective legend entry name (ENH-06): a non-empty per-entry
 * style_config.legendLabel override wins, else the layer's display name, else
 * the dataset name. Shared by the plugin and the viewer for parity.
 */
export function legendEntryName(layer: MapLayerResponse): string {
  const override = layer.style_config?.legendLabel;
  if (typeof override === 'string' && override.trim() !== '') return override;
  return layer.display_name ?? layer.dataset_name;
}

export function LegendPlugin({ ctx }: { ctx: PluginContext }) {
  const { t } = useTranslation('builder');
  const [isEditing, setIsEditing] = useState(false);

  const legendTitle = ctx.legendTitle?.trim() ? ctx.legendTitle.trim() : null;
  // The edit affordance is only available when the host wired persistence
  // callbacks (the builder); read-only contexts (viewer/tests) hide it.
  const canEdit = Boolean(ctx.onLegendTitleChange || ctx.onLegendLabelChange);

  // D-02: exclude terrain-suppressed DEM layers (render_mode:"terrain") — they
  // have no stack row and paint nothing, so they must not appear as per-layer
  // legend entries. Consume the shared predicate, never re-derive it.
  const legendLayers = useMemo(
    () => ctx.layers.filter(
      (l) => l.visible && l.show_in_legend !== false && !isDemTerrainVisualSuppressed(l),
    ),
    [ctx.layers],
  );

  // D-01: single synthetic "3D terrain" entry driven by terrain_config — only
  // when a backing terrain-capable DEM layer for the source dataset is present
  // (999.17 MD-01: no phantom entry for a dangling terrain_config).
  const terrainEntryRaw = useMemo(
    () => deriveTerrainLegendEntry(ctx.terrainConfig, ctx.layers, { labelKey: 'plugins.legend.terrain3d' }),
    [ctx.terrainConfig, ctx.layers],
  );
  // Dedup: drop the synthetic entry when the terrain source DEM is ALSO shown as
  // a per-layer entry (e.g. a visible hillshade of the same dataset), so the
  // legend doesn't list one DEM twice. Keeps it for the pure-terrain / hidden
  // case where the synthetic is the only terrain indicator.
  const terrainEntry = terrainEntryRaw && !terrainSourceIsShownAsLayer(ctx.terrainConfig, legendLayers)
    ? terrainEntryRaw
    : null;

  if (legendLayers.length === 0 && !terrainEntry) {
    return (
      <p className="text-xs text-muted-foreground">{t('plugins.legend.noLayers')}</p>
    );
  }

  return (
    <div className="space-y-0 min-w-44">
      {/* ENH-06: custom map-level legend title + edit affordance. The title row
          renders only when a custom title exists OR the editor is open; the
          pencil button is always present in editable (builder) contexts. */}
      {(legendTitle || canEdit) && (
        <div className="flex items-center justify-between gap-1 pb-1" data-testid="legend-title-row">
          {legendTitle ? (
            <span className="text-xs font-semibold text-foreground truncate" data-testid="legend-title">
              {legendTitle}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground/70 truncate">
              {t('plugins.legend.titlePlaceholder')}
            </span>
          )}
          {canEdit && (
            <button
              type="button"
              onClick={() => setIsEditing((v) => !v)}
              aria-pressed={isEditing}
              aria-label={t('plugins.legend.editLegend')}
              title={t('plugins.legend.editLegend')}
              className="flex-shrink-0 p-0.5 rounded text-muted-foreground hover:text-foreground hover:bg-accent"
            >
              {isEditing ? <Check className="w-3.5 h-3.5" aria-hidden="true" /> : <Pencil className="w-3.5 h-3.5" aria-hidden="true" />}
            </button>
          )}
        </div>
      )}

      {isEditing && canEdit && (
        <div className="mb-1 space-y-1.5 rounded border border-border/50 bg-muted/30 p-1.5" data-testid="legend-editor">
          {ctx.onLegendTitleChange && (
            <input
              type="text"
              defaultValue={ctx.legendTitle ?? ''}
              maxLength={120}
              placeholder={t('plugins.legend.titlePlaceholder')}
              aria-label={t('plugins.legend.titlePlaceholder')}
              className="w-full rounded border border-border bg-background px-1.5 py-0.5 text-xs"
              onBlur={(e) => ctx.onLegendTitleChange?.(e.target.value.trim() || null)}
            />
          )}
          {ctx.onLegendLabelChange &&
            legendLayers.map((layer) => (
              <input
                key={layer.id}
                type="text"
                defaultValue={
                  typeof layer.style_config?.legendLabel === 'string'
                    ? layer.style_config.legendLabel
                    : ''
                }
                maxLength={120}
                placeholder={t('plugins.legend.entryLabelPlaceholder', {
                  name: layer.display_name ?? layer.dataset_name,
                })}
                aria-label={t('plugins.legend.entryLabelPlaceholder', {
                  name: layer.display_name ?? layer.dataset_name,
                })}
                className="w-full rounded border border-border bg-background px-1.5 py-0.5 text-xs"
                onBlur={(e) => ctx.onLegendLabelChange?.(layer.id, e.target.value.trim())}
              />
            ))}
        </div>
      )}

      {/* A1: pin the synthetic terrain entry at the top, mirroring the stack's
          relief:terrain row at the top of the relief/terrain group. */}
      {terrainEntry && (
        <div data-testid="legend-terrain-synthetic">
          <div className="p-1 text-xs">
            <div className="flex items-center gap-1.5">
              <Mountain className="w-4 h-4 text-muted-foreground" aria-hidden="true" />
              <span className="font-medium text-foreground truncate">
                {t(terrainEntry.labelKey)}
              </span>
            </div>
          </div>
          {legendLayers.length > 0 && <div className="border-b" />}
        </div>
      )}
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
    // ENH-06: per-entry legendLabel override wins over display/dataset name.
    const entryName = legendEntryName(layer);

    return (
      <div>
        <div className="p-1 text-xs">
          {layer.style_config?.render_mode === 'heatmap' ? (
            <HeatmapLegend
              name={entryName}
              rampName={(layer.paint?.['_heatmap-ramp'] as string) ?? 'YlOrRd'}
              weightColumn={weightCol}
              opacity={opacity}
              lowLabel={t('plugins.legend.low')}
              highLabel={t('plugins.legend.high')}
              weightedByLabel={weightCol ? t('plugins.legend.weightedBy', { column: weightCol }) : undefined}
            />
          ) : layer.style_config?.column ? (
            <>
              <div className="font-medium text-foreground mb-1 truncate">
                {entryName}
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
                layerId={`legend-plugin-${idx}`}
                // Pass the capability kind ('raster'/'vrt'/'vector'), not the raw
                // layer_type ('raster_geolens') — ColorizedGeometryIcon keys its
                // raster/vrt icons off kind, same contract StackRow uses. Raw
                // layer_type fell through to a polygon swatch for raster layers.
                layerType={getLayerCapabilities(layer).kind}
                styleHints={extractStyleHints(
                  layer.paint ?? {},
                  layer.layout ?? {},
                  effectiveGeom,
                  opacity,
                  layer.style_config,
                )}
              />
              <span className="font-medium text-foreground truncate">
                {entryName}
              </span>
            </div>
          )}
        </div>
        {!isLast && <div className="border-b" />}
      </div>
    );
  } catch (err) {
    if (import.meta.env.DEV) console.error(`[LegendPlugin] Failed to render layer "${layer.display_name ?? layer.dataset_name}":`, err);
    return (
      <div>
        <div className="p-1 text-xs">
          <span className="font-medium text-foreground truncate">
            {legendEntryName(layer)}
          </span>
          <span className="text-muted-foreground italic ml-1">
            {t('plugins.legend.unavailable', { defaultValue: '(legend unavailable)' })}
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
  const labelConfig = styleConfig as LegendLabelStyleConfig;
  const metricLabel = labelConfig.sizeLabel ?? displayColumn(styleConfig.column);

  // Parse circle-color expression unconditionally (Rules of Hooks)
  const rawCircleColor = paint['circle-color'];
  const parsedCircleColor = useMemo(() => parsePaintColors(rawCircleColor), [rawCircleColor]);
  const colorColumn = expressionColumn(rawCircleColor);

  if (styleConfig.target === 'radius' && styleConfig.sizes) {
    const circleColor = (typeof rawCircleColor === 'string' ? rawCircleColor : undefined) ?? MAP_COLORS.fallback;
    return (
      <div className="space-y-1">
        <div className="text-[11px] font-medium text-muted-foreground">
          Size: {metricLabel}
        </div>
        <GraduatedRadiusLegend
          sizes={styleConfig.sizes}
          breaks={breaks}
          circleColor={parsedCircleColor?.colors[0] ?? circleColor}
          style={style}
        />
        {parsedCircleColor && colorColumn && colorColumn !== styleConfig.column && (
          <>
            <div className="pt-1 text-[11px] font-medium text-muted-foreground">
              Color: {labelConfig.colorLabel ?? displayColumn(colorColumn)}
            </div>
            <GraduatedColorLegend
              colors={parsedCircleColor.colors}
              breaks={parsedCircleColor.breaks}
              geometryType={geometryType}
              style={style}
            />
          </>
        )}
      </div>
    );
  }

  if (styleConfig.target === 'width' && styleConfig.sizes) {
    const raw = paint['line-color'];
    const lineColor = (typeof raw === 'string' ? raw : undefined) ?? MAP_COLORS.fallback;
    return (
      <div className="space-y-1">
        <div className="text-[11px] font-medium text-muted-foreground">
          Width: {metricLabel}
        </div>
        <GraduatedWidthLegend
          sizes={styleConfig.sizes}
          breaks={breaks}
          lineColor={lineColor}
          style={style}
        />
      </div>
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
