import type { Map as MaplibreMap } from 'maplibre-gl';
import type { FilterSpecification, LayerSpecification } from 'maplibre-gl';
import type { LabelConfig, StyleConfig } from '@/types/api';
import type { LayoutPropertyName, PaintPropertyName } from './shared';

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
  bounds?: number[] | null;
  /** fix(#1472 review): the dataset's required credit line, for the raster and
   *  raster-dem source specs. The vector path sets the same MapLibre source
   *  property directly in map-sync; without it here a raster or DEM layer was
   *  the one builder layer kind that rendered uncredited. */
  attribution?: string | null;
}

/**
 * One map layer a saved layer draws. `layer` is the layer as MapLibre adds it.
 * On a layer already on the map, a write keeps only the owned keys in step: it
 * sets each to the spec's value, or clears it when the spec leaves it out.
 */
export interface LayerSpec {
  layer: {
    id: string;
    type: LayerSpecification['type'];
    source: string;
    'source-layer'?: string;
    filter?: FilterSpecification;
    layout: Record<string, unknown>;
    paint: Record<string, unknown>;
  };
  ownedPaint: readonly PaintPropertyName[];
  ownedLayout: readonly LayoutPropertyName[];
}

/** An image the specs draw with: a sprite sheet by URL, or one image built only when the map lacks it. */
export type ImageSpec =
  | { kind: 'sprite'; id: string; url: string }
  | {
    kind: 'image';
    id: string;
    data: () => { width: number; height: number; data: Uint8ClampedArray };
    options?: { sdf?: boolean; pixelRatio?: number };
  };

/** The map layers an adapter draws for one saved layer, bottom first, and the images they use. */
export interface LayerDrawing {
  specs: readonly LayerSpec[];
  images: readonly ImageSpec[];
}

export interface LayerAdapter {
  type: 'fill' | 'line' | 'circle' | 'symbol' | 'raster' | 'heatmap' | 'hillshade' | 'cluster' | 'mixed';
  /** Present on the adapters whose layers the writer adds and updates. */
  describe?(input: AdapterLayerInput): LayerDrawing;
  addLayers(map: MaplibreMap, input: AdapterLayerInput): void;
  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void;
  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void;
  getLayerIds(layerId: string): string[];
}
