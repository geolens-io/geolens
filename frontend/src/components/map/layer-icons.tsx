import { useMemo } from 'react';
import { Circle, Pentagon, Grid3x3, Layers } from 'lucide-react';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { MAP_COLORS } from '@/lib/map-colors';
import { patternPreviewStyle } from '@/lib/fill-pattern-preview';
import type { MapLayerResponse } from '@/types/api';
import { legendFacts, rampGradient } from './legend-facts';
import type { LegendFacts, LegendRamp, LegendSwatch } from './legend-facts';

/** Shape hints for the icon glyph. Its stroke, fill opacity and pattern come from the layer's legend swatch. */
export interface StyleHints {
  dashPattern?: number[];    // line-dasharray (e.g., [4,2])
  opacity?: number;          // layer opacity (0-1)
  strokeWidth?: number;      // line-width raw value — map to SVG strokeWidth
  radius?: number;           // circle-radius raw value — map to SVG size hint
  isHeatmap?: boolean;       // render_mode === 'heatmap' — triggers radial gradient icon
}

/**
 * Extract the icon's shape hints from paint/layout objects.
 * Reads custom conventions (legacy line-dasharray in layout, etc.).
 */
export function extractStyleHints(
  paint: Record<string, unknown>,
  layout: Record<string, unknown>,
  geometryType: string | null,
  opacity?: number,
  styleConfig?: { render_mode?: string } | null,
): StyleHints {
  const gt = (geometryType ?? '').toUpperCase();
  const hints: StyleHints = {};

  if (styleConfig?.render_mode === 'heatmap') {
    hints.isHeatmap = true;
  }

  if (opacity !== undefined && opacity < 1) {
    hints.opacity = opacity;
  }

  if (gt.includes('LINE')) {
    const lw = paint['line-width'];
    if (typeof lw === 'number') hints.strokeWidth = lw;
    const dash = paint['line-dasharray'] ?? layout['line-dasharray'];
    if (Array.isArray(dash) && dash.length > 0) {
      hints.dashPattern = dash as number[];
    }
  }

  if (gt.includes('POINT')) {
    const cr = paint['circle-radius'];
    if (typeof cr === 'number') hints.radius = cr;
  }

  return hints;
}

interface IconSubProps {
  colors: string[];
  layerId: string;
  opacityStyle?: React.CSSProperties;
  styleHints?: StyleHints;
  swatch?: LegendSwatch | null;
  ramp?: LegendRamp | null;
  /** ux(#840): render multi-color fills as hard-stop bands instead of a smooth ramp. */
  discrete?: boolean;
}

/** The swatch's fill opacity as an SVG attribute: omitted when fully opaque. */
function fillOpacityOf(swatch?: LegendSwatch | null): number | undefined {
  return swatch && swatch.fillOpacity < 1 ? swatch.fillOpacity : undefined;
}

/**
 * Categories are discrete classes, so their icon draws bands instead of blurring
 * them into a continuous ramp.
 */
export function isDiscreteColorStyle(facts: LegendFacts | null): boolean {
  return facts?.classes?.some((classes) => classes.mode === 'categorical') ?? false;
}

// ux(#840): bands inside the existing glyph, not separate chips — keeps the
// geometry-type cue and the 22px row cell untouched. Cap at 4 bands; beyond
// that 14px slivers are unreadable and the row subtitle carries the count.
const MAX_DISCRETE_BANDS = 4;

function gradientStops(colors: string[], discrete?: boolean) {
  if (!discrete) {
    return colors.map((c, i) => (
      <stop key={i} offset={`${(i / (colors.length - 1)) * 100}%`} stopColor={c} />
    ));
  }
  const bands = colors.slice(0, MAX_DISCRETE_BANDS);
  return bands.flatMap((c, i) => [
    <stop key={`${i}-start`} offset={`${(i / bands.length) * 100}%`} stopColor={c} />,
    <stop key={`${i}-end`} offset={`${((i + 1) / bands.length) * 100}%`} stopColor={c} />,
  ]);
}

function HeatmapIcon({ colors, layerId, opacityStyle, ramp }: IconSubProps) {
  const gradientId = `layer-heat-${layerId}`;
  const stops = ramp ? rampGradient(ramp) : colors.map((color, i) => ({ color, offset: i / (colors.length - 1) }));
  return (
    <span className="relative inline-flex h-3.5 w-3.5 items-center justify-center" style={opacityStyle}>
      <svg width="14" height="14" viewBox="0 0 14 14" className="h-3.5 w-3.5">
        <defs>
          <radialGradient id={gradientId}>
            {stops.map(({ color, offset }, i) => (
              <stop key={i} offset={`${offset * 100}%`} stopColor={color} />
            ))}
          </radialGradient>
        </defs>
        <circle cx="7" cy="7" r="6.5" fill={`url(#${gradientId})`} />
      </svg>
    </span>
  );
}

function LineIcon({ colors, layerId, opacityStyle, styleHints, swatch, discrete }: IconSubProps) {
  const rawSW = styleHints?.strokeWidth;
  const svgStrokeWidth = rawSW !== undefined ? (rawSW <= 1.5 ? 2 : rawSW > 4 ? 4.5 : 3) : 3;
  const color = colors[0] ?? MAP_COLORS.icon.fallback;
  const hasGradient = colors.length > 1;
  const gradientId = `layer-grad-${layerId}`;
  const dashArray = styleHints?.dashPattern
    ? styleHints.dashPattern.map((v) => v * 1.5).join(' ')
    : undefined;
  const strokeColor = hasGradient ? `url(#${gradientId})` : color;

  return (
    <span className="relative inline-flex h-3.5 w-3.5 items-center justify-center" style={opacityStyle}>
      <svg width="14" height="14" viewBox="0 0 14 14" className="h-3.5 w-3.5">
        {hasGradient && (
          <defs>
            {/* userSpaceOnUse, not the objectBoundingBox default: a horizontal
                line has a zero-height bounding box, and the SVG spec disables
                rendering of any element painted by a bounding-box-united
                gradient when either bbox dimension is zero — so every
                multi-color line icon (categorical bands and graduated ramps
                alike) drew nothing. The coordinates pin the gradient to the
                line's own endpoints. */}
            <linearGradient id={gradientId} gradientUnits="userSpaceOnUse" x1="1" y1="7" x2="13" y2="7">
              {gradientStops(colors, discrete)}
            </linearGradient>
          </defs>
        )}
        <line x1="1" y1="7" x2="13" y2="7" stroke={strokeColor} strokeOpacity={fillOpacityOf(swatch)} strokeWidth={svgStrokeWidth} strokeLinecap="round" strokeDasharray={dashArray} />
      </svg>
    </span>
  );
}

function ShapeIcon({ colors, layerId, opacityStyle, styleHints, swatch, isPoint, discrete }: IconSubProps & { isPoint: boolean }) {
  let sizeClass = 'h-3.5 w-3.5';
  if (isPoint && styleHints?.radius !== undefined) {
    sizeClass = styleHints.radius <= 3 ? 'h-2.5 w-2.5' : styleHints.radius > 7 ? 'h-4.5 w-4.5' : 'h-3.5 w-3.5';
  }
  const Icon = isPoint ? Circle : Pentagon;
  const ring = swatch?.stroke ?? null;
  const fillOpacity = fillOpacityOf(swatch);

  // A patterned polygon draws the pattern INSTEAD of a fill. Deliberately a
  // square chip, matching the picker and legend chips: the pentagon glyph has no
  // fill we can pattern without duplicating all five patterns as SVG defs.
  if (!isPoint && swatch?.pattern) {
    // fillOpacity dims the pattern only, as a nested layer, never the border,
    // which must stay opaque for a stroke-only style (fillOpacity 0) to show.
    const patternFillStyle: React.CSSProperties = {
      color: swatch.pattern.tint ?? colors[0] ?? MAP_COLORS.icon.fallback,
      ...patternPreviewStyle(swatch.pattern.id),
    };
    if (fillOpacity !== undefined) patternFillStyle.opacity = fillOpacity;
    return (
      <span
        className="relative inline-block h-3.5 w-3.5 shrink-0 overflow-hidden rounded-sm border"
        style={{
          borderColor: ring?.color ?? 'transparent',
          ...opacityStyle,
        }}
        aria-hidden="true"
      >
        <span className="absolute inset-0" style={patternFillStyle} />
      </span>
    );
  }

  if (colors.length <= 1) {
    const color = colors[0] ?? MAP_COLORS.icon.fallback;
    const stroke = ring ? { stroke: ring.color, strokeWidth: isPoint ? 2 : 2.5 } : { strokeWidth: 0 };
    return (
      <span style={opacityStyle} className="inline-flex">
        {/* fillOpacity on the SVG fill, not the span: a stroke-only style
            (fill-opacity: 0) must leave the outline visible. */}
        <Icon className={sizeClass} fill={color} fillOpacity={fillOpacity} {...stroke} />
      </span>
    );
  }

  const gradientId = `layer-grad-${layerId}`;
  const stroke = ring ? { stroke: ring.color, strokeWidth: isPoint ? 1.5 : 2.5 } : { strokeWidth: 0 };

  return (
    <span className="relative inline-flex" style={opacityStyle}>
      <span className={`relative inline-flex ${sizeClass}`}>
        <svg width="0" height="0" className="absolute">
          <defs>
            <linearGradient id={gradientId}>
              {gradientStops(colors, discrete)}
            </linearGradient>
          </defs>
        </svg>
        <Icon className={sizeClass} fill={`url(#${gradientId})`} fillOpacity={fillOpacity} {...stroke} />
      </span>
    </span>
  );
}

export function ColorizedGeometryIcon({
  geometryType,
  colors,
  layerId,
  layerType,
  styleHints,
  swatch,
  ramp,
  discrete,
}: {
  geometryType: string | null;
  colors: string[];
  layerId: string;
  layerType?: string;
  styleHints?: StyleHints;
  /** The layer's legend swatch: its stroke, fill opacity and pattern. */
  swatch?: LegendSwatch | null;
  /** A heatmap's colour ramp, drawn at its own stops. */
  ramp?: LegendRamp | null;
  /** ux(#840): true for categorical styles — hard-stop bands instead of a smooth ramp. */
  discrete?: boolean;
}) {
  if (layerType === 'vrt') return <Layers className="h-3.5 w-3.5 text-muted-foreground" />;
  if (layerType === 'raster') return <Grid3x3 className="h-3.5 w-3.5 text-muted-foreground" />;

  const gt = (geometryType ?? '').toUpperCase();
  // Element-level opacity is for the LAYER opacity only. The sub-icons apply the
  // swatch's fillOpacity to the specific SVG attribute (fill-opacity or
  // stroke-opacity), so a stroke-only style keeps the outline it's drawn with.
  const layerOpacity = styleHints?.opacity ?? 1;
  const opacityStyle: React.CSSProperties | undefined = layerOpacity < 1 ? { opacity: layerOpacity } : undefined;
  const sub: IconSubProps = { colors, layerId, opacityStyle, styleHints, swatch, ramp, discrete };

  if (styleHints?.isHeatmap && colors.length > 1) return <HeatmapIcon {...sub} />;
  if (gt.includes('LINE')) return <LineIcon {...sub} />;
  return <ShapeIcon {...sub} isPoint={gt.includes('POINT')} />;
}

/**
 * The colours a layer's icon draws: the heatmap ramp, else the swatch's constant
 * colour or pattern tint, else the colour classes.
 */
export function getLayerColors(facts: LegendFacts | null): string[] {
  if (facts?.ramp) return facts.ramp.colors;
  const constant = facts?.swatch?.fill ?? facts?.swatch?.pattern?.tint;
  if (constant) return [constant];
  const classes = facts?.classes ?? [];
  const colorClasses = classes.find((entry) => entry.target === 'color');
  if (colorClasses) return colorClasses.items.map((item) => item.color);
  // A size classification's items carry the colour each size class draws in.
  if (classes.length) return [...new Set(classes[0].items.map((item) => item.color))];
  return [MAP_COLORS.icon.fallback];
}

/**
 * fix(#452): shared glyph chip for raster-family layers. StackRow, the builder
 * LegendPlugin, and the viewer LayerLegend all render this one component so the
 * legend icon can never drift from the layer-stack icon again.
 */
export function RasterGlyphChip({ glyph }: { glyph: string }) {
  return (
    <span
      className="flex items-center justify-center h-[22px] w-[22px] shrink-0 rounded-sm bg-[--type-raster-bg] text-[--type-raster] text-xs font-semibold"
      aria-hidden="true"
    >
      {glyph}
    </span>
  );
}

/** Glyph for the DEM chip by effective render mode (⛰ hillshade, ◬ terrain-only, ▦ image). */
export function demChipGlyph(renderMode: unknown): string {
  if (renderMode === 'hillshade') return '⛰';
  if (renderMode === 'terrain') return '◬';
  return '▦';
}

export type LayerTypeIconLayer = Pick<MapLayerResponse, 'dataset_geometry_type'> &
  Partial<
    Pick<
      MapLayerResponse,
      'layer_type' | 'dataset_record_type' | 'is_dem' | 'paint' | 'layout' | 'opacity' | 'style_config'
    >
  >;

/**
 * fix(#452): single source of truth for a layer's type icon, shared by the
 * builder layer stack and BOTH legend surfaces (LegendPlugin, viewer
 * LayerLegend). Raster/VRT layers get the glyph chip (▦, DEM: ⛰/◬); vector
 * layers get the colorized geometry icon. Extracted from StackRow.TypeIcon.
 */
export function LayerTypeIcon({ layer, iconId }: { layer: LayerTypeIconLayer; iconId: string }) {
  const caps = getLayerCapabilities({
    layer_type: layer.layer_type,
    dataset_record_type: layer.dataset_record_type,
    dataset_geometry_type: layer.dataset_geometry_type,
  });
  const paint = layer.paint ?? {};
  const layout = layer.layout ?? {};
  // Memoize on the exact fields each extraction reads: `paint` and `layout`
  // above are fresh fallback objects on every render.
  const styleHints = useMemo(
    () => extractStyleHints(paint, layout, layer.dataset_geometry_type, layer.opacity, layer.style_config),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layer.paint, layer.layout, layer.dataset_geometry_type, layer.opacity, layer.style_config],
  );
  const facts = useMemo(
    () => legendFacts({
      layer_type: layer.layer_type,
      is_dem: layer.is_dem,
      dataset_geometry_type: layer.dataset_geometry_type,
      paint: layer.paint,
      opacity: layer.opacity,
      style_config: layer.style_config,
    }),
    [layer.layer_type, layer.is_dem, layer.dataset_geometry_type, layer.paint, layer.opacity, layer.style_config],
  );

  if (caps.kind === 'raster' || caps.kind === 'vrt') {
    const renderMode = (layer.style_config as Record<string, unknown> | null | undefined)?.render_mode;
    return <RasterGlyphChip glyph={layer.is_dem === true ? demChipGlyph(renderMode) : '▦'} />;
  }

  return (
    <ColorizedGeometryIcon
      geometryType={layer.dataset_geometry_type}
      colors={getLayerColors(facts)}
      layerId={iconId}
      layerType={caps.kind}
      styleHints={styleHints}
      swatch={facts?.swatch ?? null}
      ramp={facts?.ramp ?? null}
      discrete={isDiscreteColorStyle(facts)}
    />
  );
}
