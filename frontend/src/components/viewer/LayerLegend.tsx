import { useEffect, useMemo, useRef } from 'react';
import type { MapTerrainConfig, SharedLayerResponse } from '@/types/api';
import { useTranslation } from 'react-i18next';
import { demChipGlyph, LayerTypeIcon, RasterGlyphChip } from '@/components/map/layer-icons';
import { HeatmapLegend, LegendClassesList } from '@/components/map/LegendEntries';
import { Eye, EyeOff, Layers, X } from 'lucide-react';
import { createViewerLayerEntries, isTerrainBackingLiveVisible } from '@/components/viewer/layer-identity';
import {
  deriveTerrainLegendEntry,
  terrainSourceIsShownAsLayer,
} from '@/components/builder/terrain-legend';
import { legendFacts } from '@/components/map/legend-facts';
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

function clusterLegendKind(layer: SharedLayerResponse) {
  if (!isClusterRenderMode(layer)) return null;
  const strategy = getClusterSourceStrategy(layer);
  return strategy.kind;
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

  // The synthetic terrain entry below stays local to this legend: ViewerMap
  // also reads createViewerLayerEntries and must not see a row that draws nothing.
  const sorted = useMemo(
    () =>
      createViewerLayerEntries(layers)
        .flatMap((entry) => {
          if (entry.layer.show_in_legend === false) return [];
          const facts = legendFacts(entry.layer);
          return facts ? [{ ...entry, facts }] : [];
        })
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
    // longer renders. Same helper as ViewerMap's mesh gate — one definition,
    // so legend and mesh cannot disagree.
    if (!isTerrainBackingLiveVisible(layers, terrainConfig, visibleLayers)) return null;
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
        className="absolute start-3 top-3 z-20 flex items-center justify-center w-8 h-8 rounded-md bg-background/80 backdrop-blur-sm border border-border/50 shadow-sm text-foreground hover:bg-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
        // fix(#731): cap the height against the CONTAINER, not the viewport —
        // the panel is absolutely positioned inside the map, so a viewport cap
        // let a tall legend run down behind the Map data button (bottom-20 +
        // ~2rem) and the basemap toggle (bottom-8) in the same corner. 11rem =
        // the 3.5rem top offset plus clearance above that bottom-left stack.
        className="absolute start-3 top-14 z-10 w-64 max-h-[calc(100%-11rem)] overflow-y-auto bg-background/90 backdrop-blur-md rounded-lg shadow-lg border border-border/50"
      >
        <div className="p-3 border-b border-border/50">
          <h2 className="text-sm font-semibold text-foreground">
            {customTitle ?? t('viewer.legend.title')}
          </h2>
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
                    legend and layer-list icons must agree, so derive the glyph
                    instead of hardcoding it. */}
                <RasterGlyphChip glyph={demChipGlyph('terrain')} />
                {/* fix(HT-08): keep the bound DEM's identity — fall back to the
                    generic "3D terrain" label only when the layer has no name. */}
                <span className="text-sm text-foreground flex-1">
                  {terrainEntry.sourceName ?? t(terrainEntry.labelKey)}
                </span>
              </div>
            </li>
          )}
          {sorted.map(({ layer, key, facts }) => {
            const isVisible = visibleLayers.has(key);
            const sc = layer.style_config;
            const layerName = facts.name;
            const clusterKind = clusterLegendKind(layer);
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
                {clusterKind && (
                  <div className="mt-1 ms-6 text-mini font-medium text-muted-foreground">
                    {clusterKind === 'server-tile'
                      ? t('viewer.legend.cluster.server')
                      : clusterKind === 'bounded-geojson'
                        ? t('viewer.legend.cluster.bounded')
                        : t('viewer.legend.cluster.fallback')}
                  </div>
                )}

                {/* Data-driven legend entries */}
                {isVisible && (
                  facts.ramp ? (
                    <div className="mt-1.5 ms-6">
                      <HeatmapLegend
                        name=""
                        ramp={facts.ramp}
                        opacity={layer.opacity ?? 1}
                        lowLabel={t('viewer.heatmapLow')}
                        highLabel={t('viewer.heatmapHigh')}
                      />
                    </div>
                  ) : facts.classes ? (
                    <div className="mt-1.5 ms-6">
                      <LegendClassesList classes={facts.classes} geometryType={layer.geometry_type} style={facts.swatch} />
                    </div>
                  ) : null
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
