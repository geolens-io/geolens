import { useMemo } from 'react';
import { Circle, Pentagon, Grid3x3, Layers } from 'lucide-react';
import { getColorProperty, getRampColors } from '@/lib/color-ramps';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { MAP_COLORS } from '@/lib/map-colors';
import { fillPatternFromPaint, fillPatternTint, patternPreviewStyle } from '@/lib/fill-pattern-preview';
import type { MapLayerResponse } from '@/types/api';

/** Darken a hex color by reducing each channel by ~30% for outline contrast */
function darkenColor(hex: string): string {
  const m = hex.match(/^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i);
  if (!m) return MAP_COLORS.icon.invalidColor;
  const darken = (ch: string) => Math.max(0, Math.round(parseInt(ch, 16) * 0.6)).toString(16).padStart(2, '0');
  return `#${darken(m[1])}${darken(m[2])}${darken(m[3])}`;
}

export interface StyleHints {
  strokeColor?: string;      // polygon _outline-color or circle-stroke-color
  strokeDisabled?: boolean;  // _stroke-disabled — suppresses outline rendering
  dashPattern?: number[];    // line-dasharray (e.g., [4,2])
  opacity?: number;          // layer opacity (0-1)
  fillOpacity?: number;      // paint-level opacity (circle-opacity, fill-opacity, line-opacity)
  strokeWidth?: number;      // line-width raw value — map to SVG strokeWidth
  radius?: number;           // circle-radius raw value — map to SVG size hint
  isHeatmap?: boolean;       // render_mode === 'heatmap' — triggers radial gradient icon
  fillPattern?: string;      // fix(#951): paint['fill-pattern'] — the swatch draws the pattern
  fillPatternColor?: string; // fix(#914): the colour the MAP tints that pattern with
}

/**
 * Extract style hints from paint/layout objects for icon rendering.
 * Reads custom conventions (_outline-color, legacy line-dasharray in layout, etc.).
 */
export function extractStyleHints(
  paint: Record<string, unknown>,
  layout: Record<string, unknown>,
  geometryType: string | null,
  opacity?: number,
  // fix(#914): `builder` is read for the fill-pattern tint stash.
  // fix(#1288): also read for outlineColor and strokeDisabled — the renderer
  // draws from builder state, so the swatch must prefer it over the paint
  // mirror below, which can go stale (paint keeps the color/flag a layer had
  // before its last edit).
  styleConfig?: {
    render_mode?: string;
    builder?: { fillColorSaved?: string; outlineColor?: string; strokeDisabled?: boolean; outlineWidth?: number };
  } | null,
): StyleHints {
  const gt = (geometryType ?? '').toUpperCase();
  const hints: StyleHints = {};

  if (styleConfig?.render_mode === 'heatmap') {
    hints.isHeatmap = true;
  }

  if (opacity !== undefined && opacity < 1) {
    hints.opacity = opacity;
  }

  // fix(#1288 codex): builder.strokeDisabled wins over the paint mirror ONLY
  // where the real map renderer also consults builder state — fill-adapter.ts
  // (polygons and the mixed GEOMETRY adapter's fill sublayer). circle-adapter.ts
  // (points) applies circle paint properties directly and never reads
  // style_config.builder, so a point must resolve purely from paint below —
  // otherwise a stale builder.strokeDisabled (e.g. after an Advanced JSON/API
  // edit restored a real stroke) would hide a stroke the map still draws.
  const isPoint = gt.includes('POINT');
  const strokeDisabled = isPoint
    ? !!paint['_stroke-disabled']
    : Boolean(styleConfig?.builder?.strokeDisabled ?? paint['_stroke-disabled']);
  if (strokeDisabled) {
    hints.strokeDisabled = true;
  }

  if (gt.includes('LINE')) {
    const lw = paint['line-width'];
    if (typeof lw === 'number') hints.strokeWidth = lw;
    const dash = paint['line-dasharray'] ?? layout['line-dasharray'];
    if (Array.isArray(dash) && dash.length > 0) {
      hints.dashPattern = dash as number[];
    }
    const lo = paint['line-opacity'];
    if (typeof lo === 'number' && lo < 1) hints.fillOpacity = lo;
  } else if (gt.includes('POLYGON')) {
    // fix(#1288 codex): an explicit zero-width outline draws nothing on the
    // map — builder.outlineWidth wins over the paint mirror, same precedence
    // as outlineColor/strokeDisabled — so treat it as a disabled stroke
    // instead of drawing ShapeIcon's fixed-width outline for a layer that
    // renders none.
    const ow = styleConfig?.builder?.outlineWidth ?? paint['_outline-width'];
    const outlineDisabled = strokeDisabled || (typeof ow === 'number' && ow === 0);
    if (outlineDisabled) {
      hints.strokeDisabled = true;
    } else {
      // fix(#1288): builder.outlineColor wins over the flat paint mirror.
      const oc = styleConfig?.builder?.outlineColor ?? paint['_outline-color'];
      if (typeof oc === 'string') hints.strokeColor = oc;
    }
    const fo = paint['fill-opacity'];
    if (typeof fo === 'number' && fo < 1) hints.fillOpacity = fo;
  }

  // fix(#951 review): read the pattern independently of the POLYGON-only branch
  // above — a GEOMETRY / GEOMETRYCOLLECTION layer renders a fill sublayer via
  // the mixed adapter and gets the shape icon, but matches neither branch.
  hints.fillPattern = fillPatternFromPaint(paint);
  // fix(#914): a pattern deletes fill-color, so `colors[0]` below falls back to a
  // default while the map tints from the stash — resolve the map's colour here.
  hints.fillPatternColor = fillPatternTint(paint, styleConfig?.builder);

  if (isPoint) {
    // fix(#1288 codex): an explicit circle-stroke-width of 0 draws nothing on
    // the map (no builder mirror exists for it, unlike the polygon outline
    // width, so this reads paint directly) — treat it as a disabled stroke,
    // same as the polygon outline-width fix above.
    const csw = paint['circle-stroke-width'];
    const pointStrokeDisabled = strokeDisabled || (typeof csw === 'number' && csw === 0);
    if (pointStrokeDisabled) {
      hints.strokeDisabled = true;
    } else {
      const sc = paint['circle-stroke-color'];
      if (typeof sc === 'string') hints.strokeColor = sc;
    }
    const cr = paint['circle-radius'];
    if (typeof cr === 'number') hints.radius = cr;
    const co = paint['circle-opacity'];
    if (typeof co === 'number' && co < 1) hints.fillOpacity = co;
  }

  return hints;
}

interface IconSubProps {
  colors: string[];
  layerId: string;
  opacityStyle?: React.CSSProperties;
  styleHints?: StyleHints;
  /** ux(#840): render multi-color fills as hard-stop bands instead of a smooth ramp. */
  discrete?: boolean;
}

/**
 * ux(#840): a categorical style is a set of discrete classes — its icon must
 * not blur them into a continuous ramp. Heatmaps keep their smooth ramp icon.
 * codex(#841): symbol mode keeps the top-level column/categories only for
 * round-tripping back to points while rendering marker icons (possibly
 * categorized on a different column via builder.symbol) — exclude it too.
 */
export function isDiscreteColorStyle(styleConfig: MapLayerResponse['style_config']): boolean {
  return (
    !!styleConfig?.categories?.length
    && styleConfig.render_mode !== 'heatmap'
    && styleConfig.render_mode !== 'symbol'
  );
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

function HeatmapIcon({ colors, layerId, opacityStyle }: IconSubProps) {
  const gradientId = `layer-heat-${layerId}`;
  return (
    <span className="relative inline-flex h-3.5 w-3.5 items-center justify-center" style={opacityStyle}>
      <svg width="14" height="14" viewBox="0 0 14 14" className="h-3.5 w-3.5">
        <defs>
          <radialGradient id={gradientId}>
            {colors.map((c, i) => (
              <stop key={i} offset={`${(i / (colors.length - 1)) * 100}%`} stopColor={c} />
            ))}
          </radialGradient>
        </defs>
        <circle cx="7" cy="7" r="6.5" fill={`url(#${gradientId})`} />
      </svg>
    </span>
  );
}

function LineIcon({ colors, layerId, opacityStyle, styleHints, discrete }: IconSubProps) {
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
        <line x1="1" y1="7" x2="13" y2="7" stroke={strokeColor} strokeOpacity={styleHints?.fillOpacity} strokeWidth={svgStrokeWidth} strokeLinecap="round" strokeDasharray={dashArray} />
      </svg>
    </span>
  );
}

function ShapeIcon({ colors, layerId, opacityStyle, styleHints, isPoint, discrete }: IconSubProps & { isPoint: boolean }) {
  let sizeClass = 'h-3.5 w-3.5';
  if (isPoint && styleHints?.radius !== undefined) {
    sizeClass = styleHints.radius <= 3 ? 'h-2.5 w-2.5' : styleHints.radius > 7 ? 'h-4.5 w-4.5' : 'h-3.5 w-3.5';
  }
  const Icon = isPoint ? Circle : Pentagon;
  const showOutline = !styleHints?.strokeDisabled;

  // fix(#951): a patterned polygon draws the pattern INSTEAD of a fill, so the
  // swatch shows the pattern rather than a solid colour that appears nowhere on
  // the map. Deliberately a square chip, matching the picker and legend chips —
  // the pentagon glyph has no fill we can pattern without duplicating all five
  // patterns as SVG defs.
  if (!isPoint && styleHints?.fillPattern) {
    // fix(#1288 codex): fillOpacity dims the PATTERN only, as a nested layer —
    // plain CSS opacity, so it works for `color` in any format the pattern's
    // `currentColor` resolves to — and never the border, which must stay fully
    // opaque for a stroke-only style (fillOpacity 0) to remain visible.
    const patternFillStyle: React.CSSProperties = {
      color: styleHints.fillPatternColor ?? colors[0] ?? MAP_COLORS.icon.fallback,
      ...patternPreviewStyle(styleHints.fillPattern),
    };
    if (styleHints.fillOpacity !== undefined && styleHints.fillOpacity < 1) {
      patternFillStyle.opacity = styleHints.fillOpacity;
    }
    return (
      <span
        className="relative inline-block h-3.5 w-3.5 shrink-0 overflow-hidden rounded-sm border"
        style={{
          borderColor: showOutline ? (styleHints.strokeColor ?? MAP_COLORS.icon.outline) : 'transparent',
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
    const stroke = isPoint
      ? (styleHints?.strokeColor ? { stroke: styleHints.strokeColor, strokeWidth: 2 } : { strokeWidth: 0 })
      : showOutline
        ? { stroke: styleHints?.strokeColor ?? darkenColor(color), strokeWidth: 2.5 }
        : { strokeWidth: 0 };
    return (
      <span style={opacityStyle} className="inline-flex">
        {/* fix(#1288): fillOpacity on the SVG fill, not the span — a stroke-only
            style (fill-opacity: 0) must leave the outline (stroke above) visible. */}
        <Icon className={sizeClass} fill={color} fillOpacity={styleHints?.fillOpacity} {...stroke} />
      </span>
    );
  }

  const gradientId = `layer-grad-${layerId}`;
  const stroke = !isPoint && showOutline
    ? { stroke: styleHints?.strokeColor ?? MAP_COLORS.icon.outline, strokeWidth: 2.5 }
    : styleHints?.strokeColor
      ? { stroke: styleHints.strokeColor, strokeWidth: 1.5 }
      : { strokeWidth: 0 };

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
        <Icon className={sizeClass} fill={`url(#${gradientId})`} fillOpacity={styleHints?.fillOpacity} {...stroke} />
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
  discrete,
}: {
  geometryType: string | null;
  colors: string[];
  layerId: string;
  layerType?: string;
  styleHints?: StyleHints;
  /** ux(#840): true for categorical styles — hard-stop bands instead of a smooth ramp. */
  discrete?: boolean;
}) {
  if (layerType === 'vrt') return <Layers className="h-3.5 w-3.5 text-muted-foreground" />;
  if (layerType === 'raster') return <Grid3x3 className="h-3.5 w-3.5 text-muted-foreground" />;

  const gt = (geometryType ?? '').toUpperCase();
  // fix(#1288): element-level opacity is for the LAYER opacity only. fillOpacity
  // (paint's fill-/circle-/line-opacity) is a per-element hint the sub-icons
  // apply to the specific SVG attribute (fill-opacity or stroke-opacity) so a
  // stroke-only style (fill-opacity: 0) doesn't hide the outline it's drawn with.
  const layerOpacity = styleHints?.opacity ?? 1;
  const opacityStyle: React.CSSProperties | undefined = layerOpacity < 1 ? { opacity: layerOpacity } : undefined;
  const sub: IconSubProps = { colors, layerId, opacityStyle, styleHints, discrete };

  if (styleHints?.isHeatmap && colors.length > 1) return <HeatmapIcon {...sub} />;
  if (gt.includes('LINE')) return <LineIcon {...sub} />;
  return <ShapeIcon {...sub} isPoint={gt.includes('POINT')} />;
}

export function getLayerColors(layer: Pick<MapLayerResponse, 'dataset_geometry_type' | 'paint' | 'style_config'>): string[] {
  // Heatmap: extract from ramp name
  if (layer.style_config?.render_mode === 'heatmap') {
    const rampName = (layer.paint?.['_heatmap-ramp'] as string) ?? layer.style_config.ramp ?? 'YlOrRd';
    return getRampColors(rampName, 5);
  }
  const colorKey = getColorProperty(layer.dataset_geometry_type);
  const value = layer.paint?.[colorKey];
  if (typeof value === 'string') return [value];
  if (layer.style_config?.categories?.length)
    return layer.style_config.categories.map((c) => c.color);
  if (layer.style_config?.colors?.length)
    return layer.style_config.colors;
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
  // GUARD-04 (moved from StackRow.TypeIcon): memoize hint extraction on the
  // exact fields it reads.
  const styleHints = useMemo(
    () => extractStyleHints(paint, layout, layer.dataset_geometry_type, layer.opacity, layer.style_config),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layer.paint, layer.layout, layer.dataset_geometry_type, layer.opacity, layer.style_config],
  );

  if (caps.kind === 'raster' || caps.kind === 'vrt') {
    const renderMode = (layer.style_config as Record<string, unknown> | null | undefined)?.render_mode;
    return <RasterGlyphChip glyph={layer.is_dem === true ? demChipGlyph(renderMode) : '▦'} />;
  }

  return (
    <ColorizedGeometryIcon
      geometryType={layer.dataset_geometry_type}
      colors={getLayerColors({
        dataset_geometry_type: layer.dataset_geometry_type,
        paint,
        style_config: layer.style_config ?? null,
      })}
      layerId={iconId}
      layerType={caps.kind}
      styleHints={styleHints}
      discrete={isDiscreteColorStyle(layer.style_config ?? null)}
    />
  );
}
