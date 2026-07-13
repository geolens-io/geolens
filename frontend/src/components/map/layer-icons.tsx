import { useMemo } from 'react';
import { Circle, Pentagon, Grid3x3, Layers } from 'lucide-react';
import { getColorProperty, getRampColors } from '@/lib/color-ramps';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { MAP_COLORS } from '@/lib/map-colors';
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

  if (paint['_stroke-disabled']) {
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
    if (!paint['_stroke-disabled']) {
      const oc = paint['_outline-color'];
      if (typeof oc === 'string') hints.strokeColor = oc;
    }
    const fo = paint['fill-opacity'];
    if (typeof fo === 'number' && fo < 1) hints.fillOpacity = fo;
  }

  if (gt.includes('POINT')) {
    if (!paint['_stroke-disabled']) {
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

function LineIcon({ colors, layerId, opacityStyle, styleHints }: IconSubProps) {
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
            <linearGradient id={gradientId}>
              {colors.map((c, i) => (
                <stop key={i} offset={`${(i / (colors.length - 1)) * 100}%`} stopColor={c} />
              ))}
            </linearGradient>
          </defs>
        )}
        <line x1="1" y1="7" x2="13" y2="7" stroke={strokeColor} strokeWidth={svgStrokeWidth} strokeLinecap="round" strokeDasharray={dashArray} />
      </svg>
    </span>
  );
}

function ShapeIcon({ colors, layerId, opacityStyle, styleHints, isPoint }: IconSubProps & { isPoint: boolean }) {
  let sizeClass = 'h-3.5 w-3.5';
  if (isPoint && styleHints?.radius !== undefined) {
    sizeClass = styleHints.radius <= 3 ? 'h-2.5 w-2.5' : styleHints.radius > 7 ? 'h-4.5 w-4.5' : 'h-3.5 w-3.5';
  }
  const Icon = isPoint ? Circle : Pentagon;
  const showOutline = !styleHints?.strokeDisabled;

  if (colors.length <= 1) {
    const color = colors[0] ?? MAP_COLORS.icon.fallback;
    const stroke = isPoint
      ? (styleHints?.strokeColor ? { stroke: styleHints.strokeColor, strokeWidth: 2 } : { strokeWidth: 0 })
      : showOutline
        ? { stroke: styleHints?.strokeColor ?? darkenColor(color), strokeWidth: 2.5 }
        : { strokeWidth: 0 };
    return (
      <span style={opacityStyle} className="inline-flex">
        <Icon className={sizeClass} fill={color} {...stroke} />
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
              {colors.map((c, i) => (
                <stop key={i} offset={`${(i / (colors.length - 1)) * 100}%`} stopColor={c} />
              ))}
            </linearGradient>
          </defs>
        </svg>
        <Icon className={sizeClass} fill={`url(#${gradientId})`} {...stroke} />
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
}: {
  geometryType: string | null;
  colors: string[];
  layerId: string;
  layerType?: string;
  styleHints?: StyleHints;
}) {
  if (layerType === 'vrt') return <Layers className="h-3.5 w-3.5 text-muted-foreground" />;
  if (layerType === 'raster') return <Grid3x3 className="h-3.5 w-3.5 text-muted-foreground" />;

  const gt = (geometryType ?? '').toUpperCase();
  const compoundOpacity = (styleHints?.opacity ?? 1) * (styleHints?.fillOpacity ?? 1);
  const opacityStyle: React.CSSProperties | undefined = compoundOpacity < 1 ? { opacity: compoundOpacity } : undefined;
  const sub: IconSubProps = { colors, layerId, opacityStyle, styleHints };

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
    />
  );
}
