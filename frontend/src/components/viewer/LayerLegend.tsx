import { useEffect, useMemo, useRef } from 'react';
import type { MapTerrainConfig, SharedLayerResponse, StyleConfig } from '@/types/api';
import { useTranslation } from 'react-i18next';
import { LayerTypeIcon, RasterGlyphChip } from '@/components/map/layer-icons';
import {
  CategoricalLegend,
  GraduatedColorLegend,
  GraduatedRadiusLegend,
  GraduatedWidthLegend,
  HeatmapLegend,
} from '@/components/map/LegendEntries';
import type { SwatchStyle } from '@/components/map/LegendEntries';
import { Eye, EyeOff, Layers, X } from 'lucide-react';
import { parseStepOrInterpolate } from '@/lib/normalize-style-config';
import { MAP_COLORS } from '@/lib/map-colors';
import { createViewerLayerEntries } from '@/components/viewer/layer-identity';
import {
  deriveTerrainLegendEntry,
  isDemTerrainVisualSuppressed,
  terrainSourceIsShownAsLayer,
} from '@/components/builder/terrain-legend';
import { resolveTerrainSourceLayer } from '@/components/builder/map-stack';
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
        <div className="text-mini font-medium text-muted-foreground">
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
            <div className="pt-1 text-mini font-medium text-muted-foreground">
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
        <div className="text-mini font-medium text-muted-foreground">
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
  const terrainEntry = useMemo(() => {
    const entry = deriveTerrainLegendEntry(terrainConfig, layers, { labelKey: 'viewer.legend.terrain3d' });
    if (!entry) return null;
    // fix(#452): the viewer now clears terrain when the bound DEM is LIVE-hidden
    // via the legend eye (useViewerTerrain honors visibleLayers), so a hidden
    // source must not keep a synthetic "3D terrain" row for a mesh that no
    // longer renders. Resolve the bound DEM with the same shared resolver the
    // renderer uses and gate on the live toggle state.
    const backing = resolveTerrainSourceLayer(layers, terrainConfig);
    const backingKey = createViewerLayerEntries(layers).find((e) => e.layer === backing)?.key;
    if (backingKey && !visibleLayers.has(backingKey)) return null;
    // Dedup: drop the synthetic entry when the terrain source DEM is shown as a
    // VISIBLE per-layer entry (e.g. a visible hillshade of the same dataset), so
    // the legend doesn't list one DEM twice. Kept for the pure-terrain case
    // where the suppressed DEM has no per-layer row.
    const visibleSourceLayers = sorted.filter((s) => visibleLayers.has(s.key)).map((s) => s.layer);
    return terrainSourceIsShownAsLayer(terrainConfig, visibleSourceLayers) ? null : entry;
  }, [terrainConfig, layers, sorted, visibleLayers]);

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
        className="absolute left-3 top-3 z-20 flex items-center justify-center w-8 h-8 rounded-md bg-background/80 backdrop-blur-sm border border-border/50 shadow-sm text-foreground hover:bg-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {isOpen ? <X className="w-4 h-4" aria-hidden="true" /> : <Layers className="w-4 h-4" aria-hidden="true" />}
      </button>

      {/* Legend panel — unmounted when closed (PR #330: prevent keyboard trap
          into invisible per-layer toggles; was opacity-0 + pointer-events-none only). */}
      {isOpen && (
      <div
        ref={panelRef}
        id="layer-legend-panel"
        role="region"
        aria-label={t('viewer.legend.title')}
        className="absolute left-3 top-14 z-10 w-64 max-h-[calc(100vh-5rem)] overflow-y-auto bg-background/90 backdrop-blur-md rounded-lg shadow-lg border border-border/50"
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
                {/* fix(#452): same ◬ chip as the stack's terrain-mode DEM row —
                    legend and layer-list icons must agree. */}
                <RasterGlyphChip glyph="◬" />
                {/* fix(HT-08): keep the bound DEM's identity — fall back to the
                    generic "3D terrain" label only when the layer has no name. */}
                <span className="text-sm text-foreground flex-1">
                  {terrainEntry.sourceName ?? t(terrainEntry.labelKey)}
                </span>
              </div>
            </li>
          )}
          {sorted.map(({ layer, key }) => {
            const isVisible = visibleLayers.has(key);
            const sc = layer.style_config;
            const layerName = viewerLegendEntryName(layer);
            const clusterLabel = clusterLegendLabel(layer);
            return (
              <li key={key} className="px-3 py-2 hover:bg-accent/50">
                <div className="flex items-center gap-2">
                  {/* fix(#452): one shared icon component with the builder layer
                      stack — raster/DEM rows get the same glyph chip (▦/⛰/◬),
                      vector rows the same colorized geometry icon. */}
                  <LayerTypeIcon
                    layer={{
                      dataset_geometry_type: layer.geometry_type,
                      layer_type: layer.layer_type,
                      dataset_record_type: layer.dataset_record_type,
                      is_dem: layer.is_dem,
                      paint: layer.paint,
                      layout: layer.layout,
                      opacity: layer.opacity,
                      style_config: sc,
                    }}
                    iconId={`viewer-legend-${key}`}
                  />
                  <span className="text-sm text-foreground flex-1 line-clamp-2" title={layerName}>
                    {layerName}
                  </span>
                  <button
                    type="button"
                    onClick={() => onToggleVisibility(key)}
                    className="flex-shrink-0 p-1 rounded-sm hover:bg-accent text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={isVisible
                      ? t('viewer.legend.hideLayer', { name: layerName })
                      : t('viewer.legend.showLayer', { name: layerName })}
                  >
                    {isVisible ? <Eye className="w-4 h-4" aria-hidden="true" /> : <EyeOff className="w-4 h-4" aria-hidden="true" />}
                  </button>
                </div>
                {clusterLabel && (
                  <div className="mt-1 ms-6 text-mini font-medium text-muted-foreground">
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
      )}
    </>
  );
}
