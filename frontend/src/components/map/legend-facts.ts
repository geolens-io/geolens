import { resolveCirclePaint, resolvePointStroke } from '@/components/builder/layer-adapters/circle-adapter';
import { resolveFillPaint, resolvePolygonStroke } from '@/components/builder/layer-adapters/fill-adapter';
import { resolveLinePaint } from '@/components/builder/layer-adapters/line-adapter';
import { resolveMixedFillPaint, resolveMixedOutline } from '@/components/builder/layer-adapters/mixed-adapter';
import {
  getBuilderStyleConfig,
  getFeatureOpacity,
  resolveAdapterType,
  simplifyPaint,
} from '@/components/builder/layer-adapters/shared';
import type { LayerAdapter } from '@/components/builder/layer-adapters/types';
import { isDemTerrainVisualSuppressed } from '@/components/builder/map-sync';
import { effectiveDemRenderMode } from '@/lib/dem-render-mode';
import { fillPatternFromPaint, fillPatternTint } from '@/lib/fill-pattern-preview';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import type { StyleConfig } from '@/types/api';

/** The saved-layer fields legend facts read. MapLayerResponse and SharedLayerResponse both satisfy it. */
export interface LegendLayer {
  display_name?: string | null;
  dataset_name?: string | null;
  layer_type?: string | null;
  is_dem?: boolean | null;
  /** The builder shape's geometry. */
  dataset_geometry_type?: string | null;
  /** The viewer shape's geometry. */
  geometry_type?: string | null;
  paint?: Record<string, unknown> | null;
  opacity?: number | null;
  style_config?: StyleConfig | null;
}

/** One swatch for a layer, drawn the way the map draws its features. */
export interface LegendSwatch {
  /** The constant colour the layer draws, or null when an expression or a pattern sets it. */
  fill: string | null;
  /** The fill, line or circle opacity from paint. */
  fillOpacity: number;
  /** The layer's own opacity, over the whole swatch. */
  opacity: number;
  stroke: { color: string; width: number } | null;
  pattern: { id: string; tint: string | null } | null;
}

/** What a legend entry shows for one layer. */
export interface LegendFacts {
  name: string;
  drawsAs: LayerAdapter['type'];
  /** Null for heatmap, raster and hillshade layers. */
  swatch: LegendSwatch | null;
}

function nonBlank(value: unknown): string | null {
  const trimmed = typeof value === 'string' ? value.trim() : '';
  return trimmed || null;
}

/**
 * The first non-blank of the layer's `legendLabel`, `display_name` and
 * `dataset_name`, trimmed; null when all three are blank.
 */
export function legendEntryName(
  layer: Pick<LegendLayer, 'display_name' | 'dataset_name' | 'style_config'>,
): string | null {
  return nonBlank(layer.style_config?.legendLabel)
    ?? nonBlank(layer.display_name)
    ?? nonBlank(layer.dataset_name);
}

function drawsAs(layer: LegendLayer): LayerAdapter['type'] {
  if (layer.layer_type === 'raster_geolens') {
    return layer.is_dem === true && effectiveDemRenderMode(layer.style_config, true) === 'hillshade'
      ? 'hillshade'
      : 'raster';
  }
  const geometry = layer.dataset_geometry_type ?? layer.geometry_type ?? null;
  return resolveAdapterType(geometry, layer.style_config, layer.paint ?? undefined) as LayerAdapter['type'];
}

function stringOrNull(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

// Expressions count at the value the adapter adds them with.
function featureOpacity(paint: Record<string, unknown>, family: 'fill' | 'line' | 'circle'): number {
  const value = getFeatureOpacity(simplifyPaint(paint), family);
  return typeof value === 'number' ? value : 1;
}

function patternOf(
  paint: Record<string, unknown>,
  builder: NonNullable<StyleConfig['builder']>,
): LegendSwatch['pattern'] {
  const id = fillPatternFromPaint(paint);
  return id ? { id, tint: fillPatternTint(paint, builder) ?? null } : null;
}

function swatchFor(layer: LegendLayer, kind: LayerAdapter['type']): LegendSwatch | null {
  const paint = layer.paint ?? {};
  const opacity = layer.opacity ?? 1;
  const builder = getBuilderStyleConfig(layer);
  switch (kind) {
    case 'fill': {
      const stroke = resolvePolygonStroke(paint, builder);
      return {
        fill: stringOrNull(resolveFillPaint(paint)['fill-color']),
        fillOpacity: featureOpacity(paint, 'fill'),
        opacity,
        stroke: stroke.disabled || stroke.width <= 0 ? null : { color: stroke.color, width: stroke.width },
        pattern: patternOf(paint, builder),
      };
    }
    case 'mixed':
      return {
        fill: stringOrNull(resolveMixedFillPaint(paint)['fill-color']),
        fillOpacity: featureOpacity(paint, 'fill'),
        opacity,
        stroke: resolveMixedOutline(),
        pattern: patternOf(paint, builder),
      };
    case 'line':
      return {
        fill: stringOrNull(resolveLinePaint(paint)['line-color']),
        fillOpacity: featureOpacity(paint, 'line'),
        opacity,
        stroke: null,
        pattern: null,
      };
    // A cluster's unclustered points and a symbol layer's swatch follow the circle rules.
    case 'circle':
    case 'cluster':
    case 'symbol':
      return {
        fill: stringOrNull(resolveCirclePaint(paint)['circle-color']),
        fillOpacity: featureOpacity(paint, 'circle'),
        opacity,
        stroke: resolvePointStroke(paint),
        pattern: null,
      };
    default:
      return null;
  }
}

/**
 * Legend facts for one saved layer, or null when the map draws nothing for it.
 * Folder rows copy their first child's fields but render nothing, and a DEM in
 * terrain mode shapes the terrain mesh instead of drawing a layer.
 */
export function legendFacts(layer: LegendLayer): LegendFacts | null {
  if (isFolderGroupLayer(layer) || isDemTerrainVisualSuppressed(layer)) return null;
  const kind = drawsAs(layer);
  return { name: legendEntryName(layer) ?? '', drawsAs: kind, swatch: swatchFor(layer, kind) };
}
