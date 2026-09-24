import { resolveCirclePaint, resolvePointStroke } from '@/components/builder/layer-adapters/circle-adapter';
import { resolveFillPaint, resolvePolygonStroke } from '@/components/builder/layer-adapters/fill-adapter';
import { resolveLinePaint } from '@/components/builder/layer-adapters/line-adapter';
import { resolveMixedFillPaint, resolveMixedOutline } from '@/components/builder/layer-adapters/mixed-adapter';
import {
  getBuilderStyleConfig,
  getFeatureOpacity,
  resolveAdapterType,
} from '@/components/builder/layer-adapters/shared';
import type { LayerAdapter } from '@/components/builder/layer-adapters/types';
import { isDemTerrainVisualSuppressed } from '@/components/builder/map-sync';
import { colorClassificationIsOrphaned, getColorProperty } from '@/lib/color-ramps';
import { effectiveDemRenderMode } from '@/lib/dem-render-mode';
import { fillPatternFromPaint, fillPatternTint } from '@/lib/fill-pattern-preview';
import { inferGeometryType } from '@/lib/geo-utils';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { MAP_COLORS } from '@/lib/map-colors';
import { parseStepOrInterpolate } from '@/lib/normalize-style-config';
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

/** One classification the map draws, as the legend lists it. */
export interface LegendClasses {
  mode: 'categorical' | 'graduated';
  target: 'color' | 'radius' | 'width';
  /** The classified attribute, named for the legend. */
  title: string;
  /** One entry per class: its colour, its size on a size target, and a category's label. */
  items: { color: string; size?: number; label?: string }[];
  /** Graduated class breaks; empty for categories. */
  breaks: number[];
}

/** What a legend entry shows for one layer. */
export interface LegendFacts {
  name: string;
  drawsAs: LayerAdapter['type'];
  /** Null for heatmap, raster and hillshade layers. */
  swatch: LegendSwatch | null;
  /**
   * The classifications the map draws, or null for none. A size classification
   * comes first, followed by the colour classes its symbols are painted in.
   */
  classes: LegendClasses[] | null;
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

/** Where an expression's branches put their outputs: step and interpolate stops, match and case arms, coalesce arguments. */
function expressionOutputs(expr: unknown[]): unknown[] {
  switch (expr[0]) {
    case 'step':
      return expr.filter((_, i) => i >= 2 && i % 2 === 0);
    case 'interpolate':
    case 'interpolate-hcl':
    case 'interpolate-lab':
      return expr.filter((_, i) => i >= 4 && i % 2 === 0);
    case 'match':
      return expr.filter((_, i) => i >= 3 && (i % 2 === 1 || i === expr.length - 1));
    case 'case':
      return expr.filter((_, i) => i >= 2 && (i % 2 === 0 || i === expr.length - 1));
    case 'coalesce':
      return expr.slice(1);
    default:
      return [];
  }
}

/** The largest number an expression outputs, through nested expressions; null when it outputs none. */
function largestOutput(value: unknown): number | null {
  if (typeof value === 'number') return value;
  if (!Array.isArray(value)) return null;
  return expressionOutputs(value).reduce<number | null>((largest, output) => {
    const candidate = largestOutput(output);
    return candidate !== null && (largest === null || candidate > largest) ? candidate : largest;
  }, null);
}

// A zoom or data expression counts at the largest value it reaches: the swatch
// shows the layer as it looks once it fades in, and an unreadable one shows at 1.
function featureOpacity(paint: Record<string, unknown>, family: 'fill' | 'line' | 'circle'): number {
  const value = getFeatureOpacity(paint, family);
  return typeof value === 'number' ? value : largestOutput(value) ?? 1;
}

/** The paint with an expression on `key` replaced by the largest value it reaches, else 1. */
function atLargestOutput(paint: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = paint[key];
  return Array.isArray(value) ? { ...paint, [key]: largestOutput(value) ?? 1 } : paint;
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
        stroke: resolvePointStroke(atLargestOutput(paint, 'circle-stroke-width')),
        pattern: null,
      };
    default:
      return null;
  }
}

/** A column name as a legend title. */
function displayColumn(column: string): string {
  return column
    .replace(/^_+/, '')
    .replace(/_/g, ' ')
    .replace(/\bmhi\b/i, 'income')
    .replace(/\bkm\b/i, 'km');
}

/** The first column an expression reads with `get`. */
function expressionColumn(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  if (value[0] === 'get' && typeof value[1] === 'string') return value[1];
  for (const entry of value) {
    const column = expressionColumn(entry);
    if (column) return column;
  }
  return null;
}

/** The column a plain `['get', column]` reads; null for any other value. */
function getColumn(value: unknown): string | null {
  return Array.isArray(value) && value.length === 2 && value[0] === 'get' && typeof value[1] === 'string'
    ? value[1]
    : null;
}

/** The input a step or interpolate expression is classed on; undefined for any other value. */
function rampInput(value: unknown): unknown {
  if (!Array.isArray(value)) return undefined;
  if (value[0] === 'step') return value[1];
  if (value[0] === 'interpolate') return value[2];
  return undefined;
}

/**
 * The ramp inside the null guard the style builders wrap around their classes,
 * `['case', ['==', ['get', column], null], fallback, ramp]`, when the ramp is
 * classed on that same column; any other value as it is.
 */
function unwrapNullGuard(value: unknown): unknown {
  if (!Array.isArray(value) || value[0] !== 'case' || value.length !== 4) return value;
  const [, test, , ramp] = value;
  const isNullTest = Array.isArray(test) && test.length === 3 && test[0] === '==' && test[2] === null;
  const guarded = isNullTest ? getColumn(test[1]) : null;
  return guarded !== null && getColumn(rampInput(ramp)) === guarded ? ramp : value;
}

/**
 * The colours, breaks and column of a step or linear interpolate colour ramp,
 * null guard or not. The column comes from the ramp's input, so a zoom ramp has none.
 */
function colorSteps(value: unknown): { colors: string[]; breaks: number[]; column: string | null } | null {
  const ramp = unwrapNullGuard(value);
  const parsed = parseStepOrInterpolate(ramp);
  if (!parsed || !parsed.values.every((v) => typeof v === 'string')) return null;
  return { colors: parsed.values as string[], breaks: parsed.breaks, column: expressionColumn(rampInput(ramp)) };
}

// Symbol icons, heatmaps and rasters draw none of the vector colour or size classes.
const CLASSED_KINDS = new Set<LayerAdapter['type']>(['fill', 'line', 'circle', 'cluster', 'mixed']);

function classesFor(
  layer: LegendLayer,
  kind: LayerAdapter['type'],
  swatch: LegendSwatch | null,
): LegendClasses[] | null {
  const config = layer.style_config;
  const column = config?.column;
  if (!config || !column || !CLASSED_KINDS.has(kind)) return null;
  const paint = layer.paint ?? {};
  const geometry = inferGeometryType(paint, layer.dataset_geometry_type ?? layer.geometry_type);
  // A classification stays in style_config after the paint stops reading its column.
  if (colorClassificationIsOrphaned(config, paint, geometry)) return null;
  const breaks = config.breaks ?? [];
  if (config.mode === 'categorical') {
    const items = (config.categories ?? []).map((category) => ({
      color: category.color,
      label: category.label ?? String(category.value ?? 'null'),
    }));
    if (!items.length) return null;
    return [{ mode: 'categorical', target: 'color', title: config.colorLabel ?? displayColumn(column), items, breaks: [] }];
  }
  if (config.mode !== 'graduated') return null;
  if ((config.target === 'radius' || config.target === 'width') && config.sizes?.length) {
    const steps = colorSteps(paint[getColorProperty(geometry)]);
    const color = steps?.colors[0] ?? swatch?.fill ?? MAP_COLORS.fallback;
    const sized: LegendClasses = {
      mode: 'graduated',
      target: config.target,
      title: config.sizeLabel ?? displayColumn(column),
      items: config.sizes.map((size) => ({ color, size })),
      breaks,
    };
    if (!steps?.column) return [sized];
    return [sized, {
      mode: 'graduated',
      target: 'color',
      title: config.colorLabel ?? displayColumn(steps.column),
      items: steps.colors.map((stepColor) => ({ color: stepColor })),
      breaks: steps.breaks,
    }];
  }
  const items = (config.colors ?? []).map((classColor) => ({ color: classColor }));
  if (!items.length) return null;
  return [{ mode: 'graduated', target: 'color', title: config.colorLabel ?? displayColumn(column), items, breaks }];
}

/**
 * Legend facts for one saved layer, or null when the map draws nothing for it.
 * Folder rows copy their first child's fields but render nothing, and a DEM in
 * terrain mode shapes the terrain mesh instead of drawing a layer.
 */
export function legendFacts(layer: LegendLayer): LegendFacts | null {
  if (isFolderGroupLayer(layer) || isDemTerrainVisualSuppressed(layer)) return null;
  const kind = drawsAs(layer);
  const swatch = swatchFor(layer, kind);
  return { name: legendEntryName(layer) ?? '', drawsAs: kind, swatch, classes: classesFor(layer, kind, swatch) };
}
