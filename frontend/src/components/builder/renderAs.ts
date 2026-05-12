import type { MapLayerResponse, MapLayerType, StyleConfig } from '@/types/api';

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

export type RenderAsAdapterType = 'circle' | 'symbol' | 'heatmap' | 'line' | 'fill' | 'raster' | 'hillshade';

export interface RenderAsPatch {
  layer_type?: MapLayerType | null;
  style_config?: StyleConfig | null;
  paint?: Record<string, unknown> | null;
  layout?: Record<string, unknown> | null;
}

export interface RenderAsMutation {
  patch: RenderAsPatch;
  adapterType: RenderAsAdapterType;
}

type RenderAsLayer = Pick<
  MapLayerResponse,
  | 'dataset_column_info'
  | 'dataset_geometry_type'
  | 'dataset_record_type'
  | 'is_dem'
  | 'layer_type'
  | 'paint'
  | 'style_config'
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

const DEFAULT_CIRCLE_PAINT = {
  'circle-color': '#3b82f6',
  'circle-radius': 5,
  'circle-stroke-color': '#ffffff',
  'circle-stroke-width': 1,
} as const;

const DEFAULT_HEATMAP_PAINT = {
  'heatmap-radius': 18,
  'heatmap-weight': 0.5,
  'heatmap-intensity': 1,
  'heatmap-opacity': 0.8,
} as const;

const DEFAULT_FILL_PAINT = {
  'fill-color': '#3b82f6',
  'fill-opacity': 0.45,
  'fill-outline-color': '#1d4ed8',
} as const;

const DEFAULT_HILLSHADE_PAINT = {
  'hillshade-illumination-direction': 335,
  'hillshade-illumination-anchor': 'viewport',
  'hillshade-exaggeration': 0.5,
  'hillshade-shadow-color': '#000000',
  'hillshade-highlight-color': '#ffffff',
  'hillshade-accent-color': '#000000',
} as const;

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

function compactRecord<T extends Record<string, unknown>>(value: T): T {
  return Object.fromEntries(
    Object.entries(value).filter(([, entry]) => entry !== undefined),
  ) as T;
}

function styleRecord(layer: RenderAsLayer): Record<string, unknown> {
  return { ...(layer.style_config ?? {}) };
}

function builderRecord(layer: RenderAsLayer): Record<string, unknown> {
  const builder = layer.style_config?.builder;
  return typeof builder === 'object' && builder !== null ? { ...builder } : {};
}

function styleWithBuilder(layer: RenderAsLayer, builder: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return compactRecord({
    ...styleRecord(layer),
    ...extra,
    builder: compactRecord(builder),
  }) as unknown as StyleConfig;
}

function styleWithoutRenderMode(layer: RenderAsLayer, extra: Record<string, unknown> = {}) {
  const style = styleRecord(layer);
  delete style.render_mode;
  return compactRecord({ ...style, ...extra }) as unknown as StyleConfig;
}

function numericHeightColumn(layer: RenderAsLayer) {
  const existing = builderHeightColumn(layer);
  if (existing) return existing;

  const numericColumn = layer.dataset_column_info?.find((column) => {
    const type = column.type.toLowerCase();
    return /(int|float|double|decimal|numeric|real|number)/.test(type);
  });
  return numericColumn?.name ?? layer.dataset_column_info?.[0]?.name ?? 'height';
}

function polygonPaint(layer: RenderAsLayer): Record<string, unknown> {
  return {
    ...DEFAULT_FILL_PAINT,
    ...(layer.paint ?? {}),
  };
}

function vectorLayerType(layer: RenderAsLayer): MapLayerType {
  return layer.layer_type === 'geojson' ? 'geojson' : 'vector_geolens';
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

export function buildRenderAsPatch(layer: RenderAsLayer, renderAs: RenderAsId): RenderAsMutation | null {
  if (!getRenderAsOptions(layer).some((option) => option.id === renderAs)) return null;

  if (renderAs === 'point') {
    const style = styleWithoutRenderMode(layer, {
      heatmapPaint: getCurrentRenderAs(layer) === 'heatmap' ? { ...(layer.paint ?? {}) } : layer.style_config?.heatmapPaint,
      savedCirclePaint: undefined,
      symbol: undefined,
    });
    const savedCirclePaint = layer.style_config?.savedCirclePaint;
    return {
      adapterType: 'circle',
      patch: {
        layer_type: vectorLayerType(layer),
        paint: savedCirclePaint && Object.keys(savedCirclePaint).length > 0
          ? { ...savedCirclePaint }
          : { ...DEFAULT_CIRCLE_PAINT },
        style_config: style,
      },
    };
  }

  if (renderAs === 'symbol') {
    return {
      adapterType: 'symbol',
      patch: {
        layer_type: vectorLayerType(layer),
        paint: { ...(layer.style_config?.savedCirclePaint ?? layer.paint ?? DEFAULT_CIRCLE_PAINT) },
        style_config: compactRecord({
          ...styleRecord(layer),
          render_mode: 'symbol',
          savedCirclePaint: layer.style_config?.savedCirclePaint ?? { ...(layer.paint ?? DEFAULT_CIRCLE_PAINT) },
          symbol: layer.style_config?.symbol ?? {
            iconImage: 'marker',
            iconSize: 1,
            iconRotation: 0,
            iconAnchor: 'center',
            iconOffset: [0, 0],
          },
        }) as unknown as StyleConfig,
      },
    };
  }

  if (renderAs === 'heatmap') {
    return {
      adapterType: 'heatmap',
      patch: {
        layer_type: vectorLayerType(layer),
        paint: { ...(layer.style_config?.heatmapPaint ?? DEFAULT_HEATMAP_PAINT) },
        style_config: compactRecord({
          ...styleRecord(layer),
          render_mode: 'heatmap',
          savedCirclePaint: getCurrentRenderAs(layer) === 'heatmap'
            ? layer.style_config?.savedCirclePaint
            : { ...(layer.paint ?? DEFAULT_CIRCLE_PAINT) },
          builder: compactRecord({
            ...builderRecord(layer),
            heatmapRamp: layer.style_config?.builder?.heatmapRamp ?? 'YlOrRd',
          }),
        }) as unknown as StyleConfig,
      },
    };
  }

  if (renderAs === 'line') {
    return {
      adapterType: 'line',
      patch: {
        layer_type: vectorLayerType(layer),
        style_config: styleWithoutRenderMode(layer),
      },
    };
  }

  if (renderAs === 'fill' || renderAs === 'stroke' || renderAs === 'fill-stroke' || renderAs === 'extrusion-3d') {
    const builder = builderRecord(layer);
    const priorHeightScale = builder.heightScale;
    const priorExtrusionMinZoom = builder.extrusionMinZoom;
    const priorExtrusionOpacity = builder.extrusionOpacity;
    delete builder.heightColumn;
    delete builder.heightScale;
    delete builder.extrusionMinZoom;
    delete builder.extrusionOpacity;

    if (renderAs === 'fill') {
      builder.fillDisabled = false;
      builder.strokeDisabled = true;
    } else if (renderAs === 'stroke') {
      builder.fillDisabled = true;
      builder.strokeDisabled = false;
    } else {
      builder.fillDisabled = false;
      builder.strokeDisabled = false;
    }

    const paint = polygonPaint(layer);
    if (renderAs === 'stroke') {
      paint['fill-opacity'] = 0;
    } else if (typeof paint['fill-opacity'] !== 'number' || paint['fill-opacity'] <= 0) {
      paint['fill-opacity'] = DEFAULT_FILL_PAINT['fill-opacity'];
    }

    if (renderAs === 'extrusion-3d') {
      builder.heightColumn = numericHeightColumn(layer);
      builder.heightScale = typeof priorHeightScale === 'number' ? priorHeightScale : 1;
      builder.extrusionMinZoom = typeof priorExtrusionMinZoom === 'number' ? priorExtrusionMinZoom : 14;
      builder.extrusionOpacity = typeof priorExtrusionOpacity === 'number' ? priorExtrusionOpacity : Math.min(0.85, 1);
    }

    return {
      adapterType: 'fill',
      patch: {
        layer_type: vectorLayerType(layer),
        paint,
        style_config: styleWithBuilder(layer, builder, { render_mode: undefined }),
      },
    };
  }

  if (renderAs === 'image') {
    return {
      adapterType: 'raster',
      patch: {
        layer_type: 'raster_geolens',
        style_config: styleWithoutRenderMode(layer),
        paint: { ...(layer.paint ?? {}) },
      },
    };
  }

  if (renderAs === 'hillshade') {
    return {
      adapterType: 'hillshade',
      patch: {
        layer_type: 'raster_geolens',
        style_config: compactRecord({
          ...styleRecord(layer),
          render_mode: 'hillshade',
        }) as unknown as StyleConfig,
        paint: { ...DEFAULT_HILLSHADE_PAINT, ...(layer.paint ?? {}) },
      },
    };
  }

  return null;
}
