import type { MapLayerResponse, MapLayerType, StyleConfig } from '@/types/api';
import { canUseClusterSource } from './cluster-source';
import { classifyGeometry } from './layer-adapters/shared';
import { MAP_COLORS } from '@/lib/map-colors';
import i18n from '@/i18n/i18n';
// Per-render-mode default paint and the arrow/extrusion constants come from the
// single builder-defaults source of truth.
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

type RenderAsSource =
  | 'vector-point'
  | 'vector-line'
  | 'vector-polygon'
  | 'raster'
  | 'raster-dem'
  | 'unsupported';

interface RenderAsOption {
  id: RenderAsId;
  label: string;
  source: RenderAsSource;
}

// RendererCapability trimmed to the fields runtime code reads. Every renderer is
// backend:'maplibre', so there is no multi-backend abstraction to model.
interface RendererCapability {
  id: RenderAsId;
  label: string;
  source: Exclude<RenderAsSource, 'unsupported'>;
  /** Cluster needs a GeoJSON/cluster source; the only capability-level gate read at runtime. */
  requiresClusterSource?: boolean;
}

interface RendererCapabilityDefinition extends Omit<RendererCapability, 'label'> {
  labelKey: string;
}

type BuilderTranslator = (key: string, options?: Record<string, unknown>) => string;

const defaultBuilderTranslator: BuilderTranslator = (key, options) =>
  i18n.t(key, { ns: 'builder', ...options }) as string;

export type RenderAsAdapterType = 'circle' | 'symbol' | 'heatmap' | 'line' | 'fill' | 'raster' | 'hillshade';

interface RenderAsPatch {
  layer_type?: MapLayerType | null;
  style_config?: StyleConfig | null;
  paint?: Record<string, unknown> | null;
  layout?: Record<string, unknown> | null;
}

interface RenderAsMutation {
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

export const RENDERER_CAPABILITIES: readonly RendererCapabilityDefinition[] = [
  { id: 'point', labelKey: 'renderAs.point', source: 'vector-point' },
  { id: 'symbol', labelKey: 'renderAs.symbol', source: 'vector-point' },
  { id: 'heatmap', labelKey: 'renderAs.heatmap', source: 'vector-point' },
  { id: 'cluster', labelKey: 'renderAs.cluster', source: 'vector-point', requiresClusterSource: true },
  { id: 'line', labelKey: 'renderAs.line', source: 'vector-line' },
  { id: 'arrow', labelKey: 'renderAs.arrow', source: 'vector-line' },
  { id: 'fill', labelKey: 'renderAs.fill', source: 'vector-polygon' },
  { id: 'stroke', labelKey: 'renderAs.stroke', source: 'vector-polygon' },
  { id: 'fill-stroke', labelKey: 'renderAs.fillStroke', source: 'vector-polygon' },
  { id: 'extrusion-3d', labelKey: 'renderAs.extrusion3d', source: 'vector-polygon' },
  { id: 'image', labelKey: 'renderAs.image', source: 'raster' },
  { id: 'hillshade', labelKey: 'renderAs.hillshade', source: 'raster-dem' },
];

function isRasterLayer(layer: RenderAsLayer) {
  return (
    layer.layer_type === 'raster_geolens'
    || layer.dataset_record_type === 'raster_dataset'
    || layer.dataset_record_type === 'vrt_dataset'
  );
}

// Derive from the single classifyGeometry scanner.
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
 *  heightColumn baseline for hasCustomizedRenderAsStyle. */
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

export function getRenderAsOptions(
  layer: RenderAsLayer,
  t: BuilderTranslator = defaultBuilderTranslator,
): RenderAsOption[] {
  return getRendererCapabilities(layer, t).map((capabilityEntry) => ({
    id: capabilityEntry.id,
    label: capabilityEntry.label,
    source: capabilityEntry.source,
  }));
}

export function getRendererCapabilities(
  layer: RenderAsLayer,
  t: BuilderTranslator = defaultBuilderTranslator,
): RendererCapability[] {
  const source = getRenderAsSource(layer);
  if (source === 'unsupported') return [];
  return RENDERER_CAPABILITIES
    .filter((entry) => {
      if (entry.source !== source) return false;
      if (entry.requiresClusterSource) return canUseClusterSource(layer);
      return true;
    })
    .map(({ labelKey, ...entry }) => ({ ...entry, label: t(labelKey) }));
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

/**
 * Whether the layer's current render mode carries mode-specific style settings
 * that diverge from that mode's fresh/default state. Decides whether the
 * render-as confirm dialog is warranted: a layer never customized beyond the
 * mode's defaults has nothing to lose, so `handleRenderAsClick` skips the
 * confirm when this is `false`.
 *
 * Only fields with a fixed, mode-independent default (radius/zoom/size numbers,
 * ramp/icon names) are checked. Color fields are excluded: they derive from the
 * layer's base paint at mode entry (e.g. arrow color inherits the line color),
 * so there is no fixed default to diverge from and they would always read as
 * customized.
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
        // The Symbol editor also persists iconOffset and a per-category icon
        // mapping, all dropped when leaving symbol mode.
        || (symbol.iconOffset !== undefined
          && (symbol.iconOffset[0] !== 0 || symbol.iconOffset[1] !== 0))
        || (typeof symbol.categoryColumn === 'string' && symbol.categoryColumn !== '')
        || (Array.isArray(symbol.categories) && symbol.categories.length > 0)
      );
    }

    case 'heatmap': {
      if (builder.heatmapRamp !== undefined && builder.heatmapRamp !== 'YlOrRd') return true;
      return (Object.keys(DEFAULT_HEATMAP_PAINT) as (keyof typeof DEFAULT_HEATMAP_PAINT)[]).some(
        (key) => key in paint && paint[key] !== DEFAULT_HEATMAP_PAINT[key],
      );
    }

    case 'cluster': {
      // A clusterColor equal to the point colour (older maps seeded it on mode
      // entry) is not customization; a diverging one is, as for extrusion
      // heightColumn. Any non-empty ramp is user-authored state.
      const seededClusterColor = typeof paint['circle-color'] === 'string'
        ? paint['circle-color']
        : DEFAULT_CIRCLE_PAINT['circle-color'];
      return (
        (typeof builder.clusterRadius === 'number' && builder.clusterRadius !== 48)
        || (typeof builder.clusterMaxZoom === 'number' && builder.clusterMaxZoom !== 14)
        || (typeof builder.clusterTextColor === 'string' && builder.clusterTextColor !== MAP_COLORS.cluster.text)
        || (typeof builder.clusterTextSize === 'number' && builder.clusterTextSize !== 12)
        || (typeof builder.clusterColor === 'string' && builder.clusterColor !== seededClusterColor)
        || (Array.isArray(builder.clusterColorRamp) && builder.clusterColorRamp.length > 0)
        // Counts hidden is user-authored destructible state.
        || builder.clusterShowCounts === false
      );
    }

    case 'arrow': {
      // An arrowColor equal to the line colour (older maps seeded it on mode
      // entry) is not customization; a diverging one is destructible state.
      // Every editor-persisted builder field (arrow*, cluster*, heightColumn,
      // symbol.*) is covered by this switch.
      const seededArrowColor = typeof paint['line-color'] === 'string'
        ? paint['line-color']
        : MAP_COLORS.default.fill;
      return (
        (typeof builder.arrowSize === 'number' && builder.arrowSize !== DEFAULT_ARROW_SIZE)
        || (typeof builder.arrowSpacing === 'number' && builder.arrowSpacing !== DEFAULT_ARROW_SPACING)
        || (typeof builder.arrowColor === 'string' && builder.arrowColor !== seededArrowColor)
      );
    }

    case 'extrusion-3d': {
      // A user-chosen heightColumn is destructible too (leaving extrusion deletes
      // it). Entry auto-picks a column, so presence alone isn't customization;
      // diverging from the auto-pick default is.
      const heightColumn = builderHeightColumn(layer);
      return (
        (typeof builder.heightScale === 'number' && builder.heightScale !== 1)
        || (typeof builder.extrusionMinZoom === 'number' && builder.extrusionMinZoom !== DEFAULT_EXTRUSION_MIN_ZOOM)
        || (typeof builder.extrusionOpacity === 'number' && builder.extrusionOpacity !== DEFAULT_EXTRUSION_OPACITY_CAP)
        || (heightColumn !== null && heightColumn !== defaultHeightColumn(layer))
      );
    }

    // 'point' / 'line' / 'fill' / 'stroke' / 'fill-stroke' / 'image' /
    // 'hillshade' have no destructible mode-specific settings: buildRenderAsPatch
    // preserves or stashes (savedCirclePaint) their base paint across a switch.
    default:
      return false;
  }
}

export function buildRenderAsPatch(
  layer: RenderAsLayer,
  renderAs: RenderAsId,
  options: { heightColumn?: string } = {},
): RenderAsMutation | null {
  if (!getRenderAsOptions(layer).some((option) => option.id === renderAs)) return null;

  if (renderAs === 'point') {
    const current = getCurrentRenderAs(layer);
    const style = styleWithoutRenderMode(layer, {
      heatmapPaint: current === 'heatmap' ? { ...(layer.paint ?? {}) } : layer.style_config?.heatmapPaint,
      savedCirclePaint: undefined,
      symbol: undefined,
    });
    const savedCirclePaint = layer.style_config?.savedCirclePaint;
    // Cluster draws its unclustered points with the layer's own circle paint.
    const circlePaint = current === 'cluster'
      ? layer.paint
      : savedCirclePaint && Object.keys(savedCirclePaint).length > 0 ? savedCirclePaint : null;
    return {
      adapterType: 'circle',
      patch: {
        layer_type: vectorLayerType(layer),
        paint: { ...(circlePaint ?? DEFAULT_CIRCLE_PAINT) },
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
    // Heatmap paint holds heatmap-* keys; the circle paint is stashed.
    const circlePaint = getCurrentRenderAs(layer) === 'heatmap'
      ? { ...(layer.style_config?.savedCirclePaint ?? DEFAULT_CIRCLE_PAINT) }
      : { ...(layer.paint ?? DEFAULT_CIRCLE_PAINT) };
    return {
      adapterType: 'circle',
      patch: {
        layer_type: vectorLayerType(layer),
        paint: circlePaint,
        style_config: styleWithBuilder(layer, {
          ...builderRecord(layer),
          clusterRadius: layer.style_config?.builder?.clusterRadius ?? 48,
          clusterMaxZoom: layer.style_config?.builder?.clusterMaxZoom ?? 14,
          // Unset until chosen, so cluster bubbles follow later circle-color edits.
          clusterTextColor: layer.style_config?.builder?.clusterTextColor ?? MAP_COLORS.cluster.text,
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
    return {
      adapterType: 'line',
      patch: {
        layer_type: vectorLayerType(layer),
        // arrowColor stays unset until chosen, so arrows follow later line-color edits.
        style_config: styleWithBuilder(layer, {
          ...builderRecord(layer),
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
      builder.heightColumn = options.heightColumn ?? numericHeightColumn(layer);
      builder.heightScale = typeof priorHeightScale === 'number' ? priorHeightScale : 1;
      builder.extrusionMinZoom = typeof priorExtrusionMinZoom === 'number' ? priorExtrusionMinZoom : DEFAULT_EXTRUSION_MIN_ZOOM;
      // The shared extrusion-opacity cap, not a hardcoded value.
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
