import type { Map as MaplibreMap } from 'maplibre-gl';
import type { FilterSpecification } from 'maplibre-gl';
import type { LabelConfig, StyleConfig } from '@/types/api';

type AdapterStyleConfig = Partial<StyleConfig> & {
  builder?: StyleConfig['builder'];
};

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
  type: 'fill' | 'line' | 'circle' | 'raster' | 'heatmap';
  addLayers(map: MaplibreMap, input: AdapterLayerInput): void;
  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void;
  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void;
  getLayerIds(layerId: string): string[];
}
