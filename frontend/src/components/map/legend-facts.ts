import { getClusterSourceStrategy, isClusterRenderMode, type ClusterSourceStrategyKind } from '@/components/builder/cluster-source';
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
import { getColorProperty } from '@/lib/color-ramps';
import { effectiveDemRenderMode } from '@/lib/dem-render-mode';
import { fillPatternFromPaint, fillPatternTint } from '@/lib/fill-pattern-preview';
import { inferGeometryType } from '@/lib/geo-utils';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { MAP_COLORS } from '@/lib/map-colors';
import { expressionReadsColumn } from '@/lib/maplibre-expressions';
import { parseStepOrInterpolate } from '@/lib/normalize-style-config';
import type { StyleConfig } from '@/types/api';

/** The saved-layer fields legend facts read. MapLayerResponse and SharedLayerResponse both satisfy it. */
export interface LegendLayer {
  display_name?: string | null;
  dataset_name?: string | null;
  layer_type?: string | null;
  dataset_record_type?: string | null;
  is_dem?: boolean | null;
  /** The builder shape's geometry. */
  dataset_geometry_type?: string | null;
  /** The viewer shape's geometry. */
  geometry_type?: string | null;
  /** The builder shape's feature count. */
  dataset_feature_count?: number | null;
  /** The viewer shape's feature count. */
  feature_count?: number | null;
  paint?: Record<string, unknown> | null;
  /** The saved filter, which can keep every value from a `match`'s fallback colour. */
  filter?: unknown;
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
  /**
   * One entry per class: its colour, its size on a size target, and a category's
   * label. `other` marks the class of every value the other classes don't list.
   */
  items: { color: string; size?: number; label?: string; other?: boolean }[];
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
  /**
   * Where a cluster layer's clusters come from: the browser over bounded GeoJSON,
   * the tile server, or nowhere when it draws single points. Null for other layers.
   */
  cluster: { kind: ClusterSourceStrategyKind } | null;
}

/** What the map drew a layer as, when the caller knows. */
export interface DrawnLayer {
  drawsAs: LayerAdapter['type'];
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

/** The input a step, interpolate or match expression classes on; undefined for any other value. */
function rampInput(value: unknown): unknown {
  if (!Array.isArray(value)) return undefined;
  if (value[0] === 'step' || value[0] === 'match') return value[1];
  if (value[0] === 'interpolate') return value[2];
  return undefined;
}

/**
 * The classes inside the null guard the style builders wrap around them,
 * `['case', ['==', ['get', column], null], fallback, classes]`, when a step,
 * interpolate or match classes on that same column; any other value as it is.
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

/** A colour `match` the legend can list: each arm's values and colour, and the colour of every other value. */
interface MatchClasses {
  column: string;
  arms: { values: (string | number)[]; color: string }[];
  fallback: string;
}

/** The values one `match` arm lists, one label or an array of them; null for anything else. */
function armValues(label: unknown): (string | number)[] | null {
  const values: unknown[] = Array.isArray(label) ? label : [label];
  return values.length > 0 && values.every((value) => typeof value === 'string' || typeof value === 'number')
    ? (values as (string | number)[])
    : null;
}

/** A colour `match` on a column the legend can name, null guard or not; null for any other value. */
function matchClasses(value: unknown): MatchClasses | null {
  const match = unwrapNullGuard(value);
  if (!Array.isArray(match) || match[0] !== 'match' || match.length < 5 || match.length % 2 === 0) return null;
  const column = plainColumn(match[1]);
  const fallback = match[match.length - 1];
  if (column === null || typeof fallback !== 'string') return null;
  const arms: MatchClasses['arms'] = [];
  for (let i = 2; i < match.length - 1; i += 2) {
    const values = armValues(match[i]);
    const color = match[i + 1];
    if (values === null || typeof color !== 'string') return null;
    arms.push({ values, color });
  }
  return { column, arms, fallback };
}

/**
 * The values a layer filter lets through on `column`, from an `==` or a literal
 * `in` on it, alone or inside `all`; null when the filter names none.
 */
function filteredValues(filter: unknown, column: string): unknown[] | null {
  if (!Array.isArray(filter)) return null;
  const [op, input, operand] = filter;
  if (op === 'all') {
    const limits = filter.slice(1)
      .map((entry) => filteredValues(entry, column))
      .filter((limit): limit is unknown[] => limit !== null);
    return limits.length > 0 ? limits.reduce((kept, limit) => kept.filter((value) => limit.includes(value))) : null;
  }
  if (filter.length !== 3 || getColumn(input) !== column) return null;
  if (op === '==' && isLiteral(operand)) return [operand];
  if (op === 'in' && Array.isArray(operand) && operand[0] === 'literal' && Array.isArray(operand[1])) return operand[1];
  return null;
}

/**
 * Categories from a colour `match`: each arm, then its fallback when a value the
 * filter lets through reaches it. Stored categories on its column lend their
 * labels, and one that no arm lists, in the fallback's colour, names the fallback.
 */
function categoricalClasses(match: MatchClasses, config: StyleConfig, filter: unknown, title: string): LegendClasses {
  const stored = config.column === match.column && Array.isArray(config.categories) ? config.categories : [];
  // A paint that coerces its input matches a stored value of another type.
  const isListed = (value: unknown) => match.arms.some((arm) => arm.values.some((armValue) => String(armValue) === String(value)));
  const items: LegendClasses['items'] = match.arms.map(({ values, color }) => ({
    color,
    label: values.map((value) => stored.find((category) => String(category.value) === String(value))?.label ?? String(value)).join(', '),
  }));
  const allowed = filteredValues(filter, match.column);
  const reachesFallback = allowed === null || allowed.some((value) => !match.arms.some((arm) => arm.values.some((armValue) => armValue === value)));
  if (reachesFallback && !isTransparentColor(match.fallback)) {
    const named = stored.filter((category) => !isListed(category.value)
      && String(category.color).toLowerCase() === match.fallback.toLowerCase());
    items.push(named.length === 1
      ? { color: match.fallback, label: named[0].label ?? String(named[0].value) }
      : { color: match.fallback, other: true });
  }
  return { mode: 'categorical', target: 'color', title, items, breaks: [] };
}

/** The sizes, breaks and column of a size `step` on a column the legend can name, null guard or not. */
function sizeSteps(value: unknown): { sizes: number[]; breaks: number[]; column: string } | null {
  const step = unwrapNullGuard(value);
  if (!Array.isArray(step) || step[0] !== 'step') return null;
  const column = plainColumn(step[1]);
  const parsed = parseStepOrInterpolate(step);
  if (column === null || !parsed || !parsed.values.every((size) => typeof size === 'number')) return null;
  return { sizes: parsed.values as number[], breaks: parsed.breaks, column };
}

/** The size property, and its class target, of each kind that can size features by data. */
const SIZE_PAINT: Partial<Record<LayerAdapter['type'], { property: string; target: 'radius' | 'width' }>> = {
  circle: { property: 'circle-radius', target: 'radius' },
  cluster: { property: 'circle-radius', target: 'radius' },
  line: { property: 'line-width', target: 'width' },
};

interface SizeClasses {
  target: 'radius' | 'width';
  column: string;
  sizes: number[];
  breaks: number[];
  /** The size paint the classes come from, or stand in for. */
  expression: unknown;
  /** False for stored classes the paint reads in a way the legend can't list. */
  painted: boolean;
}

/** Size classes from a size step, else the stored ones while the paint reads their column in a way the legend can't list. */
function sizeClassesFor(kind: LayerAdapter['type'], paint: Record<string, unknown>, config: StyleConfig): SizeClasses | null {
  const size = SIZE_PAINT[kind];
  if (!size) return null;
  const expression = paint[size.property];
  const steps = sizeSteps(expression);
  if (steps) return { target: size.target, ...steps, expression, painted: true };
  // Sizes that also scale with zoom have no one size per class, so the stored
  // classes stand in, unchecked, while the paint reads their column.
  const { column, sizes } = config;
  if (config.target !== size.target || !column || !sizes?.length || !expressionReadsColumn(expression, column)) return null;
  return { target: size.target, column, sizes, breaks: config.breaks ?? [], expression, painted: false };
}

/** The colour a layer's features draw with; for a mixed layer, the one its fills, lines and points share, if any. */
function drawnColor(paint: Record<string, unknown>, kind: LayerAdapter['type'], geometry: string | null): unknown {
  if (kind !== 'mixed') return paint[getColorProperty(geometry)];
  const [fill, ...others] = [
    resolveMixedFillPaint(paint)['fill-color'],
    resolveLinePaint(paint)['line-color'],
    resolveCirclePaint(paint)['circle-color'],
  ];
  return others.every((color) => JSON.stringify(color) === JSON.stringify(fill)) ? fill : undefined;
}

/** A colour classification's title: the stored colour label for it, else the stored column's size label, else the column. */
function colorTitle(config: StyleConfig, column: string): string {
  const storedColumn = config.column === column;
  // A size classification's colour label names its colours whichever column they read.
  if (config.colorLabel && (storedColumn || config.target === 'radius' || config.target === 'width')) return config.colorLabel;
  return (storedColumn ? config.sizeLabel : undefined) ?? displayColumn(column);
}

// Symbol icons, heatmaps and rasters draw none of the vector colour or size classes.
const CLASSED_KINDS = new Set<LayerAdapter['type']>(['fill', 'line', 'circle', 'cluster', 'mixed']);

/**
 * The classes the paint draws, or null when it draws none the legend can read.
 * Stored state lends labels and titles, and stands in for sizes that scale with zoom.
 */
function classesFor(
  layer: LegendLayer,
  kind: LayerAdapter['type'],
  swatch: LegendSwatch | null,
): LegendClasses[] | null {
  if (!CLASSED_KINDS.has(kind)) return null;
  const config = layer.style_config ?? {};
  const paint = layer.paint ?? {};
  const color = drawnColor(paint, kind, inferGeometryType(paint, layer.dataset_geometry_type ?? layer.geometry_type));
  const match = matchClasses(color);
  const steps = match ? null : colorSteps(color);
  // Colour steps on zoom or a transformed input have no column, and list nothing.
  const listed = steps?.column ? { ...steps, column: steps.column } : null;
  const colors: LegendClasses | null = match
    ? categoricalClasses(match, config, layer.filter, colorTitle(config, match.column))
    : listed && {
      mode: 'graduated',
      target: 'color',
      title: colorTitle(config, listed.column),
      items: listed.colors.map((stepColor) => ({ color: stepColor })),
      breaks: listed.breaks,
    };
  const sized = sizeClassesFor(kind, paint, config);
  if (!sized) return colors && [colors];
  // A colour step on the size column at the size breaks, over sizes that step there
  // too, gives each size class one colour, so the legend lists one classification.
  const colorsEachSize = listed !== null && listed.isStep && listed.column === sized.column
    && sameValues(listed.breaks, sized.breaks)
    && (sized.painted || sizeStepsMatch(sized.expression, sized.column, sized.breaks));
  // A ramp's first colour stands in for the sizes; one category's colour would claim them all.
  const sizeColor = listed?.colors[0] ?? swatch?.fill ?? MAP_COLORS.fallback;
  const sizes: LegendClasses = {
    mode: 'graduated',
    target: sized.target,
    title: (sized.column === config.column ? config.sizeLabel : undefined) ?? displayColumn(sized.column),
    items: sized.sizes.map((size, i) => ({ color: (colorsEachSize ? listed.colors[i] : undefined) ?? sizeColor, size })),
    breaks: sized.breaks,
  };
  return colors && !colorsEachSize ? [sizes, colors] : [sizes];
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

function clusterFor(layer: LegendLayer, kind: LayerAdapter['type']): LegendFacts['cluster'] {
  if (!isClusterRenderMode(layer)) return null;
  // A cluster layer the map drew as anything else is drawing its single points.
  return { kind: kind === 'cluster' ? getClusterSourceStrategy(layer).kind : 'fallback' };
}

/**
 * Legend facts for one saved layer, or null when the map draws nothing for it.
 * Folder rows copy their first child's fields but render nothing, and a DEM in
 * terrain mode shapes the terrain mesh instead of drawing a layer. `drawn` is
 * what the map drew the layer as; without it the facts follow the saved style.
 */
export function legendFacts(layer: LegendLayer, drawn?: DrawnLayer): LegendFacts | null {
  if (isFolderGroupLayer(layer) || isDemTerrainVisualSuppressed(layer)) return null;
  const kind = drawn?.drawsAs ?? drawsAs(layer);
  const swatch = swatchFor(layer, kind);
  return {
    name: legendEntryName(layer) ?? '',
    drawsAs: kind,
    swatch,
    classes: classesFor(layer, kind, swatch),
    ramp: rampFor(layer, kind),
    weightColumn: weightColumnFor(layer, kind),
    cluster: clusterFor(layer, kind),
  };
}
