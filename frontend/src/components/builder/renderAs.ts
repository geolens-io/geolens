import type { MapLayerResponse } from '@/types/api';

export type RenderAsId =
  | 'point'
  | 'symbol'
  | 'heatmap'
  | 'line'
  | 'fill'
  | 'stroke'
  | 'fill-stroke'
  | 'extrusion-3d'
  | 'image'
  | 'hillshade';

export type RenderAsSource =
  | 'vector-point'
  | 'vector-line'
  | 'vector-polygon'
  | 'raster'
  | 'raster-dem'
  | 'unsupported';

export interface RenderAsOption {
  id: RenderAsId;
  label: string;
  source: RenderAsSource;
}

type RenderAsLayer = Pick<
  MapLayerResponse,
  'dataset_geometry_type' | 'dataset_record_type' | 'is_dem' | 'layer_type' | 'paint' | 'style_config'
>;

export const RENDER_AS_WRITABLE_FIELDS = ['layer_type', 'style_config', 'paint', 'layout'] as const;

export const UNSUPPORTED_V1002_RENDERERS = [
  'cluster',
  'hexbin',
  'h3',
  'arrow',
  'animated-path',
  'point-extrusion-3d',
  'timeline',
  'recipes',
  'cross-layer-filters',
  'blend-mode',
] as const;

const OPTIONS_BY_SOURCE: Record<Exclude<RenderAsSource, 'unsupported'>, RenderAsOption[]> = {
  'vector-point': [
    { id: 'point', label: 'Point', source: 'vector-point' },
    { id: 'symbol', label: 'Symbol', source: 'vector-point' },
    { id: 'heatmap', label: 'Heatmap', source: 'vector-point' },
  ],
  'vector-line': [
    { id: 'line', label: 'Line', source: 'vector-line' },
  ],
  'vector-polygon': [
    { id: 'fill', label: 'Fill', source: 'vector-polygon' },
    { id: 'stroke', label: 'Stroke', source: 'vector-polygon' },
    { id: 'fill-stroke', label: 'Fill + Stroke', source: 'vector-polygon' },
    { id: 'extrusion-3d', label: '3D extrusion', source: 'vector-polygon' },
  ],
  raster: [
    { id: 'image', label: 'Image', source: 'raster' },
  ],
  'raster-dem': [
    { id: 'image', label: 'Image', source: 'raster-dem' },
    { id: 'hillshade', label: 'Hillshade', source: 'raster-dem' },
  ],
};

function isRasterLayer(layer: RenderAsLayer) {
  return (
    layer.layer_type === 'raster_geolens'
    || layer.dataset_record_type === 'raster_dataset'
    || layer.dataset_record_type === 'vrt_dataset'
  );
}

function geometryFamily(geometryType: string | null): 'point' | 'line' | 'polygon' | null {
  const normalized = (geometryType ?? '').toUpperCase();
  if (normalized.includes('POINT')) return 'point';
  if (normalized.includes('LINE')) return 'line';
  if (normalized.includes('POLYGON')) return 'polygon';
  return null;
}

function truthyBuilderFlag(value: unknown) {
  return value === true || value === 'true';
}

function builderHeightColumn(layer: RenderAsLayer) {
  const builder = layer.style_config?.builder;
  return typeof builder?.heightColumn === 'string' && builder.heightColumn.trim()
    ? builder.heightColumn
    : typeof layer.paint?.['_height_column'] === 'string' && layer.paint._height_column.trim()
      ? layer.paint._height_column
      : null;
}

export function getRenderAsSource(layer: RenderAsLayer): RenderAsSource {
  if (isRasterLayer(layer)) {
    return layer.is_dem === true ? 'raster-dem' : 'raster';
  }

  const family = geometryFamily(layer.dataset_geometry_type);
  if (family === 'point') return 'vector-point';
  if (family === 'line') return 'vector-line';
  if (family === 'polygon') return 'vector-polygon';
  return 'unsupported';
}

export function getRenderAsOptions(layer: RenderAsLayer): RenderAsOption[] {
  const source = getRenderAsSource(layer);
  if (source === 'unsupported') return [];
  return OPTIONS_BY_SOURCE[source];
}

export function getCurrentRenderAs(layer: RenderAsLayer): RenderAsId | null {
  const source = getRenderAsSource(layer);
  const renderMode = layer.style_config?.render_mode;

  if (source === 'raster-dem') {
    return renderMode === 'hillshade' ? 'hillshade' : 'image';
  }

  if (source === 'raster') {
    return 'image';
  }

  if (source === 'vector-point') {
    if (renderMode === 'heatmap') return 'heatmap';
    if (renderMode === 'symbol') return 'symbol';
    return 'point';
  }

  if (source === 'vector-line') {
    return 'line';
  }

  if (source === 'vector-polygon') {
    if (builderHeightColumn(layer)) return 'extrusion-3d';

    const builder = layer.style_config?.builder;
    const fillDisabled = truthyBuilderFlag(builder?.fillDisabled ?? layer.paint?.['_fill-disabled']);
    const strokeDisabled = truthyBuilderFlag(builder?.strokeDisabled ?? layer.paint?.['_stroke-disabled']);

    if (fillDisabled && !strokeDisabled) return 'stroke';
    if (!fillDisabled && strokeDisabled) return 'fill';
    return 'fill-stroke';
  }

  return null;
}

export function isSupportedRenderAsId(value: string): value is RenderAsId {
  return Object.values(OPTIONS_BY_SOURCE).some((options) => (
    options.some((option) => option.id === value)
  ));
}
