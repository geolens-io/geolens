import type { FilterSpecification } from 'maplibre-gl';
import { effectiveDemRenderMode } from '@/lib/dem-render-mode';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import type { StyleConfig } from '@/types/api';
import { getClusterSourceStrategy } from './cluster-source';
import { getCompanionLayerIds } from './companion-ids';
import { getAdapter } from './layer-adapters/registry';
import { resolveAdapterType } from './layer-adapters/shared';
import type { AdapterLayerInput, LayerAdapter } from './layer-adapters/types';
import type { SyncLayerInput } from './map-sync';

/** What describing a layer depends on besides the layer itself. */
export interface RenderContext {
  /** Prefix for map ids: '' in the builder, 'viewer-' in the viewer. */
  idPrefix: string;
  /** Bounded GeoJSON by layer id. A cluster layer that needs it and lacks it draws as circles. */
  boundedGeoJson: ReadonlyMap<string, GeoJSON.FeatureCollection>;
}

/** A layer's zoom range, as `setLayerZoomRange` takes it. */
export interface ZoomRange {
  minzoom: number;
  maxzoom: number;
}

/** The builder's zoom bounds, which stand in for an end of the range the layout does not save. */
export const FULL_ZOOM_RANGE: ZoomRange = { minzoom: 0, maxzoom: 22 };

/** How the map draws one saved layer. */
export interface DescribedLayer {
  /** The primary map layer id. */
  id: string;
  /** The adapter that draws the layer. */
  drawsAs: LayerAdapter['type'];
  filter: FilterSpecification | null;
  /** The saved layout without its private `_` keys. */
  layout: Record<string, unknown>;
  /** From the layout's `_minzoom` and `_maxzoom`; null when it saves neither. */
  zoom: ZoomRange | null;
}

export interface Description {
  /** In stack order, leaving out the layers the map draws nothing for. */
  layers: readonly DescribedLayer[];
}

/** A DEM in terrain mode shapes the terrain mesh and draws no layer of its own. */
export function isDemTerrainVisualSuppressed(layer: {
  is_dem?: boolean | null;
  style_config?: Pick<StyleConfig, 'render_mode'> | null;
}) {
  return layer.is_dem === true
    && (layer.style_config as { render_mode?: unknown } | null | undefined)?.render_mode === 'terrain';
}

/** Raster datasets and DEMs draw from raster tiles. */
export function isRasterLikeLayer(
  layer: Pick<SyncLayerInput, 'is_dem' | 'layer_type' | 'dataset_record_type'>,
) {
  return layer.is_dem === true
    || layer.layer_type === 'raster_geolens'
    || layer.dataset_record_type === 'raster_dataset'
    || layer.dataset_record_type === 'vrt_dataset';
}

/** MapLibre's addLayer rejects an unknown layout property and drops the whole
 *  layer, so the builder's private `_` keys never reach it. */
function stripPrivateLayoutKeys(layout: Record<string, unknown>): Record<string, unknown> {
  if (!Object.keys(layout).some((k) => k.startsWith('_'))) return layout;
  return Object.fromEntries(Object.entries(layout).filter(([k]) => !k.startsWith('_')));
}

function zoomRange(layout: Record<string, unknown>): ZoomRange | null {
  const minzoom = layout['_minzoom'];
  const maxzoom = layout['_maxzoom'];
  if (typeof minzoom !== 'number' && typeof maxzoom !== 'number') return null;
  return {
    minzoom: typeof minzoom === 'number' ? minzoom : FULL_ZOOM_RANGE.minzoom,
    maxzoom: typeof maxzoom === 'number' ? maxzoom : FULL_ZOOM_RANGE.maxzoom,
  };
}

function canDrawCluster(layer: SyncLayerInput, ctx: RenderContext) {
  const { kind } = getClusterSourceStrategy(layer);
  return kind === 'server-tile' || (kind === 'bounded-geojson' && ctx.boundedGeoJson.has(layer.id));
}

function drawsAs(layer: SyncLayerInput, ctx: RenderContext): LayerAdapter['type'] {
  if (isRasterLikeLayer(layer)) {
    return layer.is_dem === true && effectiveDemRenderMode(layer.style_config, layer.is_dem) === 'hillshade'
      ? 'hillshade'
      : 'raster';
  }
  const type = resolveAdapterType(layer.dataset_geometry_type, layer.style_config, layer.paint);
  if (type === 'cluster' && !canDrawCluster(layer, ctx)) return 'circle';
  return getAdapter(type).type;
}

/** Describe how the map draws each layer. Folder rows and terrain-mode DEMs get no entry. */
export function describeLayers(layers: readonly SyncLayerInput[], ctx: RenderContext): Description {
  const described: DescribedLayer[] = [];
  for (const layer of layers) {
    if (isFolderGroupLayer(layer) || isDemTerrainVisualSuppressed(layer)) continue;
    const layout = layer.layout ?? {};
    described.push({
      id: getCompanionLayerIds(layer.id, ctx.idPrefix).layer,
      drawsAs: drawsAs(layer, ctx),
      filter: sanitizeNullableNumericFilter(layer.filter),
      layout: stripPrivateLayoutKeys(layout),
      zoom: zoomRange(layout),
    });
  }
  return { layers: described };
}

/** The source an adapter input reads, which the caller supplies. */
export interface AdapterSource {
  sourceId: string;
  sourceLayer: string;
  tileUrl: string;
}

/**
 * The adapter input for a described layer. Its layer id, layout and filter come
 * from the description, its source from the caller and the rest from the layer.
 * A `pending` paint or opacity stands in for the layer's own when the write has
 * not reached the layer yet.
 */
export function adapterInputFor(
  layer: SyncLayerInput,
  described: DescribedLayer,
  source: AdapterSource,
  pending: { paint?: Record<string, unknown>; opacity?: number } = {},
): AdapterLayerInput {
  return {
    id: layer.id,
    dataset_table_name: layer.dataset_table_name,
    dataset_geometry_type: layer.dataset_geometry_type,
    opacity: pending.opacity ?? layer.opacity ?? 1,
    visible: layer.visible,
    paint: pending.paint ?? layer.paint ?? {},
    layout: described.layout,
    filter: described.filter,
    label_config: layer.label_config,
    style_config: layer.style_config ?? null,
    is_dem: layer.is_dem,
    sourceId: source.sourceId,
    layerId: described.id,
    sourceLayer: source.sourceLayer,
    tileUrl: source.tileUrl,
  };
}
