import type {
  FilterSpecification,
  GeoJSONSourceSpecification,
  RasterDEMSourceSpecification,
  RasterSourceSpecification,
  SourceSpecification,
  VectorSourceSpecification,
} from 'maplibre-gl';
import type { TileToken, UnsignedRasterTileTemplate } from '@/api/tiles';
import { effectiveDemRenderMode } from '@/lib/dem-render-mode';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import { extractPlaceholders } from '@/lib/popup-template';
import { buildClusterTileUrl, buildSignedTileUrl, getMvtSourceLayerName } from '@/lib/tile-utils';
import type { LabelConfig, PopupConfig, StyleConfig } from '@/types/api';
import { getClusterSourceStrategy } from './cluster-source';
import { getCompanionLayerIds } from './companion-ids';
import { getClusterSourceOptions } from './layer-adapters/cluster-adapter';
import { buildColormapTileUrl } from './layer-adapters/raster-adapter';
import { FULL_ZOOM_RANGE } from './layer-adapters/builder-defaults';
import { getAdapter } from './layer-adapters/registry';
import { normalizeRasterBounds, resolveAdapterType } from './layer-adapters/shared';
import { resolveSymbolConfig } from './layer-adapters/symbol-adapter';
import type { AdapterLayerInput, ImageSpec, LayerAdapter, LayerSpec } from './layer-adapters/types';
import type { SyncLayerInput } from './map-sync';

/** What describing layers depends on besides the layers themselves. */
export interface RenderContext {
  /** Prefix for map ids: '' in the builder, 'viewer-' in the viewer. */
  idPrefix: string;
  /** The page origin that relative tile URLs resolve against. */
  origin: string;
  /** Where vector tiles are served from; `${origin}/api` when unset. */
  tileBaseUrl: string | undefined;
  /** The tenant prefix of MVT layer names. Null means it has not resolved, and describing throws. */
  sourceLayerPrefix: string | null | undefined;
  /** Tile tokens by dataset id. A vector layer without one gets an unsigned URL. */
  tokens: ReadonlyMap<string, TileToken>;
  /** Bounded GeoJSON by layer id. A cluster layer that needs it and lacks it draws as circles. */
  boundedGeoJson: ReadonlyMap<string, GeoJSON.FeatureCollection>;
}

/** A layer's zoom range, as `setLayerZoomRange` takes it. */
export interface ZoomRange {
  minzoom: number;
  maxzoom: number;
}

/** How the map draws one saved layer. */
export interface DescribedLayer {
  /** The primary map layer id. */
  id: string;
  /** The adapter that draws the layer. */
  drawsAs: LayerAdapter['type'];
  /** The source the layer draws from. `Description.sources` lacks it when a raster layer has no tile URL. */
  sourceId: string;
  /** The MVT layer name a vector layer reads from its source. */
  sourceLayer: string;
  filter: FilterSpecification | null;
  /** The saved layout without its private `_` keys. */
  layout: Record<string, unknown>;
  /** From the layout's `_minzoom` and `_maxzoom`; null when it saves neither. */
  zoom: ZoomRange | null;
  /** The map layers drawn for the layer, bottom first. Empty while its adapter still adds its own layers. */
  specs: readonly LayerSpec[];
  /** The images those map layers use. */
  images: readonly ImageSpec[];
}

export interface Description {
  /** Every source the layers draw from, by source id. */
  sources: ReadonlyMap<string, SourceSpecification>;
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

/** The fields `getSourceIdForLayer` reads. SyncLayerInput and MapLayerResponse both satisfy it. */
export interface SourceIdLayer {
  id: string;
  dataset_table_name?: string | null;
  dataset_geometry_type?: string | null;
  dataset_record_type?: string | null;
  style_config?: Pick<StyleConfig, 'render_mode'> | null;
  feature_count?: number | null;
  dataset_feature_count?: number | null;
  is_dem?: boolean | null;
  layer_type?: string | null;
}

/** The source a layer draws from. Vector layers on one table share `source-data-<table>`;
 *  cluster, raster and DEM layers, and layers without a table, keep `source-<id>`. */
export function getSourceIdForLayer(layer: SourceIdLayer, prefix?: string) {
  // A cluster's radius and max zoom are per layer, so each cluster layer needs its own source.
  if (getClusterSourceStrategy(layer).kind !== 'fallback') {
    return getCompanionLayerIds(layer.id, prefix).source;
  }
  if (layer.is_dem === true || layer.layer_type === 'raster_geolens') {
    return getCompanionLayerIds(layer.id, prefix).source;
  }
  if (typeof layer.dataset_table_name === 'string' && layer.dataset_table_name.length > 0) {
    return `${prefix ?? ''}source-data-${layer.dataset_table_name}`;
  }
  return getCompanionLayerIds(layer.id, prefix).source;
}

/** The feature columns a layer's style, label, filter and popup read. Below z10 the tile
 *  server keeps only the columns a tile URL's `cols=` names, so each one must be listed. */
export function getDataDrivenColumnsForLayer(
  layer: {
    style_config?: StyleConfig | null;
    paint?: Record<string, unknown>;
    label_config?: LabelConfig | null;
    filter?: FilterSpecification | unknown[] | null;
    popup_config?: PopupConfig | null;
  },
): string[] {
  const cols = new Set<string>();
  const styleCol = layer.style_config?.column;
  if (typeof styleCol === 'string' && styleCol) cols.add(styleCol);
  const paint = layer.paint ?? {};
  const heatmapWeight = paint['_heatmap-weight-column'];
  if (typeof heatmapWeight === 'string' && heatmapWeight) cols.add(heatmapWeight);
  const heightCol = paint['_height_column'];
  if (typeof heightCol === 'string' && heightCol) cols.add(heightCol);
  // The label text and a symbol's category icon are layout expressions the paint walk never sees.
  const labelCol = layer.label_config?.column;
  if (typeof labelCol === 'string' && labelCol) cols.add(labelCol);
  // Resolved through the symbol adapter's own merge, which also reads `builder.symbol`.
  const symbolCol = resolveSymbolConfig(layer.style_config).categoryColumn;
  if (typeof symbolCol === 'string' && symbolCol) cols.add(symbolCol);
  function walk(node: unknown): void {
    if (!Array.isArray(node) || node.length === 0) return;
    if ((node[0] === 'get' || node[0] === 'has') && typeof node[1] === 'string') {
      cols.add(node[1]);
      return;
    }
    for (const child of node) walk(child);
  }
  for (const val of Object.values(paint)) walk(val);
  if (layer.filter) walk(layer.filter);
  const popup = layer.popup_config;
  if (popup && popup.enabled !== false) {
    if (popup.expression) {
      for (const c of extractPlaceholders(popup.expression)) cols.add(c);
    }
    if (popup.visible_fields) {
      for (const c of popup.visible_fields) {
        if (typeof c === 'string' && c) cols.add(c);
      }
    }
  }
  return Array.from(cols);
}

/** Union of data-driven columns across every layer sharing a source. */
export function getDataDrivenColumnsForSource(
  sourceId: string,
  layers: readonly SourceIdLayer[],
  prefix?: string,
): string[] {
  const cols = new Set<string>();
  for (const layer of layers) {
    if (getSourceIdForLayer(layer, prefix) !== sourceId) continue;
    for (const c of getDataDrivenColumnsForLayer(layer as Parameters<typeof getDataDrivenColumnsForLayer>[0])) {
      cols.add(c);
    }
  }
  return Array.from(cols);
}

/** Whether a layer on the source draws a line gradient, which needs `lineMetrics`. The
 *  builder's `lineGradient` intent counts only as a non-empty object, as the backend reads it. */
function lineGradientNeededFor(sourceId: string, layers: readonly SyncLayerInput[], prefix: string) {
  return layers.some((layer) => {
    if (getSourceIdForLayer(layer, prefix) !== sourceId) return false;
    if ((layer.paint ?? {})['line-gradient'] != null) return true;
    const intent = (layer.style_config as { builder?: { lineGradient?: unknown } } | null | undefined)
      ?.builder?.lineGradient;
    return intent != null
      && typeof intent === 'object'
      && !Array.isArray(intent)
      && Object.keys(intent).length > 0;
  });
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

/** A world view requests z0 tiles. */
const VECTOR_SOURCE_MINZOOM = 0;
/** The server stops simplifying before z14, so MapLibre overzooms z14 tiles instead of querying every zoom. */
const VECTOR_SOURCE_MAXZOOM = 14;
/** The server clusters only up to a layer's cluster max zoom, so single points need tiles past z14. */
const CLUSTER_SOURCE_MAXZOOM = 22;

function clusterOptions(layer: SyncLayerInput) {
  return getClusterSourceOptions({ style_config: layer.style_config } as AdapterLayerInput);
}

function nonBlank(value: string | null | undefined) {
  return value ? value : undefined;
}

/** A raster layer's unsigned tile template, from its saved `tile_url`, for a map without raster tokens. */
function rasterTokenFromLayer(layer: SyncLayerInput): UnsignedRasterTileTemplate | null {
  if (!layer.tile_url) return null;
  return {
    kind: 'raster',
    tile_url: layer.tile_url,
    bounds: layer.bounds ?? null,
    minzoom: layer.minzoom ?? 0,
    maxzoom: layer.maxzoom ?? 18,
    tile_size: layer.tile_size ?? 256,
    format: layer.format ?? 'png',
  };
}

function rasterSource(
  layer: SyncLayerInput,
  hillshade: boolean,
  ctx: RenderContext,
): RasterSourceSpecification | RasterDEMSourceSpecification | null {
  const token = ctx.tokens.get(layer.dataset_id);
  const template = token?.kind === 'raster' ? token : rasterTokenFromLayer(layer);
  if (!template) return null;
  // A DEM's terrain-RGB tiles take no colormap or stretch parameters.
  const url = hillshade ? template.tile_url : buildColormapTileUrl(template.tile_url, layer.paint ?? {});
  const bounds = normalizeRasterBounds(template.bounds);
  const attribution = nonBlank(layer.attribution);
  const spec = {
    tiles: [url.startsWith('http') ? url : `${ctx.origin}${url}`],
    tileSize: template.tile_size ?? 256,
    minzoom: template.minzoom ?? 0,
    maxzoom: template.maxzoom ?? 18,
    ...(bounds ? { bounds } : {}),
    ...(attribution ? { attribution } : {}),
  };
  return hillshade
    ? { type: 'raster-dem', ...spec, encoding: 'mapbox' }
    : { type: 'raster', ...spec };
}

function vectorSource(
  layer: SyncLayerInput,
  described: DescribedLayer,
  drawn: readonly SyncLayerInput[],
  ctx: RenderContext,
): VectorSourceSpecification | GeoJSONSourceSpecification {
  const attribution = nonBlank(layer.attribution);
  const data = ctx.boundedGeoJson.get(layer.id);
  if (described.drawsAs === 'cluster' && getClusterSourceStrategy(layer).kind === 'bounded-geojson' && data) {
    return { type: 'geojson', data, cluster: true, ...clusterOptions(layer), ...(attribution ? { attribution } : {}) };
  }
  const serverCluster = described.drawsAs === 'cluster';
  const token = ctx.tokens.get(layer.dataset_id);
  const vectorToken = token?.kind === 'vector' ? token : null;
  const tileBaseUrl = ctx.tileBaseUrl || `${ctx.origin}/api`;
  const tileVersion = layer.tile_version ?? undefined;
  const cols = getDataDrivenColumnsForSource(described.sourceId, drawn, ctx.idPrefix);
  const bounds = normalizeRasterBounds(layer.bounds);
  return {
    type: 'vector',
    tiles: [serverCluster
      ? buildClusterTileUrl(layer.dataset_table_name, vectorToken, tileBaseUrl, tileVersion, clusterOptions(layer), cols)
      : buildSignedTileUrl(layer.dataset_table_name, vectorToken, tileBaseUrl, tileVersion, cols)],
    minzoom: VECTOR_SOURCE_MINZOOM,
    maxzoom: serverCluster ? CLUSTER_SOURCE_MAXZOOM : VECTOR_SOURCE_MAXZOOM,
    ...(lineGradientNeededFor(described.sourceId, drawn, ctx.idPrefix) ? { lineMetrics: true } : {}),
    ...(bounds ? { bounds } : {}),
    ...(attribution ? { attribution } : {}),
  };
}

/**
 * Describe how the map draws each layer and the sources it draws them from.
 * Folder rows and terrain-mode DEMs get no entry. A source takes its dataset
 * facts from the first layer on it, and its `cols=` and `lineMetrics` from all.
 */
export function describeLayers(layers: readonly SyncLayerInput[], ctx: RenderContext): Description {
  const drawn = layers.filter((layer) => !isFolderGroupLayer(layer) && !isDemTerrainVisualSuppressed(layer));
  const sources = new Map<string, SourceSpecification>();
  const described: DescribedLayer[] = [];
  for (const layer of drawn) {
    const layout = layer.layout ?? {};
    const entry: DescribedLayer = {
      id: getCompanionLayerIds(layer.id, ctx.idPrefix).layer,
      drawsAs: drawsAs(layer, ctx),
      sourceId: getSourceIdForLayer(layer, ctx.idPrefix),
      sourceLayer: getMvtSourceLayerName(layer.dataset_table_name, ctx.sourceLayerPrefix),
      filter: sanitizeNullableNumericFilter(layer.filter),
      layout: stripPrivateLayoutKeys(layout),
      zoom: zoomRange(layout),
      specs: [],
      images: [],
    };
    described.push(entry);
    if (!sources.has(entry.sourceId)) {
      const source = entry.drawsAs === 'raster' || entry.drawsAs === 'hillshade'
        ? rasterSource(layer, entry.drawsAs === 'hillshade', ctx)
        : vectorSource(layer, entry, drawn, ctx);
      if (source) sources.set(entry.sourceId, source);
    }
    const sourceType = sources.get(entry.sourceId)?.type === 'geojson' ? 'geojson' : 'vector';
    // An adapter can throw on a saved style it cannot read. That layer draws
    // nothing, and every other layer is still described.
    try {
      const drawing = getAdapter(entry.drawsAs).describe?.({ ...adapterInputFor(layer, entry), sourceType });
      if (drawing) {
        entry.specs = drawing.specs;
        entry.images = drawing.images;
      }
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] describing ${entry.id} failed:`, e);
    }
  }
  return { sources, layers: described };
}

/**
 * The adapter input for a described layer. Its ids, layout and filter come from
 * the description and the rest from the layer. A `pending` paint or opacity
 * stands in for the layer's own when the write has not reached the layer yet.
 */
export function adapterInputFor(
  layer: SyncLayerInput,
  described: DescribedLayer,
  pending: { tileUrl?: string; paint?: Record<string, unknown>; opacity?: number } = {},
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
    sourceId: described.sourceId,
    layerId: described.id,
    sourceLayer: described.sourceLayer,
    tileUrl: pending.tileUrl ?? '',
  };
}
