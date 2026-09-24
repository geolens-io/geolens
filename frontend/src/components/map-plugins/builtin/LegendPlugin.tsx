import { memo, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { demChipGlyph, LayerTypeIcon, RasterGlyphChip } from '@/components/map/layer-icons';
import { HeatmapLegend, LegendClassesList } from '@/components/map/LegendEntries';
import type { MapLayerResponse } from '@/types/api';
import { inferGeometryType } from '@/lib/geo-utils';
import { legendEntryName, legendFacts } from '@/components/map/legend-facts';
import { Pencil, Check } from 'lucide-react';
import { syntheticTerrainEntry } from '@/components/builder/terrain-legend';
import type { PluginContext } from '../types';

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
    const weight = facts?.weight ?? null;

    return (
      <div>
        <div className="p-1 text-xs">
          {facts?.ramp ? (
            <HeatmapLegend
              name={entryName}
              ramp={facts.ramp}
              weightColumn={weight?.column}
              opacity={opacity}
              lowLabel={t('plugins.legend.low')}
              highLabel={t('plugins.legend.high')}
              weightedByLabel={weight
                ? t(weight.scaled ? 'plugins.legend.weightedByScaled' : 'plugins.legend.weightedBy', { column: weight.column })
                : undefined}
            />
          ) : facts?.classes ? (
            <>
              <div className="font-medium text-foreground mb-1 truncate">
                {entryName}
              </div>
              <LegendClassesList classes={facts.classes} geometryType={effectiveGeom} style={swatch} />
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
