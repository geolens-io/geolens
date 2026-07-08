import type { MapLayerResponse, MapLayerType, StyleConfig } from '@/types/api';
import { canUseClusterSource } from './cluster-source';
import { classifyGeometry } from './layer-adapters/shared';
import { MAP_COLORS } from '@/lib/map-colors';
// builder-audit #338 ADAPT-05/06 / DRY-04/06: pull the per-render-mode default paint and
// the arrow/extrusion magic constants from the single builder-defaults source of truth
// instead of re-declaring divergent copies here.
import {
  DEFAULT_ARROW_SIZE,
  DEFAULT_ARROW_SPACING,
  DEFAULT_CIRCLE_PAINT,
  DEFAULT_EXTRUSION_MIN_ZOOM,
  DEFAULT_EXTRUSION_OPACITY_CAP,
  DEFAULT_FILL_PAINT,
  DEFAULT_HEATMAP_PAINT,
  DEFAULT_HILLSHADE_PAINT,
} from './layer-adapters/builder-defaults';

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

// builder-audit #338 ADAPT-07: trimmed RendererCapability to the fields runtime code
// actually reads. The previous schema modeled backend/viewerSupport/styleJsonSupport/
// companionLayers/sourceRequirement/writableFields/enabled, none of which had a
// consumer outside this module and its tests (every row was backend:'maplibre',
// enabled:true). GUARD-05: 'deckgl-future' was already removed; with the single
// backend gone there is no multi-backend abstraction left to model.
export interface RendererCapability {
  id: RenderAsId;
  label: string;
  source: Exclude<RenderAsSource, 'unsupported'>;
  /** Cluster needs a GeoJSON/cluster source — the only capability-level gate read at runtime. */
  requiresClusterSource?: boolean;
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

export const RENDERER_CAPABILITIES: readonly RendererCapability[] = [
  { id: 'point', label: 'Point', source: 'vector-point' },
  { id: 'symbol', label: 'Symbols', source: 'vector-point' },
  { id: 'heatmap', label: 'Heatmap', source: 'vector-point' },
  { id: 'cluster', label: 'Cluster', source: 'vector-point', requiresClusterSource: true },
  { id: 'line', label: 'Line', source: 'vector-line' },
  { id: 'arrow', label: 'Arrow', source: 'vector-line' },
  { id: 'fill', label: 'Fill', source: 'vector-polygon' },
  { id: 'stroke', label: 'Stroke', source: 'vector-polygon' },
  { id: 'fill-stroke', label: 'Fill + Stroke', source: 'vector-polygon' },
  { id: 'extrusion-3d', label: '3D extrusion', source: 'vector-polygon' },
  { id: 'image', label: 'Image', source: 'raster' },
  { id: 'hillshade', label: 'Hillshade', source: 'raster-dem' },
];

function isRasterLayer(layer: RenderAsLayer) {
  return (
    layer.layer_type === 'raster_geolens'
    || layer.dataset_record_type === 'raster_dataset'
    || layer.dataset_record_type === 'vrt_dataset'
  );
}

// builder-audit #338 ADAPT-02/DRY-05: derive from the single classifyGeometry scanner.
function geometryFamily(geometryType: string | null): 'point' | 'line' | 'polygon' | null {
  const family = classifyGeometry(geometryType);
  return family === 'other' ? null : family;
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
  return defaultHeightColumn(layer);
}

/** The column auto-pick would choose on extrusion entry — the "uncustomized"
 *  heightColumn baseline for hasCustomizedRenderAsStyle (fix #430 codex). */
function defaultHeightColumn(layer: RenderAsLayer): string {
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
    if (entry.source !== source) return false;
    if (entry.requiresClusterSource) return canUseClusterSource(layer);
    return true;
  });
}

export function getRendererCapability(id: RenderAsId, layer?: RenderAsLayer): RendererCapability | null {
  const entries = layer ? getRendererCapabilities(layer) : RENDERER_CAPABILITIES;
  return entries.find((entry) => entry.id === id) ?? null;
}

export function getCurrentRenderAs(layer: RenderAsLayer): RenderAsId | null {
  const source = getRenderAsSource(layer);
  const renderMode = layer.style_config?.render_mode;

  if (source === 'raster-dem') {
    return 'hillshade';
  }

  if (source === 'raster') {
    return 'image';
  }

  if (source === 'vector-point') {
    if (renderMode === 'cluster' && canUseClusterSource(layer)) return 'cluster';
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
  return RENDERER_CAPABILITIES.some((entry) => entry.id === value);
}

/**
 * fix(V-09): whether the layer's CURRENT render mode carries mode-specific
 * style settings that diverge from that mode's fresh/default state. Used to
 * decide whether the render-as confirm dialog is warranted — a layer that has
 * never been customized beyond the mode's defaults has nothing to lose by
 * switching, so `handleRenderAsClick` skips the confirm when this is `false`.
 *
 * Only checks fields with a fixed, mode-independent default (radius/zoom/size
 * numbers, ramp/icon names). Color fields are intentionally excluded — they
 * are derived from the layer's base paint at mode-entry time (e.g. arrow
 * color inherits the line color), so there is no fixed "default" to diverge
 * from and comparing them would always read as customized.
 */
export function hasCustomizedRenderAsStyle(layer: RenderAsLayer): boolean {
  const mode = getCurrentRenderAs(layer);
  const builder = layer.style_config?.builder ?? {};
  const paint = (layer.paint ?? {}) as Record<string, unknown>;

  switch (mode) {
    case 'symbol': {
      const symbol = layer.style_config?.symbol;
      if (!symbol) return false;
      return (
        (symbol.iconImage !== undefined && symbol.iconImage !== 'marker')
        || (symbol.iconSize !== undefined && symbol.iconSize !== 1)
        || (symbol.iconRotation !== undefined && symbol.iconRotation !== 0)
        || (symbol.iconAnchor !== undefined && symbol.iconAnchor !== 'center')
      );
    }

    case 'heatmap': {
      if (builder.heatmapRamp !== undefined && builder.heatmapRamp !== 'YlOrRd') return true;
      return (Object.keys(DEFAULT_HEATMAP_PAINT) as (keyof typeof DEFAULT_HEATMAP_PAINT)[]).some(
        (key) => key in paint && paint[key] !== DEFAULT_HEATMAP_PAINT[key],
      );
    }

    case 'cluster': {
      return (
        (typeof builder.clusterRadius === 'number' && builder.clusterRadius !== 48)
        || (typeof builder.clusterMaxZoom === 'number' && builder.clusterMaxZoom !== 14)
        || (typeof builder.clusterTextColor === 'string' && builder.clusterTextColor !== '#ffffff')
        || (typeof builder.clusterTextSize === 'number' && builder.clusterTextSize !== 12)
      );
    }

    case 'arrow': {
      return (
        (typeof builder.arrowSize === 'number' && builder.arrowSize !== DEFAULT_ARROW_SIZE)
        || (typeof builder.arrowSpacing === 'number' && builder.arrowSpacing !== DEFAULT_ARROW_SPACING)
      );
    }

    case 'extrusion-3d': {
      // fix(#430 codex): a user-chosen heightColumn is destructible state too —
      // leaving extrusion deletes it. Entry auto-picks a column, so presence
      // alone isn't customization; diverging from the auto-pick default is.
      const heightColumn = builderHeightColumn(layer);
      return (
        (typeof builder.heightScale === 'number' && builder.heightScale !== 1)
        || (typeof builder.extrusionMinZoom === 'number' && builder.extrusionMinZoom !== DEFAULT_EXTRUSION_MIN_ZOOM)
        || (typeof builder.extrusionOpacity === 'number' && builder.extrusionOpacity !== DEFAULT_EXTRUSION_OPACITY_CAP)
        || (heightColumn !== null && heightColumn !== defaultHeightColumn(layer))
      );
    }

    // 'point' / 'line' / 'fill' / 'stroke' / 'fill-stroke' / 'image' / 'hillshade':
    // these modes have no destructible mode-specific settings of their own —
    // buildRenderAsPatch preserves or stashes (savedCirclePaint) their base
    // paint across a mode switch, so there is nothing mode-specific to lose.
    default:
      return false;
  }
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
          clusterTextSize: layer.style_config?.builder?.clusterTextSize ?? 12,
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
      : MAP_COLORS.default.fill;
    return {
      adapterType: 'line',
      patch: {
        layer_type: vectorLayerType(layer),
        style_config: styleWithBuilder(layer, {
          ...builderRecord(layer),
          arrowColor: layer.style_config?.builder?.arrowColor ?? lineColor,
          arrowSize: layer.style_config?.builder?.arrowSize ?? DEFAULT_ARROW_SIZE,
          arrowSpacing: layer.style_config?.builder?.arrowSpacing ?? DEFAULT_ARROW_SPACING,
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
      builder.extrusionMinZoom = typeof priorExtrusionMinZoom === 'number' ? priorExtrusionMinZoom : DEFAULT_EXTRUSION_MIN_ZOOM;
      // builder-audit #338 (verifier nit): the prior `Math.min(0.85, 1)` was a no-op that
      // always evaluated to 0.85; use the shared extrusion-opacity cap directly.
      builder.extrusionOpacity = typeof priorExtrusionOpacity === 'number' ? priorExtrusionOpacity : DEFAULT_EXTRUSION_OPACITY_CAP;
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
