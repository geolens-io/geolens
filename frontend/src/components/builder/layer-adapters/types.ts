import type { Map as MaplibreMap } from 'maplibre-gl';
import type { FilterSpecification } from 'maplibre-gl';
import type { LabelConfig, StyleConfig } from '@/types/api';

type AdapterStyleConfig = Partial<StyleConfig> & {
  builder?: StyleConfig['builder'];
};

/**
 * Detection rule for source-level `lineMetrics: true` (see map-sync.ts `lineGradientNeededFor`):
 *   1. `paint['line-gradient']` is set (any non-null/non-undefined value).
 *   2. `style_config.builder.lineGradient` is a non-empty plain object (Phase 256 authoring intent).
 *      Arrays are explicitly rejected — both frontend and backend require dict-shape for parity
 *      across the export/import boundary.
 * The flag is sticky once set — the source is not torn down on gradient removal mid-session
 * (see .planning/phases/255-line-gradient-engine-foundation/255-CONTEXT.md D-02).
 */
export interface AdapterLayerInput {
  id: string;
  dataset_table_name: string;
  dataset_geometry_type: string | null;
  opacity: number;
  visible: boolean;
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
  filter: FilterSpecification | null;
  label_config?: LabelConfig | null;
  style_config?: AdapterStyleConfig | null;
  is_dem?: boolean | null;
  // Computed IDs (caller provides these)
  sourceId: string;
  layerId: string;
  sourceLayer: string;
  // Source type: 'vector' (MVT, default) or 'geojson' (GeoJSON-Z)
  sourceType?: 'vector' | 'geojson';
  // Raster-specific (from TileToken)
  tileUrl: string;
  tileSize?: number;
  minzoom?: number;
  maxzoom?: number;
}

export interface LayerAdapter {
  type: 'fill' | 'line' | 'circle' | 'symbol' | 'raster' | 'heatmap' | 'hillshade';
  addLayers(map: MaplibreMap, input: AdapterLayerInput): void;
  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void;
  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void;
  getLayerIds(layerId: string): string[];
}
