import { memo, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { demChipGlyph, LayerTypeIcon, RasterGlyphChip } from '@/components/map/layer-icons';
import {
  CategoricalLegend,
  GraduatedColorLegend,
  GraduatedRadiusLegend,
  GraduatedWidthLegend,
  HeatmapLegend,
} from '@/components/map/LegendEntries';
import type { MapLayerResponse, StyleConfig } from '@/types/api';
import { MAP_COLORS } from '@/lib/map-colors';
import { parseStepOrInterpolate, resolveHeatmapRamp } from '@/lib/normalize-style-config';
import { inferGeometryType } from '@/lib/geo-utils';
import { legendEntryName, legendFacts } from '@/components/map/legend-facts';
import type { LegendSwatch } from '@/components/map/legend-facts';
import { Pencil, Check } from 'lucide-react';
import { syntheticTerrainEntry } from '@/components/builder/terrain-legend';
import type { PluginContext } from '../types';

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

export function LegendPlugin({ ctx }: { ctx: PluginContext }) {
  const { t } = useTranslation('builder');
  const [isEditing, setIsEditing] = useState(false);

  const legendTitle = ctx.legendTitle?.trim() ? ctx.legendTitle.trim() : null;
  // The edit affordance is only available when the host wired persistence
  // callbacks (the builder); read-only contexts (viewer/tests) hide it.
  const canEdit = Boolean(ctx.onLegendTitleChange || ctx.onLegendLabelChange);

  const legendLayers = useMemo(
    () => ctx.layers.filter(
      (l) => l.visible && l.show_in_legend !== false && legendFacts(l) !== null,
    ),
    [ctx.layers],
  );

  const terrainEntry = useMemo(
    () => syntheticTerrainEntry(ctx.terrainConfig, ctx.layers, legendLayers, { labelKey: 'plugins.legend.terrain3d' }),
    [ctx.terrainConfig, ctx.layers, legendLayers],
  );

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
            <span className="text-xs text-muted-foreground truncate">
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
              className="flex-shrink-0 p-0.5 rounded-sm text-muted-foreground hover:text-foreground hover:bg-accent"
            >
              {isEditing ? <Check className="w-3.5 h-3.5" aria-hidden="true" /> : <Pencil className="w-3.5 h-3.5" aria-hidden="true" />}
            </button>
          )}
        </div>
      )}

      {isEditing && canEdit && (
        <div className="mb-1 space-y-1.5 rounded-sm border border-border/50 bg-muted/30 p-1.5" data-testid="legend-editor">
          {ctx.onLegendTitleChange && (
            <input
              type="text"
              defaultValue={ctx.legendTitle ?? ''}
              maxLength={120}
              placeholder={t('plugins.legend.titlePlaceholder')}
              aria-label={t('plugins.legend.titlePlaceholder')}
              className="w-full rounded-sm border border-border bg-background px-1.5 py-0.5 text-xs"
              onBlur={(e) => ctx.onLegendTitleChange?.(e.target.value.trim() || null)}
            />
          )}
          {ctx.onLegendLabelChange &&
            legendLayers.map((layer) => {
              // The name the entry falls back to once the override is cleared.
              const name = legendEntryName({ display_name: layer.display_name, dataset_name: layer.dataset_name }) ?? '';
              return (
                <input
                  key={layer.id}
                  type="text"
                  defaultValue={
                    typeof layer.style_config?.legendLabel === 'string'
                      ? layer.style_config.legendLabel
                      : ''
                  }
                  maxLength={120}
                  placeholder={t('plugins.legend.entryLabelPlaceholder', { name })}
                  aria-label={t('plugins.legend.entryLabelPlaceholder', { name })}
                  className="w-full rounded-sm border border-border bg-background px-1.5 py-0.5 text-xs"
                  onBlur={(e) => ctx.onLegendLabelChange?.(layer.id, e.target.value.trim())}
                />
              );
            })}
        </div>
      )}

      {/* A1: pin the synthetic terrain entry at the top, mirroring the stack's
          relief:terrain row at the top of the relief/terrain group. */}
      {terrainEntry && (
        <div data-testid="legend-terrain-synthetic">
          <div className="p-1 text-xs">
            <div className="flex items-center gap-1.5">
              {/* fix(#452): same ◬ chip as the stack's terrain-mode DEM row —
                  legend and layer-list icons must agree, so derive the glyph
                  instead of hardcoding it. */}
              <RasterGlyphChip glyph={demChipGlyph('terrain')} />
              {/* fix(HT-08): keep the bound DEM's identity — fall back to the
                  generic "3D terrain" label only when the layer has no name. */}
              <span className="font-medium text-foreground truncate">
                {terrainEntry.sourceName ?? t(terrainEntry.labelKey)}
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
  const facts = legendFacts(layer);
  const entryName = facts?.name ?? '';

  try {
    const opacity = layer.opacity ?? 1;
    const effectiveGeom = inferGeometryType(layer.paint, layer.dataset_geometry_type);
    const swatch = facts?.swatch ?? null;
    const weightCol = layer.paint?.['_heatmap-weight-column'] as string | undefined;
    const heatmapRamp = resolveHeatmapRamp(layer.paint, layer.style_config);

    return (
      <div>
        <div className="p-1 text-xs">
          {layer.style_config?.render_mode === 'heatmap' ? (
            <HeatmapLegend
              name={entryName}
              rampName={heatmapRamp.rampName}
              reversed={heatmapRamp.reversed}
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
                  style={swatch}
                />
              )}

              {layer.style_config.mode === 'graduated' &&
                layer.style_config.breaks && (
                  <GraduatedLegendSwitch
                    styleConfig={layer.style_config}
                    paint={layer.paint ?? {}}
                    style={swatch}
                    geometryType={effectiveGeom}
                  />
                )}
            </>
          ) : (
            <div className="flex items-center gap-1.5">
              {/* fix(#452): one shared icon component with the layer stack —
                  raster/DEM rows get the same glyph chip (▦/⛰/◬) the stack
                  shows instead of a divergent lucide icon. */}
              <LayerTypeIcon
                layer={{ ...layer, dataset_geometry_type: effectiveGeom }}
                iconId={`legend-plugin-${idx}`}
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
    if (import.meta.env.DEV) console.error(`[LegendPlugin] Failed to render layer "${entryName}":`, err);
    return (
      <div>
        <div className="p-1 text-xs">
          <span className="font-medium text-foreground truncate">
            {entryName}
          </span>
          <span className="text-muted-foreground italic ms-1">
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
  style: LegendSwatch | null;
  geometryType?: string | null;
}) {
  const { t } = useTranslation('common');
  const breaks = styleConfig.breaks ?? [];
  const labelConfig = styleConfig as LegendLabelStyleConfig;
  const metricLabel = labelConfig.sizeLabel ?? displayColumn(styleConfig.column);

  // Parse circle-color expression unconditionally (Rules of Hooks)
  const rawCircleColor = paint['circle-color'];
  const parsedCircleColor = useMemo(() => parsePaintColors(rawCircleColor), [rawCircleColor]);
  const colorColumn = expressionColumn(rawCircleColor);

  if (styleConfig.target === 'radius' && styleConfig.sizes) {
    const circleColor = style?.fill ?? MAP_COLORS.fallback;
    return (
      <div className="space-y-1">
        <div className="text-mini font-medium text-muted-foreground">
          {t('common:viewer.legend.sizeLabel', { label: metricLabel })}
        </div>
        <GraduatedRadiusLegend
          sizes={styleConfig.sizes}
          breaks={breaks}
          circleColor={parsedCircleColor?.colors[0] ?? circleColor}
          style={style}
        />
        {parsedCircleColor && colorColumn && colorColumn !== styleConfig.column && (
          <>
            <div className="pt-1 text-mini font-medium text-muted-foreground">
              {t('common:viewer.legend.colorLabel', {
                label: labelConfig.colorLabel ?? displayColumn(colorColumn),
              })}
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
    const lineColor = style?.fill ?? MAP_COLORS.fallback;
    return (
      <div className="space-y-1">
        <div className="text-mini font-medium text-muted-foreground">
          {t('common:viewer.legend.widthLabel', { label: metricLabel })}
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
