import { resolveCirclePaint, resolvePointStroke } from '@/components/builder/layer-adapters/circle-adapter';
import { resolveFillPaint, resolvePolygonStroke } from '@/components/builder/layer-adapters/fill-adapter';
import { resolveHeatmapColor } from '@/components/builder/layer-adapters/heatmap-adapter';
import { resolveLinePaint } from '@/components/builder/layer-adapters/line-adapter';
import { resolveMixedFillPaint, resolveMixedOutline } from '@/components/builder/layer-adapters/mixed-adapter';
import {
  getBuilderStyleConfig,
  getFeatureOpacity,
  resolveAdapterType,
} from '@/components/builder/layer-adapters/shared';
import type { LayerAdapter } from '@/components/builder/layer-adapters/types';
import { isDemTerrainVisualSuppressed } from '@/components/builder/map-sync';
import { colorClassificationIsOrphaned, getColorProperty, getSizeProperty } from '@/lib/color-ramps';
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

/** A heatmap's colours from low to high density, where each sits on the ramp, and how they blend. */
export interface LegendRamp {
  colors: string[];
  /**
   * Where each colour sits, 0 to 1 across the densities the ramp draws: its stop
   * for an interpolate, and where its band starts for a step.
   */
  stops: number[];
  mode: 'interpolate' | 'step';
  /** The named ramp the colours come from; null for a stored expression. */
  name: string | null;
  reversed: boolean;
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
  /** A heatmap's colour ramp; null for other layers. */
  ramp: LegendRamp | null;
  /** The column a heatmap weights its points by; null when unweighted or not a heatmap. */
  weightColumn: string | null;
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

const COERCIONS = new Set(['to-number', 'number', 'to-string', 'string']);

function isLiteral(value: unknown): boolean {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value);
}

/**
 * The column an expression reads unchanged: `['get', column]`, or a type coercion
 * or `coalesce` of it with literal fallbacks. Null for anything that transforms it.
 */
function plainColumn(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  const [op, first, ...rest] = value;
  if (op === 'get') return value.length === 2 && typeof first === 'string' ? first : null;
  if (COERCIONS.has(op) || op === 'coalesce') return rest.every(isLiteral) ? plainColumn(first) : null;
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
  return guarded !== null && plainColumn(rampInput(ramp)) === guarded ? ramp : value;
}

/**
 * The colours, breaks and column of a step or linear interpolate colour ramp,
 * null guard or not. The column is the one the ramp's input reads unchanged, so a
 * zoom ramp or a transformed input has none.
 */
function colorSteps(value: unknown): { colors: string[]; breaks: number[]; column: string | null; isStep: boolean } | null {
  const ramp = unwrapNullGuard(value);
  const parsed = parseStepOrInterpolate(ramp);
  if (!parsed || !parsed.values.every((v) => typeof v === 'string')) return null;
  return {
    colors: parsed.values as string[],
    breaks: parsed.breaks,
    column: plainColumn(rampInput(ramp)),
    isStep: Array.isArray(ramp) && ramp[0] === 'step',
  };
}

function sameValues<T>(a: T[], b: T[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

/**
 * Whether a size expression steps on `column` at `breaks`, null guard or not, or is
 * a zoom ramp whose every stop is such a step: then its sizes change where the classes do.
 */
function sizeStepsMatch(value: unknown, column: string, breaks: number[]): boolean {
  const expression = unwrapNullGuard(value);
  if (!Array.isArray(expression)) return false;
  if (expression[0] === 'step' && plainColumn(expression[1]) === column) {
    return sameValues(expression.filter((_, i) => i >= 3 && i % 2 === 1), breaks);
  }
  const zoomStops = expression[0] === 'interpolate' && isExpression(expression[2], 'zoom')
    ? expression.filter((_, i) => i >= 4 && i % 2 === 0)
    : expression[0] === 'step' && isExpression(expression[1], 'zoom')
      ? expression.filter((_, i) => i >= 2 && i % 2 === 0)
      : [];
  return zoomStops.length > 0 && zoomStops.every((stop) => sizeStepsMatch(stop, column, breaks));
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
    // Colour steps the legend can't list, on zoom or a transformed input, lend the sizes no colour.
    const listed = steps?.column ? { ...steps, column: steps.column } : null;
    const color = listed?.colors[0] ?? swatch?.fill ?? MAP_COLORS.fallback;
    const sizeTitle = config.sizeLabel ?? displayColumn(column);
    // A colour step on the size column at the size breaks, over sizes that step there
    // too, gives each size class one colour, so the legend lists one classification.
    const sizeProperty = getSizeProperty(geometry, config.target);
    const colorsEachSize = listed !== null && listed.isStep && listed.column === column && sameValues(listed.breaks, breaks)
      && sizeProperty !== null && sizeStepsMatch(paint[sizeProperty], column, breaks);
    const sized: LegendClasses = {
      mode: 'graduated',
      target: config.target,
      title: sizeTitle,
      items: config.sizes.map((size, i) => ({ color: (colorsEachSize ? listed.colors[i] : undefined) ?? color, size })),
      breaks,
    };
    if (!listed || colorsEachSize) return [sized];
    return [sized, {
      mode: 'graduated',
      target: 'color',
      title: config.colorLabel ?? (listed.column === column ? sizeTitle : displayColumn(listed.column)),
      items: listed.colors.map((stepColor) => ({ color: stepColor })),
      breaks: listed.breaks,
    }];
  }
  const items = (config.colors ?? []).map((classColor) => ({ color: classColor }));
  if (!items.length) return null;
  // Stored classes that the paint's own ramp on the column contradicts are stale.
  const painted = colorSteps(paint[getColorProperty(geometry)]);
  const contradicted = painted?.column === column
    && (!sameValues(painted.colors, items.map((item) => item.color)) || (config.breaks !== undefined && !sameValues(painted.breaks, breaks)));
  if (contradicted) return null;
  return [{ mode: 'graduated', target: 'color', title: config.colorLabel ?? displayColumn(column), items, breaks }];
}

/** Whether a value is the argument-free expression `[name]`, such as `['linear']`. */
function isExpression(value: unknown, name: string): boolean {
  return Array.isArray(value) && value.length === 1 && value[0] === name;
}

/** Whether a CSS colour has zero alpha: `transparent`, an rgb(a) or hsl(a) alpha of 0, or a 4- or 8-digit hex ending in 0. */
function isTransparentColor(color: unknown): boolean {
  if (typeof color !== 'string') return false;
  const value = color.trim().toLowerCase();
  if (value === 'transparent') return true;
  const hex = /^#(?:[0-9a-f]{3}([0-9a-f])|[0-9a-f]{6}([0-9a-f]{2}))$/.exec(value);
  if (hex) return parseInt(hex[1] ?? hex[2], 16) === 0;
  const fn = /^(?:rgb|hsl)a?\((.*)\)$/.exec(value);
  if (!fn) return false;
  const parts = fn[1].split(/[\s,/]+/).filter(Boolean);
  return parts.length === 4 && parseFloat(parts[3]) === 0;
}

/** The colours, stops and mode a heatmap-color expression draws; null when they can't be read. */
function heatmapRamp(expression: unknown): Pick<LegendRamp, 'colors' | 'stops' | 'mode'> | null {
  if (typeof expression === 'string') return { colors: [expression], stops: [0], mode: 'interpolate' };
  if (!Array.isArray(expression)) return null;
  const isStep = expression[0] === 'step';
  const isLinear = expression[0] === 'interpolate' && isExpression(expression[1], 'linear');
  // The gradient can draw only hard steps and linear blends in RGB, over density.
  if (!(isStep || isLinear) || !isExpression(isStep ? expression[1] : expression[2], 'heatmap-density')) return null;
  // [density, colour]: a step's first band starts at zero density.
  const pairs: [unknown, unknown][] = isStep ? [[0, expression[2]]] : [];
  for (let i = 3; i + 1 < expression.length; i += 2) {
    // A transparent colour at zero density is the floor where no heat draws, as
    // in the built ramps; an opaque one there is part of the ramp.
    if (!isStep && expression[i] === 0 && isTransparentColor(expression[i + 1])) continue;
    pairs.push([expression[i], expression[i + 1]]);
  }
  if (!pairs.length || !pairs.every(([density, color]) => typeof density === 'number' && typeof color === 'string')) return null;
  const densities = pairs.map(([density]) => density as number);
  // An interpolate draws from its first stop to its last; a step's bands cover every density.
  const [low, high] = isStep ? [0, 1] : [densities[0], densities[densities.length - 1]];
  return {
    colors: pairs.map(([, color]) => color as string),
    // Rounded so float noise in the division doesn't leak into the stops.
    stops: densities.map((density) => (high > low ? Math.round(Math.min(1, Math.max(0, (density - low) / (high - low))) * 1e6) / 1e6 : 0)),
    mode: isStep ? 'step' : 'interpolate',
  };
}

/** A ramp as gradient stops from 0 to 1: interpolated colours at their stops, a step's colours as hard bands. */
export function rampGradient(ramp: Pick<LegendRamp, 'colors' | 'stops' | 'mode'>): { color: string; offset: number }[] {
  if (ramp.mode === 'step') {
    return ramp.colors.flatMap((color, i) => [
      { color, offset: ramp.stops[i] },
      { color, offset: ramp.stops[i + 1] ?? 1 },
    ]);
  }
  const stops = ramp.colors.map((color, i) => ({ color, offset: ramp.stops[i] }));
  // A gradient needs two stops, so a lone colour spans the ramp.
  return stops.length > 1 ? stops : [{ ...stops[0], offset: 0 }, { ...stops[0], offset: 1 }];
}

function rampFor(layer: LegendLayer, kind: LayerAdapter['type']): LegendFacts['ramp'] {
  if (kind !== 'heatmap') return null;
  const { expression, ramp } = resolveHeatmapColor(layer.paint ?? {}, getBuilderStyleConfig(layer));
  const drawn = heatmapRamp(expression);
  return drawn ? { ...drawn, name: ramp?.name ?? null, reversed: ramp?.reversed ?? false } : null;
}

// The adapter weights by the paint, so builder state naming a column is not enough.
function weightColumnFor(layer: LegendLayer, kind: LayerAdapter['type']): string | null {
  return kind === 'heatmap' ? plainColumn(layer.paint?.['heatmap-weight']) : null;
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
  return {
    name: legendEntryName(layer) ?? '',
    drawsAs: kind,
    swatch,
    classes: classesFor(layer, kind, swatch),
    ramp: rampFor(layer, kind),
    weightColumn: weightColumnFor(layer, kind),
  };
}
