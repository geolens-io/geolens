import { useEffect, useMemo, useRef } from 'react';
import type { MapTerrainConfig, SharedLayerResponse, StyleConfig } from '@/types/api';
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
import { Eye, EyeOff, Grid3x3, Layers, Mountain, X } from 'lucide-react';
import { parseStepOrInterpolate } from '@/lib/normalize-style-config';
import { MAP_COLORS } from '@/lib/map-colors';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { createViewerLayerEntries } from '@/components/viewer/layer-identity';
import {
  deriveTerrainLegendEntry,
  isDemTerrainVisualSuppressed,
} from '@/components/builder/terrain-legend';
import { getClusterSourceStrategy, isClusterRenderMode } from '@/components/builder/cluster-source';

interface LayerLegendProps {
  layers: SharedLayerResponse[];
  visibleLayers: Set<string>;
  onToggleVisibility: (layerKey: string) => void;
  isOpen: boolean;
  onToggle: () => void;
  /** Map-level terrain config; drives the synthetic "3D terrain" legend entry. */
  terrainConfig?: MapTerrainConfig | null;
  /**
   * ENH-06: custom map-level legend title. When set (non-empty), it renders as
   * the panel heading in place of the default "Legend" label. Null/empty keeps
   * the default heading.
   */
  legendTitle?: string | null;
}

/**
 * ENH-06: effective viewer legend entry name. A non-empty per-entry
 * style_config.legendLabel override wins, else the layer's display name, else
 * the dataset name. Mirrors LegendPlugin.legendEntryName for builder/viewer
 * parity.
 */
function viewerLegendEntryName(layer: SharedLayerResponse): string {
  const override = layer.style_config?.legendLabel;
  if (typeof override === 'string' && override.trim() !== '') return override;
  return layer.display_name || layer.dataset_name;
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

function clusterLegendLabel(layer: SharedLayerResponse) {
  if (!isClusterRenderMode(layer)) return null;
  const strategy = getClusterSourceStrategy(layer);
  if (strategy.kind === 'server-tile') return 'Server cluster';
  if (strategy.kind === 'bounded-geojson') return 'Bounded cluster';
  return 'Point fallback';
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
  // parsePaintColors only handles data-driven expressions; a constant fill is a
  // plain string, so fall back to it (the layer's real color) before gray.
  const constantColor =
    (typeof rawColor === 'string' ? rawColor : undefined) ?? MAP_COLORS.fallback;

  if (styleConfig.target === 'radius' && styleConfig.sizes) {
    return (
      <div className="space-y-1">
        <div className="text-[11px] font-medium text-muted-foreground">
          Size: {metricLabel}
        </div>
        <GraduatedRadiusLegend
          sizes={styleConfig.sizes}
          breaks={breaks}
          circleColor={parsedColor?.colors[0] ?? constantColor}
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
  terrainConfig = null,
  legendTitle = null,
}: LayerLegendProps) {
  const { t } = useTranslation('common');
  const panelRef = useRef<HTMLDivElement>(null);
  const customTitle = legendTitle?.trim() ? legendTitle.trim() : null;

  // D-02: exclude terrain-suppressed DEM layers (render_mode:"terrain") using
  // the SAME shared predicate as the stack/builder — never re-derived. The
  // synthetic entry is injected only here in LayerLegend's local derivation, so
  // the shared createViewerLayerEntries output (also consumed by ViewerMap for
  // real map-layer wiring) is never polluted with a non-paintable entry.
  const sorted = useMemo(
    () =>
      createViewerLayerEntries(layers)
        .filter(({ layer }) => layer.show_in_legend !== false && !isDemTerrainVisualSuppressed(layer))
        .sort((a, b) => a.layer.sort_order - b.layer.sort_order),
    [layers],
  );

  // D-01: single synthetic "3D terrain" entry driven by terrain_config — only
  // when a backing terrain-capable DEM layer for the source dataset is present
  // (999.17 MD-01: no phantom entry for a dangling terrain_config).
  const terrainEntry = useMemo(
    () => deriveTerrainLegendEntry(terrainConfig, layers, { labelKey: 'viewer.legend.terrain3d' }),
    [terrainConfig, layers],
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
          <h3 className="text-sm font-semibold text-foreground">
            {customTitle ?? t('viewer.legend.title')}
          </h3>
          {customTitle && (
            <span data-testid="viewer-legend-title" className="sr-only">{customTitle}</span>
          )}
        </div>
        <ul className="divide-y divide-border/50">
          {/* A1: pin the synthetic terrain entry at the top, mirroring the
              stack's relief:terrain row at the top of the relief/terrain group. */}
          {terrainEntry && (
            <li
              key={terrainEntry.id}
              data-testid="legend-terrain-synthetic"
              className="px-3 py-2 hover:bg-accent/50"
            >
              <div className="flex items-center gap-2">
                <Mountain className="w-4 h-4 text-muted-foreground" aria-hidden="true" />
                <span className="text-sm text-foreground flex-1">
                  {t(terrainEntry.labelKey)}
                </span>
              </div>
            </li>
          )}
          {sorted.map(({ layer, key }) => {
            const isVisible = visibleLayers.has(key);
            const sc = layer.style_config;
            const isHeatmap = sc?.render_mode === 'heatmap';
            // Raster/VRT layers have no vector fill — show a raster icon (as the
            // builder does), not the colored point/polygon swatch + default color.
            const caps = getLayerCapabilities({
              layer_type: layer.layer_type,
              dataset_record_type: layer.dataset_record_type,
              dataset_geometry_type: layer.geometry_type,
            });
            const isRasterLike = caps.kind === 'raster' || caps.kind === 'vrt';
            const color = isHeatmap || isRasterLike ? null : getLayerColors({
              dataset_geometry_type: layer.geometry_type ?? null,
              paint: layer.paint ?? {},
              style_config: sc,
            })[0];
            const layerName = viewerLegendEntryName(layer);
            const clusterLabel = clusterLegendLabel(layer);
            return (
              <li key={key} className="px-3 py-2 hover:bg-accent/50">
                <div className="flex items-center gap-2">
                  {isRasterLike ? (
                    caps.kind === 'vrt' ? (
                      <Layers className="w-3.5 h-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    ) : (
                      <Grid3x3 className="w-3.5 h-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    )
                  ) : color ? (
                    <GeometrySwatch geometryType={layer.geometry_type} color={color} />
                  ) : null}
                  <span className="text-sm text-foreground flex-1 line-clamp-2" title={layerName}>
                    {layerName}
                  </span>
                  <button
                    type="button"
                    onClick={() => onToggleVisibility(key)}
                    className="flex-shrink-0 p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                    aria-label={isVisible
                      ? t('viewer.legend.hideLayer', { name: layerName })
                      : t('viewer.legend.showLayer', { name: layerName })}
                  >
                    {isVisible ? <Eye className="w-4 h-4" aria-hidden="true" /> : <EyeOff className="w-4 h-4" aria-hidden="true" />}
                  </button>
                </div>
                {clusterLabel && (
                  <div className="mt-1 ms-6 text-[11px] font-medium text-muted-foreground">
                    {clusterLabel}
                  </div>
                )}

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
