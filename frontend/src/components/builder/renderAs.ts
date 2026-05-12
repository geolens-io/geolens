import type { MapLayerResponse, MapLayerType, StyleConfig } from '@/types/api';
import { getClusterSourceEligibility } from './cluster-source';

export type RenderAsId =
  | 'point'
  | 'symbol'
  | 'heatmap'
  | 'cluster'
  | 'line'
  | 'arrow'
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

export type RendererBackend = 'maplibre' | 'deckgl-future';
export type RendererSourceRequirement =
  | 'vector-tile'
  | 'geojson'
  | 'raster'
  | 'raster-dem'
  | 'h3-column'
  | 'path-timestamp';

export interface RendererCapability {
  id: RenderAsId;
  label: string;
  source: Exclude<RenderAsSource, 'unsupported'>;
  backend: RendererBackend;
  sourceRequirement: RendererSourceRequirement;
  writableFields: readonly (typeof RENDER_AS_WRITABLE_FIELDS)[number][];
  companionLayers: readonly string[];
  viewerSupport: 'native' | 'fallback' | 'unsupported';
  styleJsonSupport: 'native' | 'fallback' | 'unsupported';
  enabled: boolean;
  requiresBoundedGeoJson?: boolean;
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
  | 'dataset_feature_count'
  | 'dataset_geometry_type'
  | 'dataset_record_type'
  | 'is_dem'
  | 'layer_type'
  | 'paint'
  | 'style_config'
>;

export const RENDER_AS_WRITABLE_FIELDS = ['layer_type', 'style_config', 'paint', 'layout'] as const;

export const UNSUPPORTED_V1002_RENDERERS = [
  'hexbin',
  'h3',
  'animated-path',
  'point-extrusion-3d',
  'timeline',
  'recipes',
  'cross-layer-filters',
  'blend-mode',
] as const;

function capability(
  id: RenderAsId,
  label: string,
  source: Exclude<RenderAsSource, 'unsupported'>,
  options: Pick<RendererCapability, 'backend' | 'sourceRequirement' | 'companionLayers' | 'viewerSupport' | 'styleJsonSupport' | 'requiresBoundedGeoJson'>,
): RendererCapability {
  return {
    id,
    label,
    source,
    writableFields: RENDER_AS_WRITABLE_FIELDS,
    enabled: true,
    ...options,
  };
}

export const RENDERER_CAPABILITIES: readonly RendererCapability[] = [
  capability('point', 'Point', 'vector-point', {
    backend: 'maplibre',
    sourceRequirement: 'vector-tile',
    companionLayers: [],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
  capability('symbol', 'Symbol', 'vector-point', {
    backend: 'maplibre',
    sourceRequirement: 'vector-tile',
    companionLayers: [],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
  capability('heatmap', 'Heatmap', 'vector-point', {
    backend: 'maplibre',
    sourceRequirement: 'vector-tile',
    companionLayers: [],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
  capability('cluster', 'Cluster', 'vector-point', {
    backend: 'maplibre',
    sourceRequirement: 'geojson',
    companionLayers: ['cluster', 'cluster-count', 'unclustered'],
    viewerSupport: 'native',
    styleJsonSupport: 'fallback',
    requiresBoundedGeoJson: true,
  }),
  capability('line', 'Line', 'vector-line', {
    backend: 'maplibre',
    sourceRequirement: 'vector-tile',
    companionLayers: [],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
  capability('arrow', 'Arrow', 'vector-line', {
    backend: 'maplibre',
    sourceRequirement: 'vector-tile',
    companionLayers: ['arrow'],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
  capability('fill', 'Fill', 'vector-polygon', {
    backend: 'maplibre',
    sourceRequirement: 'vector-tile',
    companionLayers: ['outline'],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
  capability('stroke', 'Stroke', 'vector-polygon', {
    backend: 'maplibre',
    sourceRequirement: 'vector-tile',
    companionLayers: ['outline'],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
  capability('fill-stroke', 'Fill + Stroke', 'vector-polygon', {
    backend: 'maplibre',
    sourceRequirement: 'vector-tile',
    companionLayers: ['outline'],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
  capability('extrusion-3d', '3D extrusion', 'vector-polygon', {
    backend: 'maplibre',
    sourceRequirement: 'vector-tile',
    companionLayers: ['outline', 'extrusion'],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
  capability('image', 'Image', 'raster', {
    backend: 'maplibre',
    sourceRequirement: 'raster',
    companionLayers: [],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
  capability('image', 'Image', 'raster-dem', {
    backend: 'maplibre',
    sourceRequirement: 'raster-dem',
    companionLayers: [],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
  capability('hillshade', 'Hillshade', 'raster-dem', {
    backend: 'maplibre',
    sourceRequirement: 'raster-dem',
    companionLayers: [],
    viewerSupport: 'native',
    styleJsonSupport: 'native',
  }),
];

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

function styleWithoutRenderModeAndBuilderKeys(layer: RenderAsLayer, builderKeys: string[]) {
  const style = styleRecord(layer);
  delete style.render_mode;
  const builder = builderRecord(layer);
  for (const key of builderKeys) {
    delete builder[key];
  }
  const compactBuilderValue = compactRecord(builder);
  if (Object.keys(compactBuilderValue).length > 0) {
    style.builder = compactBuilderValue;
  } else {
    delete style.builder;
  }
  return compactRecord(style) as unknown as StyleConfig;
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
  return getRendererCapabilities(layer).map((capabilityEntry) => ({
    id: capabilityEntry.id,
    label: capabilityEntry.label,
    source: capabilityEntry.source,
  }));
}

export function getRendererCapabilities(layer: RenderAsLayer): RendererCapability[] {
  const source = getRenderAsSource(layer);
  if (source === 'unsupported') return [];
  return RENDERER_CAPABILITIES.filter((entry) => {
    if (!entry.enabled || entry.source !== source) return false;
    if (entry.requiresBoundedGeoJson) return getClusterSourceEligibility(layer).eligible;
    return true;
  });
}

export function getRendererCapability(id: RenderAsId, layer?: RenderAsLayer): RendererCapability | null {
  const entries = layer ? getRendererCapabilities(layer) : RENDERER_CAPABILITIES.filter((entry) => entry.enabled);
  return entries.find((entry) => entry.id === id) ?? null;
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
    if (renderMode === 'cluster' && getClusterSourceEligibility(layer).eligible) return 'cluster';
    if (renderMode === 'heatmap') return 'heatmap';
    if (renderMode === 'symbol') return 'symbol';
    return 'point';
  }

  if (source === 'vector-line') {
    if (renderMode === 'arrow') return 'arrow';
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
  return RENDERER_CAPABILITIES.some((entry) => entry.enabled && entry.id === value);
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

  if (renderAs === 'cluster') {
    const circlePaint = { ...(layer.paint ?? DEFAULT_CIRCLE_PAINT) };
    const clusterColor = typeof circlePaint['circle-color'] === 'string'
      ? circlePaint['circle-color']
      : DEFAULT_CIRCLE_PAINT['circle-color'];
    return {
      adapterType: 'circle',
      patch: {
        layer_type: vectorLayerType(layer),
        paint: circlePaint,
        style_config: styleWithBuilder(layer, {
          ...builderRecord(layer),
          clusterRadius: layer.style_config?.builder?.clusterRadius ?? 48,
          clusterMaxZoom: layer.style_config?.builder?.clusterMaxZoom ?? 14,
          clusterColor: layer.style_config?.builder?.clusterColor ?? clusterColor,
          clusterTextColor: layer.style_config?.builder?.clusterTextColor ?? '#ffffff',
        }, { render_mode: 'cluster' }),
      },
    };
  }

  if (renderAs === 'line') {
    return {
      adapterType: 'line',
      patch: {
        layer_type: vectorLayerType(layer),
        style_config: styleWithoutRenderModeAndBuilderKeys(layer, ['arrowColor', 'arrowSize', 'arrowSpacing']),
      },
    };
  }

  if (renderAs === 'arrow') {
    const lineColor = typeof layer.paint?.['line-color'] === 'string'
      ? layer.paint['line-color']
      : '#3b82f6';
    return {
      adapterType: 'line',
      patch: {
        layer_type: vectorLayerType(layer),
        style_config: styleWithBuilder(layer, {
          ...builderRecord(layer),
          arrowColor: layer.style_config?.builder?.arrowColor ?? lineColor,
          arrowSize: layer.style_config?.builder?.arrowSize ?? 14,
          arrowSpacing: layer.style_config?.builder?.arrowSpacing ?? 80,
        }, { render_mode: 'arrow' }),
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
